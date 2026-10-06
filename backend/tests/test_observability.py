"""Nothing identifying may leave the process through traces."""

from medishield import observability as obs


def test_images_ocr_and_identity_fields_are_removed():
    payload = {
        "system": "You are the extraction agent.",
        "messages": [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "iVBORw0KGgo" * 500}},
                     "OCR text:\n<ocr>\nChristopher Harris I.\n04/25/1954\nMED-GLD-6770619\n</ocr>\nExtract the fields."],
        "values": {"patient_name": "Christopher Harris I.", "patient_dob": "04/25/1954", "policy_number": "MED-GLD-6770619",
                   "total_charge": 4095.0, "icd_codes": ["I25.10"], "claim_number": "CLM-2024-00001"},
        "raw_text": "lots of OCR text with Christopher Harris I.",
        "bounding_boxes": [{"text": "Christopher", "box": [1, 2, 3, 4]}],
    }
    out = str(obs.scrub(payload))
    for leaked in ("Christopher", "1954", "6770619", "iVBORw0K", "CLM-2024-00001", "OCR text with"):
        assert leaked not in out, leaked
    assert "4095.0" in out and "I25.10" in out and "You are the extraction agent." in out     # useful, non-identifying content stays
    assert "[image omitted]" in out and "OCR text omitted" in out


def test_tokens_and_free_text_pii_are_redacted():
    out = obs.scrub({"note": "member Jessica Jackson Y. ssn 123-45-6789 called, Bearer abc.def.ghi", "n": 3})
    assert "Jessica" not in out["note"] and "123-45-6789" not in out["note"] and "abc.def" not in out["note"]
    assert out["n"] == 3


def test_tracing_is_off_without_a_key(monkeypatch):
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    obs._client.cache_clear()
    assert not obs.enabled() and obs.graph_config("CASE-1") == {}
    with obs.llm_span("classifier", "claude-sonnet-5-5", "low", {"x": 1}) as finish:
        finish({"y": 2})                                           # a no-op, must not raise
    obs._client.cache_clear()


def test_tracing_can_be_switched_off_even_with_a_key(monkeypatch):
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_pt_fake")
    monkeypatch.setenv("MEDISHIELD_TRACING", "0")
    obs._client.cache_clear()
    assert not obs.enabled()
    obs._client.cache_clear()


def test_identity_fields_inside_embedded_json_text_are_masked():
    prompt = ('Case documents:\n[{"doc_id": "claim_PT_99733", "patient_name": "Jessica Jackson Y.", "attending_physician": '
              '"Dr. David Nguyen, MD", "total_charge": 16825.0, "icd_codes": ["S52.501A"]}]\nPrescribed by Dr. Mark Owen, MD.')
    out = obs.scrub(prompt)
    for leaked in ("Jessica", "Nguyen", "Mark Owen"):
        assert leaked not in out, leaked
    assert "16825.0" in out and "S52.501A" in out and "claim_PT_99733" in out


def test_extracted_field_records_are_masked_by_field_name():
    out = obs.scrub({"fields": [{"name": "claim_number", "value": "CLM-2024-00002", "grounded": True},
                                {"name": "total_charge", "value": 16825.0, "grounded": True},
                                {"name": "service_lines[0].cpt", "value": "80053", "grounded": True}]})
    assert out["fields"][0]["value"] == "[REDACTED]" and out["fields"][0]["grounded"] is True
    assert out["fields"][1]["value"] == 16825.0 and out["fields"][2]["value"] == "80053"
    assert "CLM-2024" not in obs.scrub("duplicate of RX-CLM-2024-00001 and CLM-2024-00002")
