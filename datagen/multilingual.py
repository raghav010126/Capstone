"""Spanish and Hindi variants of MediShield documents, with ground truth, for the multi-language bonus.

The instructors' generator only produces English. This renders prescriptions and identity cards for existing dataset
members in Spanish and Hindi (Devanagari script), using the same member data so KYC and policy lookups still resolve.
Realistic wrinkles are kept on purpose: dates are printed day/month/year (not US month/day/year), Spanish names and labels
carry accents, and Hindi labels are in Devanagari while names, codes and drug names stay in Latin script, as on real forms.

Layout mirrors the official dataset (``dataset/metadata.json`` + ``ground_truth/{labels,fields,render,clusters}.json`` +
``records/``), so ``eval/run_eval.py --dataset data/multilingual --split all`` works unchanged.

Usage: python datagen/multilingual.py data/official data/multilingual   (then run_eval --split dev / heldout)
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import resolve_font

LABELS = {
    "es": {"rx_title": "RECETA MÉDICA", "id_title": "DOCUMENTO DE IDENTIDAD", "patient": "Paciente", "dob": "Fecha de nacimiento",
           "policy": "Número de póliza", "date": "Fecha", "doctor": "Médico", "npi": "NPI", "dea": "DEA", "meds": "Medicamentos",
           "refills": "Repeticiones", "signature": "Firma del médico", "name": "Nombre completo", "valid": "Válido hasta",
           "country": "ESTADOS UNIDOS", "insurer": "Seguro de salud MediShield",
           "claim_title": "FORMULARIO DE RECLAMACIÓN DE SEGURO MÉDICO", "claim_no": "Número de reclamo", "dos": "Fecha de servicio",
           "dx": "Diagnósticos (CIE-10)", "px": "Procedimientos (CPT)", "charge": "Cargo", "total": "Cargo total",
           "billing": "Proveedor de facturación", "attending": "Médico tratante", "missing": "[FALTA]", "expired": "VENCIDO",
           "dc_title": "RESUMEN DE ALTA HOSPITALARIA", "admit": "Fecha de ingreso", "discharge": "Fecha de alta",
           "primary_dx": "Diagnóstico principal", "facility": "Centro"},
    "hi": {"rx_title": "चिकित्सा पर्ची (प्रिस्क्रिप्शन)", "id_title": "पहचान पत्र", "patient": "रोगी का नाम", "dob": "जन्म तिथि",
           "policy": "पॉलिसी संख्या", "date": "दिनांक", "doctor": "चिकित्सक", "npi": "एनपीआई", "dea": "डीईए", "meds": "दवाइयाँ",
           "refills": "पुनः भराई", "signature": "चिकित्सक के हस्ताक्षर", "name": "पूरा नाम", "valid": "वैध तिथि तक",
           "country": "संयुक्त राज्य अमेरिका", "insurer": "मेडीशील्ड स्वास्थ्य बीमा",
           "claim_title": "स्वास्थ्य बीमा दावा प्रपत्र", "claim_no": "दावा संख्या", "dos": "सेवा की तिथि",
           "dx": "निदान (ICD-10)", "px": "प्रक्रियाएँ (CPT)", "charge": "शुल्क", "total": "कुल शुल्क",
           "billing": "बिलिंग प्रदाता", "attending": "उपस्थित चिकित्सक", "missing": "[अनुपलब्ध]", "expired": "समाप्त",
           "dc_title": "अस्पताल से छुट्टी का सारांश", "admit": "भर्ती की तिथि", "discharge": "छुट्टी की तिथि",
           "primary_dx": "मुख्य निदान", "facility": "अस्पताल"},
}
SIG = {
    "es": [("Take", "Tomar"), ("tablet", "tableta"), ("three times daily", "tres veces al día"), ("twice daily", "dos veces al día"),
           ("once daily", "una vez al día"), ("with food", "con alimentos"), ("in the evening", "por la noche"),
           ("as needed", "según necesidad")],
    "hi": [("Take", "लें"), ("tablet", "गोली"), ("three times daily", "दिन में तीन बार"), ("twice daily", "दिन में दो बार"),
           ("once daily", "दिन में एक बार"), ("with food", "भोजन के साथ"), ("in the evening", "शाम को"), ("as needed", "ज़रूरत पड़ने पर")],
}


FONT_CACHE = Path.home() / ".cache" / "medishield" / "fonts"
SCALE = 1.5                                             # PDF points -> pixels when rasterising


def _ttf(src: str, index: int, name: str) -> str:
    """fpdf2 reads .ttf only: extract one face of a macOS .ttc once."""
    from fontTools.ttLib import TTCollection

    FONT_CACHE.mkdir(parents=True, exist_ok=True)
    out = FONT_CACHE / f"{name}.ttf"
    if not out.exists():
        TTCollection(src).fonts[index].save(str(out))
    return str(out)


def _fonts() -> dict[str, str]:
    return {"latin": resolve_font("arial.ttf") or "", "latin_b": resolve_font("arialbd.ttf") or "",
            "deva": _ttf("/System/Library/Fonts/Kohinoor.ttc", 0, "kohinoor-regular"),
            "deva_b": _ttf("/System/Library/Fonts/Kohinoor.ttc", 3, "kohinoor-bold")}


def translate_sig(sig: str, lang: str) -> str:
    for en, tr in SIG[lang]:
        sig = sig.replace(en, tr)
    return sig


def dmy(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def mdy(d: date) -> str:
    return d.strftime("%m/%d/%Y")


class Page:
    """A page drawn with fpdf2 (HarfBuzz text shaping, so Devanagari conjuncts and vowel signs are laid out correctly) and
    rasterised with pdfium. Every string drawn is recorded with its pixel box: the ground truth for the evaluation."""

    def __init__(self, w: int, h: int, lang: str):
        from fpdf import FPDF

        self.w, self.h, self.lang, self.texts = w, h, lang, []
        self.pdf = FPDF(unit="pt", format=(w, h))
        self.pdf.set_auto_page_break(False)
        self.pdf.add_page()
        self.pdf.set_text_shaping(True)
        for key, path in _fonts().items():
            self.pdf.add_font(key, fname=path)
        self.rect(0, 0, w, h, (252, 252, 250))

    def rect(self, x, y, w, h, fill):
        self.pdf.set_fill_color(*fill)
        self.pdf.rect(x, y, w, h, style="F")

    def line(self, x0, y0, x1, y1, colour=(80, 80, 80)):
        self.pdf.set_draw_color(*colour)
        self.pdf.line(x0, y0, x1, y1)

    def text(self, xy, s, size=20, bold=False, fill=(20, 20, 20)):
        deva = any(0x900 <= ord(c) <= 0x97F for c in s)
        self.pdf.set_font(("deva" if deva else "latin") + ("_b" if bold else ""), size=size)
        self.pdf.set_text_color(*fill)
        x, y = xy
        width = self.pdf.get_string_width(s)
        self.pdf.set_xy(x, y)
        self.pdf.cell(width + 2, size * 1.35, s)
        self.texts.append({"text": s, "bbox": [x * SCALE, y * SCALE, (x + width) * SCALE, (y + size * 1.2) * SCALE],
                           "font_size": size, "fill": list(fill)})
        return y + size * 1.35

    @property
    def img(self) -> Image.Image:
        import pypdfium2 as pdfium

        doc = pdfium.PdfDocument(bytes(self.pdf.output()))
        return doc[0].render(scale=SCALE).to_pil().convert("RGB")


def render_rx(c: dict, lang: str, rx_date: date, missing_dea: bool = False):
    L = LABELS[lang]
    p = Page(850, 1150, lang)
    p.rect(40, 30, 770, 90, (30, 60, 110))
    p.text((60, 45), c["hospital"], 30, True, (255, 255, 255))
    p.text((60, 88), L["insurer"], 18, False, (210, 225, 255))
    p.text((60, 150), L["rx_title"], 34, True, (30, 60, 110))
    y = 220
    for key, val in ((L["patient"], c["name"]), (L["dob"], dmy(_dob(c))), (L["policy"], c["policy"]), (L["date"], dmy(rx_date))):
        p.text((60, y), f"{key}:", 20, True, (60, 60, 80))
        p.text((330, y), val, 22)
        y += 52
    p.text((60, y + 10), f"{L['doctor']}:", 20, True, (60, 60, 80))
    p.text((330, y + 10), c["doctor"], 22)
    p.text((60, y + 62), f"{L['npi']}:", 20, True, (60, 60, 80))
    p.text((330, y + 62), c["npi"], 22)
    dea = f"B{c['doctor'].split()[1][0].upper()}{c['npi'].replace('NPI-', '')[:7]}"
    p.text((60, y + 114), f"{L['dea']}:", 20, True, (60, 60, 80))
    p.text((330, y + 114), L["missing"] if missing_dea else dea, 22, fill=(190, 30, 30) if missing_dea else (20, 20, 20))
    y += 190
    p.text((60, y), f"{L['meds']}:", 24, True, (30, 60, 110))
    y += 50
    drugs = []
    for i, rx in enumerate(c["rx_list"][:3], 1):
        name, brand, sig = rx[0], rx[1], rx[2]
        p.text((60, y), f"{i}. {name} ({brand})", 24, True)
        p.text((90, y + 36), translate_sig(sig, lang), 20)
        drugs.append(name)
        y += 100
    p.text((60, y + 10), f"{L['refills']}: 2", 20)
    p.text((60, y + 90), L["signature"], 18, False, (90, 90, 90))
    p.line(60, y + 84, 330, y + 84)
    return p, dea, drugs


def render_id(c: dict, lang: str, expiry: date, expired: bool = False) -> Page:
    L = LABELS[lang]
    p = Page(860, 540, lang)
    p.rect(0, 0, 860, 92, (20, 80, 60))
    p.text((24, 14), L["country"], 16, False, (200, 235, 220))
    p.text((24, 38), L["id_title"], 32, True, (255, 255, 255))
    p.rect(40, 120, 180, 210, (205, 212, 225))
    y = 125
    for key, val in ((L["name"], c["name"].upper()), (L["dob"], dmy(_dob(c))), (L["valid"], dmy(expiry)), (L["policy"], c["policy"])):
        p.text((250, y), f"{key}:", 16, True, (40, 70, 60))
        p.text((250, y + 24), val, 22 if key == L["name"] else 20)
        y += 78
    if expired:
        p.text((560, 400), f"** {L['expired']} **", 30, True, (200, 0, 0))
    return p


def render_claim(c: dict, lang: str, dos: date, claim_no: str, lines: list[tuple[str, float]], icds: list[str]):
    L = LABELS[lang]
    p = Page(850, 1150, lang)
    p.rect(40, 30, 770, 90, (110, 30, 40))
    p.text((60, 45), L["claim_title"], 26, True, (255, 255, 255))
    p.text((60, 88), L["insurer"], 18, False, (240, 215, 220))
    y = 160
    for key, val in ((L["patient"], c["name"]), (L["dob"], dmy(_dob(c))), (L["policy"], c["policy"]), (L["claim_no"], claim_no),
                     (L["dos"], dmy(dos))):
        p.text((60, y), f"{key}:", 20, True, (60, 60, 80))
        p.text((360, y), val, 22)
        y += 50
    p.text((60, y + 10), f"{L['dx']}:", 20, True, (60, 60, 80))
    p.text((360, y + 10), ", ".join(icds), 22)
    y += 80
    p.text((60, y), f"{L['px']}:", 22, True, (110, 30, 40))
    y += 46
    for cpt, charge in lines:
        p.text((80, y), cpt, 22)
        p.text((300, y), f"{L['charge']}: ${charge:,.2f}", 22)
        y += 44
    p.line(60, y + 8, 780, y + 8)
    total = sum(ch for _c, ch in lines)
    p.text((300, y + 24), f"{L['total']}: ${total:,.2f}", 26, True)
    y += 100
    for key, val in ((L["billing"], c["hospital"]), (L["attending"], c["doctor"]), (L["npi"], c["npi"])):
        p.text((60, y), f"{key}:", 20, True, (60, 60, 80))
        p.text((360, y), val, 22)
        y += 50
    return p, total


def render_discharge(c: dict, lang: str, admit: date, discharge: date):
    L = LABELS[lang]
    p = Page(850, 900, lang)
    p.rect(40, 30, 770, 90, (30, 90, 90))
    p.text((60, 45), c["hospital"], 28, True, (255, 255, 255))
    p.text((60, 84), L["dc_title"], 20, False, (215, 240, 240))
    y = 160
    for key, val in ((L["patient"], c["name"]), (L["dob"], dmy(_dob(c))), (L["policy"], c["policy"]), (L["admit"], dmy(admit)),
                     (L["discharge"], dmy(discharge)), (L["primary_dx"], f"{c['icd_code']}"), (L["attending"], c["doctor"]),
                     (L["facility"], c["hospital"])):
        p.text((60, y), f"{key}:", 20, True, (60, 60, 80))
        p.text((360, y), val, 22)
        y += 56
    return p


def _dob(c: dict) -> date:
    m, d, y = (int(x) for x in c["dob"].split("/"))
    return date(y, m, d)


LANG_OFFSET_DAYS = {"es": 0, "hi": 23}


def build(src: Path, dst: Path, per_split: int = 4) -> dict:
    """Valid four-document bundles for ``per_split`` clean members of the dev split and of the held-out split, plus three
    failure cases per language and split: an expired ID, a prescription with no DEA number, and a claim for an excluded
    procedure. Prompts are tuned on the dev members; the held-out members are reported, never tuned on."""
    from records import official_pools

    if dst.exists():
        shutil.rmtree(dst)
    for sub in ("prescriptions", "id_documents", "claim_forms", "discharge_summaries"):
        (dst / "dataset" / sub).mkdir(parents=True)
    (dst / "ground_truth").mkdir()
    shutil.copytree(src / "records", dst / "records")
    shutil.copytree(src / "dataset" / "policies", dst / "dataset" / "policies")
    all_labels = json.loads((src / "ground_truth" / "labels.json").read_text())
    clusters = {c["cluster_id"]: c for c in json.loads((src / "ground_truth" / "clusters.json").read_text())["clusters"]}
    uncovered = official_pools()["UNCOVERED_CPT"]
    excluded_codes = {code for code, _d, _p in uncovered} | {"59400"}            # excluded procedures and the obstetric code
    # only a member's name, dates and (covered) procedure codes are reused, so the official fraud / ID flags do not matter here

    def clean(cid: str) -> bool:
        return not ({code for code, _d, _p in clusters[cid]["cpt_list"]} & excluded_codes)

    members = {"dev": [c for c in all_labels["splits"]["dev_clusters"] if clean(c)][:per_split],
               "heldout": [c for c in all_labels["splits"]["heldout_clusters"] if clean(c)][:per_split]}
    meta, labels, fields, render, cases, splits = [], {}, {}, {}, {}, {"dev": [], "heldout": []}
    counter = [90000]

    def emit(page, kind, folder, doc_id, case, c, lang, expected="APPROVE", reasons=()):
        image = page.img
        rel = f"{folder}/{doc_id}.png"
        image.save(dst / "dataset" / rel)
        meta.append({"doc_id": doc_id, "category": kind, "case_cluster_id": case, "fraud_label": False, "fraud_reason": None,
                     "edge_flags": list(reasons), "patient_id": c["patient_id"], "policy_number": c["policy"], "blur_simulated": False,
                     "file_path": rel, "language": lang})
        labels[doc_id] = {"case_id": case, "category": kind, "expected_decision": expected, "reasons": list(reasons), "visible": True,
                          "visibility_note": f"{lang} document"}
        render[doc_id] = {"category": kind, "file_path": rel, "width": image.width, "height": image.height,
                          "render": {"scan_effect": False, "rotation_deg": None, "blur_radius": None}, "texts": page.texts}

    def claim_fields(c, claim_no, dos, lines, icds, total):
        return {"form_type": "OTHER", "patient_name": c["name"], "patient_dob": mdy(_dob(c)), "policy_number": c["policy"],
                "claim_number": claim_no, "service_date": dos.isoformat(), "icd_codes": icds, "cpt_codes": [x for x, _ in lines],
                "line_charges": [ch for _, ch in lines], "total_charge": total, "provider_npi": c["npi"],
                "billing_provider": c["hospital"], "attending_physician": c["doctor"]}

    def covered_claim(c):
        lines = [(code, float(price)) for code, _d, price in c["cpt_list"]][:3]
        return lines, [c["icd_code"], c["secondary_icd_code"]][:2]

    for lang in ("es", "hi"):
        for split, cids in members.items():
            for n, cid in enumerate(cids):
                c = clusters[cid]
                # the Hindi bundle of a member is a different encounter from the Spanish one (a later date of service), so the two
                # are not the same claim twice - the duplicate-claim detector would rightly flag identical ones
                pid, dos = c["patient_id"], date.fromisoformat(c["treatment_date"]) + timedelta(days=LANG_OFFSET_DAYS[lang])
                case = f"{cid}_{lang}"
                splits[split].append(case)
                cases[case] = "APPROVE"
                counter[0] += 1
                claim_no = f"CLM-2024-{counter[0]:05d}"
                lines, icds = covered_claim(c)
                cp, total = render_claim(c, lang, dos, claim_no, lines, icds)
                emit(cp, "claim_forms", "claim_forms", f"claim_{pid}_{lang}", case, c, lang)
                fields[f"claim_{pid}_{lang}"] = claim_fields(c, claim_no, dos, lines, icds, total)
                rx_date, expiry = dos + timedelta(days=2), dos + timedelta(days=730)
                rp, dea, drugs = render_rx(c, lang, rx_date)
                emit(rp, "prescriptions", "prescriptions", f"rx_{pid}_{lang}", case, c, lang)
                fields[f"rx_{pid}_{lang}"] = {"patient_name": c["name"], "patient_dob": mdy(_dob(c)), "rx_date": rx_date.isoformat(),
                                              "prescriber": c["doctor"], "prescriber_npi": c["npi"], "dea_number": dea, "drugs": drugs,
                                              "missing_field": None}
                emit(render_id(c, lang, expiry), "id_documents", "id_documents", f"id_{pid}_{lang}", case, c, lang)
                fields[f"id_{pid}_{lang}"] = {"id_type": "other", "name_on_id": c["name"], "dob": mdy(_dob(c)), "expiry_date": expiry.isoformat(),
                                              "policy_number": c["policy"], "reference_date": dos.isoformat()}
                disch = dos + timedelta(days=3)
                emit(render_discharge(c, lang, dos, disch), "discharge_summaries", "discharge_summaries", f"dc_{pid}_{lang}", case, c, lang)
                fields[f"dc_{pid}_{lang}"] = {"patient_name": c["name"], "patient_dob": mdy(_dob(c)), "admit_date": dos.isoformat(),
                                              "discharge_date": disch.isoformat(), "primary_icd": c["icd_code"],
                                              "attending_physician": c["doctor"], "facility": c["hospital"]}
                if n:
                    continue
                # failure cases (first member of each split): a different date of service so nothing looks like a duplicate
                dos2 = dos + timedelta(days=9)
                short = lines[:2]                              # fewer lines: not a near-copy of the member's main claim page
                counter[0] += 1
                no2 = f"CLM-2024-{counter[0]:05d}"
                # 1. expired ID (needs its claim in the case: the date of service is what the ID is judged against)
                case = f"{cid}_{lang}_expiredid"
                splits[split].append(case)
                cp2, total2 = render_claim(c, lang, dos2, no2, short, icds)
                emit(cp2, "claim_forms", "claim_forms", f"claim_{pid}_{lang}_expiredid", case, c, lang)
                fields[f"claim_{pid}_{lang}_expiredid"] = claim_fields(c, no2, dos2, short, icds, total2)
                exp2 = dos2 - timedelta(days=60)
                emit(render_id(c, lang, exp2, expired=True), "id_documents", "id_documents", f"id_{pid}_{lang}_expiredid", case, c, lang,
                     "REJECT", ["expired_id"])
                fields[f"id_{pid}_{lang}_expiredid"] = {"id_type": "other", "name_on_id": c["name"], "dob": mdy(_dob(c)),
                                                        "expiry_date": exp2.isoformat(), "policy_number": c["policy"],
                                                        "reference_date": dos2.isoformat()}
                cases[case] = "REJECT"
                # 2. prescription with no DEA number
                case = f"{cid}_{lang}_nodea"
                splits[split].append(case)
                rp2, _dea, drugs2 = render_rx(c, lang, dos2 + timedelta(days=2), missing_dea=True)
                emit(rp2, "prescriptions", "prescriptions", f"rx_{pid}_{lang}_nodea", case, c, lang, "REJECT", ["missing_fields"])
                fields[f"rx_{pid}_{lang}_nodea"] = {"patient_name": c["name"], "patient_dob": mdy(_dob(c)),
                                                    "rx_date": (dos2 + timedelta(days=2)).isoformat(), "prescriber": c["doctor"],
                                                    "prescriber_npi": c["npi"], "dea_number": None, "drugs": drugs2, "missing_field": "dea"}
                cases[case] = "REJECT"
                # 3. claim for an excluded procedure
                case = f"{cid}_{lang}_uncovered"
                splits[split].append(case)
                counter[0] += 1
                no3 = f"CLM-2024-{counter[0]:05d}"
                code, _desc, price = uncovered[n % len(uncovered)]
                ulines = [(code, float(price))]
                cp3, total3 = render_claim(c, lang, dos2 + timedelta(days=1), no3, ulines, icds)
                emit(cp3, "claim_forms", "claim_forms", f"claim_{pid}_{lang}_uncovered", case, c, lang, "REJECT", ["uncovered_procedure"])
                fields[f"claim_{pid}_{lang}_uncovered"] = claim_fields(c, no3, dos2 + timedelta(days=1), ulines, icds, total3)
                cases[case] = "REJECT"
    (dst / "dataset" / "metadata.json").write_text(json.dumps(meta, indent=2))
    (dst / "ground_truth" / "labels.json").write_text(json.dumps({"rules": {}, "documents": labels, "cases": cases, "splits": {
        "dev_clusters": splits["dev"], "heldout_clusters": splits["heldout"], "dev_unknown": [], "heldout_unknown": []}}, indent=2))
    (dst / "ground_truth" / "fields.json").write_text(json.dumps(fields, indent=2))
    (dst / "ground_truth" / "render.json").write_text(json.dumps(render))
    (dst / "ground_truth" / "clusters.json").write_text(json.dumps({"clusters": [clusters[m] for ms in members.values() for m in ms]}))
    return {"documents": len(meta), "cases": len(cases), "languages": ["es", "hi"], "members": members}


if __name__ == "__main__":
    print(build(Path(sys.argv[1] if len(sys.argv) > 1 else "data/official"), Path(sys.argv[2] if len(sys.argv) > 2 else "data/multilingual")))
