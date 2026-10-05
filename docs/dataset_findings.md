# Dataset findings: the official MediShield generator

> **Status:** draft (checkpoint 1). Every claim below is either cited to a line in `datagen/official/` or
> verified programmatically by `datagen/harness.py` and `eval/truth.py`, which store their evidence in
> `data/official/ground_truth/`.

The instructors supplied four generator scripts. We run them **byte-for-byte unmodified** inside a recording
harness and generate the dataset from them: 155 documents, 2 policy PDFs and `metadata.json`.

While building ground truth we found several places where the labels, the overview and the rendered pixels
disagree. A grader scoring against `metadata.json` would hit these too, so we document each one, along with what
our system does about it.

## How the dataset is reproduced
- `make dataset` runs `datagen/harness.py --seed 42`.
- Content is identical to the instructors' seed: patient IDs `PT_19116 … PT_39451` for clusters C_001–C_006.
- Output is **pixel-deterministic**. Two runs produced byte-identical SHA-256 hashes for all 155 PNGs and for
  `metadata.json`. This works because the harness seeds the global `random`/`numpy` RNGs that the scan effect uses.
- Harness outputs:
  - `ground_truth/render.json`: every string drawn on every image. Each record has the text, font size and colour,
    plus its box in final pixel coordinates. Boxes are tracked through paste, crop and the scan-effect rotation.
  - `ground_truth/clusters.json`: the generator's internal patient-cluster data.

## Findings

| # | Finding | Evidence | Impact | What we do |
|---|---|---|---|---|
| F1 | `expected_decision` exists only for the 4 unknown docs. The overview says every entry has one. | Only writer: `generate_unknown.py:330` | 151 docs have no decision label | `eval/truth.py` derives decisions with explicit precedence rules (below) |
| F2 | **Tampered IDs are never drawn.** The tamper code exists but is never called. | `generate_docs.py:796-797`: `generate_id_document` passes only `expired`, `blur`. Programmatic check: no tamper-ink glyphs on the 3 flagged IDs. | `id_PT_57795`, `id_PT_62383`, `id_PT_74454` look normal | Labels kept, marked *not visible*. The corrected dataset renders real tampering (JPEG paste) for ELA. |
| F3 | **The name-mismatch fraud is never drawn.** `id_display_name` is computed but never rendered. | `generate_docs.py:428` computes it, `:796` drops it. The ID shows the true name. | `id_PT_39451` is labelled fraud but undetectable | Same as F2 |
| F4 | **Structuring fraud is missing in this seed.** It is injected only by the CMS-1500 renderer, but its cluster (C_004) gets a UB-04 form. | `:1035-1043` (CMS only); `:425` (`i % 3 == 0` gives UB-04) | `claim_PT_69470` shows a normal $23,290 total | Same as F2 |
| F5 | **Only 1 of 3 "blurry" prescriptions is blurred.** Blur is applied only inside the 40% random scan-effect branch. | `:472-474`; harness `render.blur_radius` | `rx_PT_88139` is flagged but sharp. (`rx_PT_45400` is also hard-REJECT for a missing field.) | Marked *not visible*; the corrected dataset applies blur deterministically |
| F6 | Every member is on the **Gold** plan | `:375` `MED-GLD-…` | The Silver PDF is a retrieval distractor | The policy agent filters by plan prefix |
| F7 | **No individual CPT code appears in either policy PDF.** Only the 18 rows of table "4.1 Excluded CPT Code Ranges" contain codes. All 5 "uncovered" CPTs fall in those ranges. | Docling spike: 18 range rows per plan | Embedding search on a code fails | The exclusion table is parsed into structured ranges (exact containment) plus semantic search on descriptions |
| F8 | Table 4.1 is **split across pages**, and the second fragment has no header row | Docling: Gold 1+17 rows, Silver 2+16 rows | Naive table parsing loses rows | Fragments are stitched when column counts match |
| F9 | Table 4.1 problems: overlapping ranges (15000-15999 ⊃ 15820-15829); 2 rows that are not exclusions (97010-97799 is "Prior Auth Req", 99241-99245 is "Specialist copay only"); section references that point to the wrong bullets | `generate_gold_policy.py:448-467` | A naive "row = excluded" rule is wrong | Each row is classified as exclusion, prior-auth or copay |
| F10 | ICD and CPT codes are **paired randomly**, e.g. sinusitis with CABG | `:384-385` (independent draws) | A generic medical-necessity check would flag ~every claim | Only hard coding edits are enforced (obstetric CPT 59400 needs a pregnancy ICD) |
| F11 | ID expiry is defined **relative to the date of service**, not today | `_exp_dates`, `:496-502` | Checking against Oct 2026 marks all 5 "expiring-soon" IDs as expired | KYC compares expiry with the claim's date of service |
| F12 | **No member database or claim history** is emitted | `:2344-2350` writes only `metadata.json` and the summary | KYC and fraud baselines have no system of record | `datagen/records.py` builds `members.json` (300) and `claims_history.json` (2,000; all dated 2023-24, before every 2025 DOS) |
| F13 | Fonts are Windows-only (`arial.ttf`, `C:\Windows\Fonts\segoesc.ttf`). On macOS/Linux, text silently falls back to Pillow's tiny bitmap font. | `:9-35` | Unreadable documents if run naively | The harness maps fonts to macOS/Linux equivalents |
| F14 | All images are PNG | `:477-480` | ELA (JPEG forensics) has nothing to find on the official set | ELA runs on JPEG uploads; the corrected dataset includes JPEG tampering |
| F15 | Provider NPIs fail the real NPI checksum (Luhn with the 80840 prefix) | Verified for all 8 NPIs in `DOCTORS` | A strict NPI validator rejects every claim | Validate NPI format (10 digits) only; checksum failures are logged as a warning |
| F16 | A prescription missing its refills shows **no marker**; the row is simply omitted | `generate_prescription` | Only detectable by absence | Extraction checks for required prescription fields |
| F17 | The Medicare card prints **no expiry date**; an expired card shows only a stamp | `_id_medicare_card` | Expiry can't be extracted for those cards | KYC also reads the "CARD EXPIRED" stamp |
| F18 | Small quirks: | | | Handled in the harness and loaders |
| | • The Gold PDF goes to `./policy/`, not `dataset/policies/` | `generate_gold_policy.py:884` | | |
| | • `metadata.json` paths are absolute (docs) vs relative (unknowns) | | | |
| | • `generate_unknown.py` appends, so re-running duplicates entries | | | |
| | • `dataset_summary.md` is written to the working directory | `:2162` | | |
| | • Claim numbers say `2024` while all dates are 2025 | `:388` | | |

## Derived labels (`eval/truth.py`)
Rules are evaluated top to bottom; the first match wins. They mirror the brief's orchestrator rule:

1. Unknown document → **ESCALATE** (the instructors' label)
2. Hard failure → **REJECT**: `expired_id`, `tampered_id`, `uncovered_procedure`, or `missing_fields` (claim or Rx)
3. Fraud label, or a blur-flagged scan (low confidence) → **ESCALATE**
4. Otherwise → **APPROVE**. An expiring-soon ID is approved with a warning.

Flags apply only to the document that carries them, as in `metadata.json`. A case's decision is ESCALATE if any of
its documents is ESCALATE; otherwise REJECT if any is REJECT; otherwise APPROVE.

**Result on the official set (seed 42):**
- Documents: **122 APPROVE · 21 REJECT · 12 ESCALATE**.
- Cases (30 patients + 4 standalone unknowns): 5 APPROVE · 18 REJECT · 11 ESCALATE.
- **6 labels are not visible in the pixels:**
  - `claim_PT_69470` (structuring)
  - `id_PT_39451` (name mismatch)
  - `id_PT_57795`, `id_PT_62383`, `id_PT_74454` (tampered)
  - `rx_PT_88139` (blur not applied)
- The eval reports decision accuracy on all 155 documents **and** on the 149 with visible labels.

## Splits
- **dev / heldout:** clusters are split 15/15, stratified by fraud type and edge case. Prompts are only ever tuned
  on dev.
- **test20:** a deterministic 20-document set covering every category, decision and visible edge case.
- **seed 7:** a generalization set from the same generator with a different content seed. We never inspect it
  during development.

## Spike results (checkpoint 1)

**RapidOCR** (PP-OCRv6, onnxruntime, Apple M4):
- Speed: about 1 s per page.
- Token recall against ground truth:

  | Document | Token recall |
  |---|---|
  | UB-04 claim (rotated scan) | 99.5% |
  | CMS-1500 claim | 100% |
  | ID card | 100% |
  | Discharge summary | 97.9% |
  | Blurred prescription | 97.4% |
  | Handwritten amendment | 98.3% (missed the handwritten DOB) |
  | Bank statement | 96.3% |

- Handwriting is the gap. It is covered by the plan's fallback to Claude vision.

**Docling:**
- Both PDFs parse with section headers.
- The 24-row benefits table is intact.
- Table 4.1 is recovered completely once its fragments are stitched (F8).
- Conversion time: 31 s on the first call (model load), 8 s after that.
