"""DynamoDB implementation of the ``Repo`` interface (one table, on-demand billing).

Records are the same SQLAlchemy model classes the SQL backend uses, built *detached* (no session), so routes and services read
them identically. Layout (partition key ``pk``, sort key ``sk``; GSI1 on ``gsi1pk`` / ``gsi1sk``):

    USER#<name>   META                 a user                              GSI1  USERS  / <name>
    CASE#<id>     META                 case scalars (small: it is indexed) GSI1  CASES  / <created_at>#<id>
    CASE#<id>     DETAIL               the decision and fraud JSON (large)
    CASE#<id>     DOC#<position>       one document, with its agent output
    CASE#<id>     RUN#<n>              agent run rows
    CASE#<id>     EVT#<id>             progress events (expire after a week)
    CASE#<id>     OVR#<id>             overrides
    CASE#<id>     AUDIT#<seq>          (GSI1 only) a case's audit entries     GSI1  CASE#<id> / AUDIT#<seq>
    AUDIT         <seq>                the global hash chain, one item per event
    POLICY        <id>                 uploaded policies
    IDEM#<user>#<key>  META            idempotency guard (conditional put)
    COUNTER#<name>     META            atomic counters for override and policy ids

Large JSON columns are stored as JSON strings, which avoids float/Decimal conversion and keeps item sizes predictable.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, ClassVar

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError
from sqlalchemy import JSON, Boolean, DateTime, Float, Integer
from sqlalchemy.sql.schema import Column

from medishield.db.models import (
    AgentRunRow,
    AuditEvent,
    Case,
    CaseEvent,
    Document,
    Override,
    PolicyDoc,
    User,
    utcnow,
)
from medishield.db.repo import Repo

EVENT_TTL_SECONDS = 7 * 24 * 3600
LIGHT_DOC_FIELDS = ("doc_id", "position", "filename", "doc_type", "decision", "media_type", "storage_key", "size_bytes",
                    "sha256", "page", "forced_type")
HEAVY_EXTRACTION_KEYS = ("bounding_boxes", "raw_text")        # large, unused after the pipeline (the UI reads ``fields``)
CASE_DETAIL_COLUMNS = ("decision", "fraud")
MAX_ITEM_BYTES = 380_000


def _num(i: int, width: int = 20) -> str:
    return f"{i:0{width}d}"


# ── record <-> item ───────────────────────────────────────────────────────────────────────────────────
def _default(col: Column) -> Any:
    d = col.default
    if d is None:
        return None
    return d.arg(None) if d.is_callable else d.arg


def _base(t):
    """The underlying column type (a TypeDecorator such as UTCDateTime wraps one)."""
    return getattr(t, "impl", t) if hasattr(t, "impl") and not isinstance(t, type) else t


def _encode(col: Column, v: Any) -> Any:
    if v is None:
        return None
    t = _base(col.type)
    if isinstance(t, JSON):
        return json.dumps(v, separators=(",", ":"), default=str)
    if isinstance(t, DateTime):
        return v.astimezone(UTC).isoformat() if v.tzinfo else v.replace(tzinfo=UTC).isoformat()
    if isinstance(t, Float):
        return Decimal(str(round(float(v), 10)))
    return v


def _decode(col: Column, v: Any) -> Any:
    if v is None:
        return None
    t = _base(col.type)
    if isinstance(t, JSON):
        return json.loads(v)
    if isinstance(t, DateTime):
        return datetime.fromisoformat(v)
    if isinstance(t, Float):
        return float(v)
    if isinstance(t, Integer):
        return int(v)
    if isinstance(t, Boolean):
        return bool(v)
    return v


def _columns(cls, only: Iterable[str] | None = None, skip: Iterable[str] = ()):
    skip = set(skip)
    return [c for c in cls.__table__.columns if (only is None or c.name in only) and c.name not in skip]


def to_item(obj: Any, cols: list[Column]) -> dict:
    out = {}
    for c in cols:
        v = getattr(obj, c.name, None)
        if v is None:
            v = _default(c)
            if v is not None:
                setattr(obj, c.name, v)
        v = _encode(c, v)
        if v is not None:
            out[c.name] = v
    return out


def from_item(cls, item: dict, cols: list[Column] | None = None, **extra) -> Any:
    kw = {c.name: _decode(c, item.get(c.name)) for c in (cols if cols is not None else _columns(cls))}
    kw.update(extra)
    return cls(**kw)


def _slim_extraction(ext: dict | None) -> dict | None:
    if not ext:
        return ext
    return {k: v for k, v in ext.items() if k not in HEAVY_EXTRACTION_KEYS}


class DynamoRepo(Repo):
    def __init__(self, table_name: str, region: str, endpoint_url: str = ""):
        self.table_name, self.region, self.endpoint_url = table_name, region, endpoint_url
        self._local = threading.local()                         # boto3 resources are not thread-safe: one per thread
        self._last_event_id = 0
        self._event_lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=8)

    # ── plumbing ─────────────────────────────────────────────────────────────────────────────────────
    @property
    def table(self):
        t = getattr(self._local, "table", None)
        if t is None:
            kw = {"endpoint_url": self.endpoint_url} if self.endpoint_url else {}
            t = boto3.resource("dynamodb", region_name=self.region, **kw).Table(self.table_name)
            self._local.table = t
        return t

    def ensure_table(self) -> None:
        """Create the table (tests and local emulators; production gets it from CloudFormation)."""
        kw = {"endpoint_url": self.endpoint_url} if self.endpoint_url else {}
        client = boto3.client("dynamodb", region_name=self.region, **kw)
        try:
            client.describe_table(TableName=self.table_name)
            return
        except ClientError as e:
            if e.response["Error"]["Code"] != "ResourceNotFoundException":
                raise
        client.create_table(
            TableName=self.table_name, BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[{"AttributeName": n, "AttributeType": "S"} for n in ("pk", "sk", "gsi1pk", "gsi1sk")],
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
            GlobalSecondaryIndexes=[{"IndexName": "gsi1", "Projection": {"ProjectionType": "ALL"},
                                     "KeySchema": [{"AttributeName": "gsi1pk", "KeyType": "HASH"},
                                                   {"AttributeName": "gsi1sk", "KeyType": "RANGE"}]}])
        client.get_waiter("table_exists").wait(TableName=self.table_name)

    def _put(self, item: dict, **kw) -> None:
        size = len(json.dumps(item, default=str))
        if size > MAX_ITEM_BYTES:
            raise ValueError(f"item {item.get('pk')}/{item.get('sk')} is {size} bytes; DynamoDB allows 400 KB")
        self.table.put_item(Item=item, **kw)

    def _query(self, pk: str | None = None, *, sk_prefix: str | None = None, sk_between: tuple[str, str] | None = None,
               index: str | None = None, reverse: bool = False, limit: int | None = None, consistent: bool = False,
               projection: str | None = None, names: dict | None = None) -> list[dict]:
        pk_name, sk_name = ("gsi1pk", "gsi1sk") if index else ("pk", "sk")
        cond = Key(pk_name).eq(pk)
        if sk_prefix is not None:
            cond = cond & Key(sk_name).begins_with(sk_prefix)
        elif sk_between is not None:
            cond = cond & Key(sk_name).between(*sk_between)
        kw: dict[str, Any] = {"KeyConditionExpression": cond, "ScanIndexForward": not reverse}
        if index:
            kw["IndexName"] = index
        elif consistent:
            kw["ConsistentRead"] = True
        if projection:
            kw["ProjectionExpression"] = projection
            kw["ExpressionAttributeNames"] = names or {}
        items: list[dict] = []
        while True:
            if limit is not None:
                kw["Limit"] = limit - len(items)
            r = self.table.query(**kw)
            items += r.get("Items", [])
            if limit is not None and len(items) >= limit:
                return items[:limit]
            if "LastEvaluatedKey" not in r:
                return items
            kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]

    def _counter(self, name: str) -> int:
        r = self.table.update_item(Key={"pk": f"COUNTER#{name}", "sk": "META"}, UpdateExpression="ADD v :one",
                                   ExpressionAttributeValues={":one": 1}, ReturnValues="UPDATED_NEW")
        return int(r["Attributes"]["v"])

    def _delete_all(self, pk: str, prefix: str) -> None:
        keys = self._query(pk, sk_prefix=prefix, projection="pk, sk")
        with self.table.batch_writer() as bw:
            for k in keys:
                bw.delete_item(Key={"pk": k["pk"], "sk": k["sk"]})

    def commit(self) -> None:                                   # every write is already durable
        return None

    # ── users ────────────────────────────────────────────────────────────────────────────────────────
    def _user(self, item: dict) -> User:
        return from_item(User, item, id=0)

    def get_user(self, username):
        r = self.table.get_item(Key={"pk": f"USER#{username}", "sk": "META"}, ConsistentRead=True).get("Item")
        return self._user(r) if r else None

    def list_users(self):
        return [self._user(i) for i in self._query("USERS", index="gsi1")]

    def add_user(self, username, display_name, role, password_hash):
        u = User(username=username, display_name=display_name, role=role, password_hash=password_hash, active=True)
        item = to_item(u, _columns(User, skip=("id",)))
        item.update(pk=f"USER#{username}", sk="META", gsi1pk="USERS", gsi1sk=username)
        self._put(item)

    # ── cases ────────────────────────────────────────────────────────────────────────────────────────
    _CASE_META: ClassVar[list] = [c for c in Case.__table__.columns if c.name not in CASE_DETAIL_COLUMNS]
    _CASE_DETAIL: ClassVar[list] = [c for c in Case.__table__.columns if c.name in CASE_DETAIL_COLUMNS]
    _DOC_COLS = _columns(Document, skip=("id",))
    _LIGHT_DOC_COLS = _columns(Document, only=LIGHT_DOC_FIELDS)

    def _case_from(self, item: dict, documents: list[Document]) -> Case:
        case = from_item(Case, item, cols=self._CASE_META)
        case.documents = documents
        return case

    def _doc_from(self, item: dict, case_id: str, cols=None) -> Document:
        return from_item(Document, item, cols=cols or self._DOC_COLS, case_id=case_id, id=0)

    def get_case(self, case_id):
        rows = self._query(f"CASE#{case_id}", sk_between=("DETAIL", "DOC#~"), consistent=True)
        meta = self.table.get_item(Key={"pk": f"CASE#{case_id}", "sk": "META"}, ConsistentRead=True).get("Item")
        if not meta:
            return None
        docs = [self._doc_from(i, case_id) for i in rows if i["sk"].startswith("DOC#")]
        case = self._case_from(meta, docs)
        for i in rows:
            if i["sk"] == "DETAIL":
                for c in self._CASE_DETAIL:
                    setattr(case, c.name, _decode(c, i.get(c.name)))
        return case

    def _light(self, case_id_item: dict) -> Case:
        """A list-view case: scalars and document stubs only (no decision/fraud JSON, no extractions). Do not save it."""
        case_id = case_id_item["id"]
        names = {f"#{n}": n for n in LIGHT_DOC_FIELDS}
        docs = self._query(f"CASE#{case_id}", sk_prefix="DOC#", projection=", ".join(names), names=names)
        return self._case_from(case_id_item, [self._doc_from(d, case_id, cols=self._LIGHT_DOC_COLS) for d in docs])

    def _many(self, items: list[dict]) -> list[Case]:
        return list(self._pool.map(self._light, items))

    def find_case_by_idempotency(self, username, key):
        r = self.table.get_item(Key={"pk": f"IDEM#{username}#{key}", "sk": "META"}, ConsistentRead=True).get("Item")
        return self.get_case(r["case_id"]) if r else None

    def add_case(self, case):
        if case.idempotency_key:
            try:
                self._put({"pk": f"IDEM#{case.submitted_by}#{case.idempotency_key}", "sk": "META", "case_id": case.id},
                          ConditionExpression=Attr("pk").not_exists())
            except ClientError as e:
                if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
                    raise
                for _ in range(10):                             # the winner may still be writing its case
                    prior = self.find_case_by_idempotency(case.submitted_by, case.idempotency_key)
                    if prior:
                        return prior, False
                    time.sleep(0.2)
                raise
        now = utcnow()
        case.created_at = case.created_at or now
        case.updated_at = now
        for i, d in enumerate(case.documents):
            d.case_id = case.id
            d.position = d.position if d.position is not None else i
            self.save_document(d)
        self.save_case(case)
        return case, True

    def save_case(self, case):
        case.updated_at = utcnow()
        item = to_item(case, self._CASE_META)
        item.update(pk=f"CASE#{case.id}", sk="META", gsi1pk="CASES", gsi1sk=f"{item['created_at']}#{case.id}")
        self._put(item)
        detail = to_item(case, self._CASE_DETAIL)
        if detail:
            self._put({"pk": f"CASE#{case.id}", "sk": "DETAIL", **detail})

    def save_document(self, doc):
        if doc.extraction:
            doc.extraction = _slim_extraction(doc.extraction)
        item = to_item(doc, self._DOC_COLS)
        item.update(pk=f"CASE#{doc.case_id}", sk=f"DOC#{_num(doc.position, 4)}")
        self._put(item)

    def list_cases(self, *, submitted_by=None, status=None, decision=None, limit=50, offset=0):
        metas = self._query("CASES", index="gsi1", reverse=True)
        if submitted_by:
            metas = [m for m in metas if m.get("submitted_by") == submitted_by]
        if status:
            metas = [m for m in metas if m.get("status") == status.upper()]
        if decision:
            metas = [m for m in metas if (m.get("final_decision") or m.get("ai_decision")) == decision.upper()]
        return self._many(metas[offset: offset + limit])

    def all_cases(self):
        return self._many(self._query("CASES", index="gsi1"))

    def cases_by_status(self, status):
        return self._many([m for m in self._query("CASES", index="gsi1") if m.get("status") == status])

    # ── agent runs ───────────────────────────────────────────────────────────────────────────────────
    _RUN_COLS = _columns(AgentRunRow, skip=("id",))

    def replace_agent_runs(self, case_id, runs):
        self._delete_all(f"CASE#{case_id}", "RUN#")
        with self.table.batch_writer() as bw:
            for n, r in enumerate(runs, 1):
                row = AgentRunRow(case_id=case_id, agent=r["agent"], model=r.get("model"), retried_with=r.get("retried_with"),
                                  input_tokens=r["input_tokens"], output_tokens=r["output_tokens"], cost_usd=r["cost_usd"],
                                  cold_cost_usd=r.get("cold_cost_usd", r["cost_usd"]), latency_ms=r["latency_ms"],
                                  llm_calls=r["llm_calls"], cache_hits=r["cache_hits"])
                bw.put_item(Item={**to_item(row, self._RUN_COLS), "pk": f"CASE#{case_id}", "sk": f"RUN#{_num(n, 4)}"})

    def list_agent_runs(self, case_id):
        return [from_item(AgentRunRow, i, cols=self._RUN_COLS, id=n)
                for n, i in enumerate(self._query(f"CASE#{case_id}", sk_prefix="RUN#"), 1)]

    # ── events ───────────────────────────────────────────────────────────────────────────────────────
    _EVT_COLS = _columns(CaseEvent, skip=("id",))

    def _event_id(self) -> int:
        """Monotonic within a process (one worker writes a case's events): microsecond clock, never repeating."""
        with self._event_lock:
            self._last_event_id = max(self._last_event_id + 1, int(time.time() * 1_000_000))
            return self._last_event_id

    def add_event(self, case_id, ev):
        extra = {k: v for k, v in ev.items() if k not in ("node", "status", "doc_id", "ts")}
        row = CaseEvent(case_id=case_id, node=str(ev.get("node", "")), status=str(ev.get("status", "")), doc_id=ev.get("doc_id"),
                        payload=extra)
        eid = self._event_id()
        item = to_item(row, self._EVT_COLS)
        item.update(pk=f"CASE#{case_id}", sk=f"EVT#{_num(eid)}", eid=eid, ttl=int(time.time()) + EVENT_TTL_SECONDS)
        self._put(item)

    def events_after(self, case_id, last_id):
        rows = self._query(f"CASE#{case_id}", sk_between=(f"EVT#{_num(last_id + 1)}", "EVT#99999999999999999999"))
        return [from_item(CaseEvent, i, cols=self._EVT_COLS, id=int(i["eid"])) for i in rows]

    def clear_events(self, case_id):
        self._delete_all(f"CASE#{case_id}", "EVT#")

    # ── overrides ────────────────────────────────────────────────────────────────────────────────────
    _OVR_COLS = _columns(Override, skip=("id",))

    def _ovr_item(self, ov) -> dict:
        item = to_item(ov, self._OVR_COLS)
        item.update(pk=f"CASE#{ov.case_id}", sk=f"OVR#{_num(ov.id, 10)}", oid=ov.id)
        return item

    def _ovr_from(self, item: dict) -> Override:
        return from_item(Override, item, cols=self._OVR_COLS, id=int(item["oid"]))

    def add_override(self, ov):
        ov.id = self._counter("override")
        self._put(self._ovr_item(ov))
        return ov

    def get_override(self, case_id, override_id):
        r = self.table.get_item(Key={"pk": f"CASE#{case_id}", "sk": f"OVR#{_num(override_id, 10)}"}, ConsistentRead=True).get("Item")
        return self._ovr_from(r) if r else None

    def list_overrides(self, case_id):
        return [self._ovr_from(i) for i in self._query(f"CASE#{case_id}", sk_prefix="OVR#", consistent=True)]

    def save_override(self, ov):
        self._put(self._ovr_item(ov))

    def pending_override(self, case_id):
        return next((o for o in self.list_overrides(case_id) if o.status == "PENDING_APPROVAL"), None)

    def case_ids_with_override_status(self, status):
        out: set[str] = set()
        kw: dict[str, Any] = {"FilterExpression": Attr("sk").begins_with("OVR#") & Attr("status").eq(status),
                              "ProjectionExpression": "case_id"}
        while True:
            r = self.table.scan(**kw)
            out |= {i["case_id"] for i in r["Items"]}
            if "LastEvaluatedKey" not in r:
                return out
            kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]

    # ── audit chain ──────────────────────────────────────────────────────────────────────────────────
    _AUD_COLS = _columns(AuditEvent, skip=("seq",))

    def _aud_from(self, item: dict) -> AuditEvent:
        return from_item(AuditEvent, item, cols=self._AUD_COLS, seq=int(item["seq"]))

    def append_audit(self, actor, action, case_id, detail):
        from medishield.db import audit as chain

        for _ in range(50):                                     # a concurrent writer took our slot: re-read the head, re-link
            head = self._query("AUDIT", reverse=True, limit=1, consistent=True)
            seq = int(head[0]["seq"]) + 1 if head else 1
            prev = head[0]["hash"] if head else chain.GENESIS
            ts = utcnow().isoformat(timespec="microseconds")
            ev = AuditEvent(seq=seq, ts=ts, actor=actor, action=action, case_id=case_id, detail=detail, prev_hash=prev,
                            hash=chain.chain_hash(prev, chain.canonical(ts, actor, action, case_id, detail)))
            item = {**to_item(ev, self._AUD_COLS), "pk": "AUDIT", "sk": _num(seq, 12), "seq": seq}
            if case_id:
                item.update(gsi1pk=f"CASE#{case_id}", gsi1sk=f"AUDIT#{_num(seq, 12)}")
            try:
                self._put(item, ConditionExpression=Attr("pk").not_exists())
                return ev
            except ClientError as e:
                if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
                    raise
        raise RuntimeError("audit append kept losing the race")

    def list_audit(self, *, case_id, action, limit, offset):
        if case_id:
            rows = self._query(f"CASE#{case_id}", sk_prefix="AUDIT#", index="gsi1", reverse=True)
        else:
            rows = self._query("AUDIT", reverse=True)
        out = [self._aud_from(i) for i in rows if not action or i.get("action") == action]
        return out[offset: offset + limit]

    def audit_for_case(self, case_id):
        return [self._aud_from(i) for i in self._query(f"CASE#{case_id}", sk_prefix="AUDIT#", index="gsi1")]

    def iter_audit(self):
        return (self._aud_from(i) for i in self._query("AUDIT", consistent=True))

    # ── policies ─────────────────────────────────────────────────────────────────────────────────────
    _POL_COLS = _columns(PolicyDoc, skip=("id",))

    def _pol_item(self, p) -> dict:
        item = to_item(p, self._POL_COLS)
        item.update(pk="POLICY", sk=_num(p.id, 10), pid=p.id)
        return item

    def _pol_from(self, item: dict) -> PolicyDoc:
        return from_item(PolicyDoc, item, cols=self._POL_COLS, id=int(item["pid"]))

    def add_policy(self, plan, filename, sha256, uploaded_by):
        p = PolicyDoc(plan=plan, filename=filename[:255], sha256=sha256, uploaded_by=uploaded_by, status="INGESTING")
        p.id = self._counter("policy")
        self._put(self._pol_item(p))
        return p

    def get_policy(self, policy_id):
        r = self.table.get_item(Key={"pk": "POLICY", "sk": _num(policy_id, 10)}, ConsistentRead=True).get("Item")
        return self._pol_from(r) if r else None

    def list_policies(self):
        return [self._pol_from(i) for i in self._query("POLICY", reverse=True)]

    def ready_policies(self):
        return [p for p in (self._pol_from(i) for i in self._query("POLICY")) if p.status == "READY"]

    def save_policy(self, p):
        self._put(self._pol_item(p))


_repo: DynamoRepo | None = None
_repo_lock = threading.Lock()


def get_dynamo_repo() -> DynamoRepo:
    global _repo
    from medishield.config import get_settings

    s = get_settings()
    with _repo_lock:
        if _repo is None or (_repo.table_name, _repo.region, _repo.endpoint_url) != (s.dynamo_table, s.aws_region, s.dynamo_endpoint_url):
            _repo = DynamoRepo(s.dynamo_table, s.aws_region, s.dynamo_endpoint_url)
        return _repo


def reset_dynamo_repo() -> None:
    global _repo
    _repo = None
