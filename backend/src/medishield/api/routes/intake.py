"""Email intake over HTTP: ``POST /intake/email`` takes one raw ``.eml`` message (for demos, and for any mail gateway that
can forward a message to an authenticated endpoint). The SES inbound path is ``medishield.intake.ses``."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from medishield.api import schemas as S
from medishield.api.deps import get_db
from medishield.api.routes.cases import _admit
from medishield.api.security import Principal, Role, client_key, require
from medishield.api.uploads import UploadError
from medishield.db.repo import Repo
from medishield.intake import service
from medishield.intake.email import parse
from medishield.intake.settings import intake_settings
from medishield.services.cases import should_enqueue
from medishield.worker.queue import enqueue_case

router = APIRouter(tags=["intake"])

_BODY = {"requestBody": {"required": True, "content": {
    "message/rfc822": {"schema": {"type": "string", "format": "binary"}},
    "multipart/form-data": {"schema": {"type": "object", "required": ["file"],
                                       "properties": {"file": {"type": "string", "format": "binary"}}}}}}}


async def _read_message(request: Request, cap: int) -> bytes:
    """A multipart field ``file`` or the raw request body; never buffers more than ``cap`` + 1 bytes of the message."""
    if request.headers.get("content-type", "").startswith("multipart/form-data"):
        form = await request.form(max_files=1, max_fields=4)
        f = form.get("file")
        if f is None or isinstance(f, str):
            raise HTTPException(422, "send the message as a file field named 'file'")
        return await f.read(cap + 1)
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > cap:
            break
    return bytes(data)


@router.post("/intake/email", response_model=S.CaseCreated, status_code=202, openapi_extra=_BODY)
async def email_intake(request: Request, response: Response, user: Principal = Depends(require("case:create")),
                       db: Repo = Depends(get_db)):
    """Create a case from the PDF/PNG/JPEG/TIFF attachments of one email, owned by the caller. The From address must be
    on the intake allow-list (``INTAKE_SENDERS``), and a submitter may only send mail from an address mapped to them.
    Idempotent on the Message-ID: the same message again returns the first case (200)."""
    _admit(user)
    raw = await _read_message(request, intake_settings().max_email_bytes)
    domain = ""
    try:
        parsed = parse(raw)
        domain = parsed.sender_domain
        mapped = service.resolve_sender(db, parsed.sender)
        if user.role == Role.SUBMITTER and mapped.username != user.username:
            raise UploadError("this sender is mapped to another user", 403)
        case, warnings, created = service.submit(db, user, parsed, "api")
    except UploadError as e:
        service.reject(db, user.username, "api", domain, str(e), ip=client_key(request))
        db.commit()
        # submitters get one generic answer, so they can't probe which addresses are allow-listed or mapped to whom
        detail = "this sender may not submit cases by email" if e.status == 403 and user.role == Role.SUBMITTER else str(e)
        raise HTTPException(e.status, detail) from e
    db.commit()
    if should_enqueue(case, created):
        enqueue_case(case.id)
    if not created:
        response.status_code = 200
    return S.CaseCreated(case_id=case.id, status=case.status, documents=[d.doc_id for d in case.documents],
                         warnings=warnings, idempotent_replay=not created)
