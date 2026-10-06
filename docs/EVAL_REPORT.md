# MediShield evaluation report

_Assembled 2026-10-05 16:07 from `docs/eval_results/` by `make report`. Every number comes from running the real pipeline (Claude Sonnet 5.5 / Opus 5.5, RapidOCR, Docling, Qdrant) on labelled documents._

**How to read this.** Prompts and thresholds were tuned on the *dev* split only. The *held-out* split, the *seed-7* set (generated with a different random seed and never inspected during development) and the multilingual held-out members are reported without tuning. Decision accuracy is shown on **all** labels and on the labels that are actually **visible in the pixels**: the instructors' generator records a few labels (tampered IDs, a name mismatch, a structuring fraud, a blur) that it never draws, so no system can see them (see `docs/dataset_findings.md`).

## Headline

| Run | Docs | Classification | Extraction (claim fields) | Retrieval Recall@3 | Decisions (all labels) | Decisions (visible labels) | Cost / case |
|---|---|---|---|---|---|---|---|
| Official dataset · dev | 77 | 100.0% | 100.0% | 100.0% | 96.1% | 100.0% | $0.12 |
| Official dataset · heldout | 78 | 100.0% | 100.0% | 100.0% | 96.2% | 100.0% | $0.13 |
| Corrected dataset · all | 155 | 100.0% | 100.0% | 100.0% | 98.1% | 98.7% | $0.13 |
| Unseen generalisation set · all | 155 | 100.0% | 100.0% | 100.0% | 96.1% | 100.0% | $0.12 |
| Unseen set with the tampering · all | 155 | 100.0% | 100.0% | 100.0% | 98.1% | 99.4% | $0.12 |
| Spanish and Hindi · dev | 40 | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | $0.13 |
| Spanish and Hindi · heldout | 40 | 100.0% | 100.0% | 100.0% | 95.0% | 95.0% | $0.14 |

## Robustness

- **Prompt-injection red team:** 0 decision flips in 7 adversarial documents; poisoned policy PDF held (excluded code stayed NOT_COVERED). Details: `docs/redteam.md`.
- **Tamper forensics** (24 ID cards, forged expiry dates): typography check caught 19/24 retyped dates in PNGs (0/24 clean cards flagged); ELA caught 9/24 spliced regions with 8/48 false alarms, so it is advisory only.

## OCR-first routing (page images are sent to a model only when OCR is not enough)

Measured on the dev split with the same documents and the same prompts. *Always vision* sends every page image to the model (classifier, extractor, KYC visual review). *OCR-first* skips the classifier model call when the printed title words settle the type on a clean OCR page, and skips the KYC visual review when OCR is clean and neither forensic check flags the card. *OCR-first + text-only extraction* additionally reads fields from OCR text alone first; it is **off** because it saved little and cost accuracy.

| Configuration | Decisions (all) | Decisions (visible) | Claim-field extraction | Cost / case (uncached) | Classifier $ | KYC visual $ | Extractor $ |
|---|---|---|---|---|---|---|---|
| Always vision | 96.1% | 100.0% | 100.0% | $0.157 | $0.52 | $0.15 | $0.86 |
| OCR-first (shipped) | 96.1% | 100.0% | 100.0% | $0.118 | $0.02 | $0.00 | $0.86 |
| OCR-first + text-only extraction | 92.2% | 96.0% | 97.7% | $0.113 | $0.02 | $0.00 | $0.76 |

## Spanish and Hindi

| Split | Language | Docs | Classification | Extraction (all fields) | Decisions | Mean classifier confidence |
|---|---|---|---|---|---|---|
| dev | es | 20 | 100.0% | 100.0% | 100.0% | 0.98 |
| dev | hi | 20 | 100.0% | 98.7% | 100.0% | 0.77 |
| heldout | es | 20 | 100.0% | 100.0% | 95.0% | 0.98 |
| heldout | hi | 20 | 100.0% | 98.7% | 95.0% | 0.77 |

## Confidence calibration

ECE = expected calibration error (lower is better); Brier = mean squared error of the confidence as a probability of being correct. The isotonic calibrator is fitted on the dev split and applied unchanged elsewhere.

| Run | Docs | Accuracy | ECE raw | ECE calibrated | Brier raw | Brier calibrated |
|---|---|---|---|---|---|---|
| official-dev (in-sample) | 77 | 96.1% | 0.107 | 0.019 | 0.057 | 0.038 |
| official-heldout | 78 | 96.2% | 0.135 | 0.015 | 0.064 | 0.038 |
| corrected-all | 155 | 98.1% | 0.102 | 0.003 | 0.043 | 0.019 |
| seed7-all | 155 | 96.1% | 0.088 | 0.015 | 0.056 | 0.037 |
| seed7_corrected-all | 155 | 98.1% | 0.096 | 0.004 | 0.039 | 0.018 |
| multilingual-dev | 40 | 100.0% | 0.081 | 0.031 | 0.008 | 0.001 |
| multilingual-heldout | 40 | 95.0% | 0.070 | 0.016 | 0.049 | 0.047 |

---

## Official dataset, dev split (prompts were tuned here)

_Generated 2026-10-05T15:44:05 by `make eval`. Prompts are tuned on the dev split only; held-out and seed-7 numbers are reported without tuning._

#### Rubric metrics

| Rubric criterion (weight) | Metric | Result |
|---|---|---|
| Classification (20%) | document-type accuracy | **100.0%** (77 docs) |
| Extraction (20%) | required claim fields correct (ICD, CPT, line amounts, total, NPI, provider) | **100.0%** (87 fields) |
| Policy retrieval (15%) | Recall@3 of the governing policy section per billed code / MRR | **100.0%** / 0.9884 (43 queries) |
| Decision correctness (25%) | per-document decision accuracy, all labels | **96.1%** (77 docs) |
| | ... on labels visible in the pixels | **100.0%** (74 docs) |
| | case roll-up accuracy | 82.3% (17 cases) |

#### Decisions

Accuracy by true document type: ID_DOCUMENT 86.7%, CLAIM_FORM 93.3%, DISCHARGE_SUMMARY 100.0%, PRESCRIPTION 100.0%, POLICY_AMENDMENT 100.0%, UNKNOWN 100.0%

Confusion (expected -> predicted): `APPROVE->APPROVE` 62, `ESCALATE->APPROVE` 1, `ESCALATE->ESCALATE` 4, `REJECT->APPROVE` 2, `REJECT->REJECT` 8

**Fraud scenarios detected (per-document score >= 0.3):** amount_under_10k (not visible) 0/1, date_conflict 1/1, proc_diag_mismatch 1/1

False-positive fraud escalations on non-fraud documents: 0

**Edge cases handled as labelled:** expired_id 3/3, expiring_soon_id 2/2, missing_fields 3/3, tampered_id (not visible) 0/2, uncovered_procedure 2/2, unknown_document 2/2

<details><summary>Decision errors</summary>

- claim_PT_69470: expected ESCALATE got APPROVE (R4_default) [label not visible] - all checks passed
- id_PT_57795: expected REJECT got APPROVE (R4_default) [label not visible] - all checks passed
- id_PT_74454: expected REJECT got APPROVE (R4_default) [label not visible] - all checks passed

</details>

#### Extraction detail

All scored fields across document types: **99.2%**. By type: ID_DOCUMENT 93.0%, CLAIM_FORM 99.4%, DISCHARGE_SUMMARY 100.0%, PRESCRIPTION 100.0%, POLICY_AMENDMENT 100.0%

| Field | Accuracy | n |
|---|---|---|
| CLAIM_FORM.attending_physician | 100.0% | 13 |
| CLAIM_FORM.billing_provider | 100.0% | 15 |
| CLAIM_FORM.claim_number | 100.0% | 15 |
| CLAIM_FORM.cpt_codes | 100.0% | 15 |
| CLAIM_FORM.icd_codes | 100.0% | 14 |
| CLAIM_FORM.line_charges | 100.0% | 15 |
| CLAIM_FORM.patient_dob | 93.3% | 15 |
| CLAIM_FORM.patient_name | 100.0% | 15 |
| CLAIM_FORM.policy_number | 100.0% | 15 |
| CLAIM_FORM.provider_npi | 100.0% | 13 |
| CLAIM_FORM.service_date | 100.0% | 15 |
| CLAIM_FORM.total_charge | 100.0% | 15 |
| DISCHARGE_SUMMARY.admit_date | 100.0% | 15 |
| DISCHARGE_SUMMARY.attending_physician | 100.0% | 15 |
| DISCHARGE_SUMMARY.discharge_date | 100.0% | 15 |
| DISCHARGE_SUMMARY.facility | 100.0% | 15 |
| DISCHARGE_SUMMARY.patient_dob | 100.0% | 15 |
| DISCHARGE_SUMMARY.patient_name | 100.0% | 15 |
| DISCHARGE_SUMMARY.primary_icd | 100.0% | 15 |
| ID_DOCUMENT.dob | 100.0% | 10 |
| ID_DOCUMENT.expiry_date | 91.7% | 12 |
| ID_DOCUMENT.name_on_id | 100.0% | 15 |
| ID_DOCUMENT.policy_number | 66.7% | 6 |
| POLICY_AMENDMENT.amendment_type | 100.0% | 15 |
| POLICY_AMENDMENT.dob | 100.0% | 15 |
| POLICY_AMENDMENT.effective_date | 100.0% | 15 |
| POLICY_AMENDMENT.policy_number | 100.0% | 15 |
| POLICY_AMENDMENT.policyholder | 100.0% | 15 |
| PRESCRIPTION.dea_number | 100.0% | 15 |
| PRESCRIPTION.drugs | 100.0% | 15 |
| PRESCRIPTION.patient_dob | 100.0% | 15 |
| PRESCRIPTION.patient_name | 100.0% | 15 |
| PRESCRIPTION.prescriber | 100.0% | 15 |
| PRESCRIPTION.prescriber_npi | 100.0% | 15 |
| PRESCRIPTION.rx_date | 100.0% | 15 |

<details><summary>Field misses</summary>

- claim_PT_82132.patient_dob: gt='11/14/1951' got=None
- id_PT_15075.expiry_date: gt='2025-05-04' got=None
- id_PT_67125.policy_number: gt='MED-GLD-1327691' got=None
- id_PT_99687.policy_number: gt='MED-GLD-6218367' got=None

</details>

#### Retrieval detail

Gold sections come from `eval/retrieval_gold.json`, built from the policy text (not retriever output).

#### Operations

- Cases: 17, documents: 77
- Case latency (cold path incl. LLM): p50 3.3s, p95 5.7s
- Cost without cache: $2.00 total, $0.118/case, $0.026/document. Spent this run: $0.00
- Cost by agent: classifier $0.02, extractor $0.86, policy $0.60, fraud $0.40, justify $0.12
- LLM calls: 130 (126 served from cache); retries on Opus: {'extractor': 3, 'classifier': 1}
- Mean OCR grounding rate 97.9%; mean support rate (grounded or corroborated by the member database) 98.5%


---

## Official dataset, held-out split (never tuned on)

_Generated 2026-10-05T15:46:38 by `make eval`. Prompts are tuned on the dev split only; held-out and seed-7 numbers are reported without tuning._

#### Rubric metrics

| Rubric criterion (weight) | Metric | Result |
|---|---|---|
| Classification (20%) | document-type accuracy | **100.0%** (78 docs) |
| Extraction (20%) | required claim fields correct (ICD, CPT, line amounts, total, NPI, provider) | **100.0%** (94 fields) |
| Policy retrieval (15%) | Recall@3 of the governing policy section per billed code / MRR | **100.0%** / 0.9773 (44 queries) |
| Decision correctness (25%) | per-document decision accuracy, all labels | **96.2%** (78 docs) |
| | ... on labels visible in the pixels | **100.0%** (75 docs) |
| | case roll-up accuracy | 88.2% (17 cases) |

#### Decisions

Accuracy by true document type: ID_DOCUMENT 86.7%, CLAIM_FORM 100.0%, DISCHARGE_SUMMARY 100.0%, PRESCRIPTION 93.3%, POLICY_AMENDMENT 100.0%, UNKNOWN 100.0%

Confusion (expected -> predicted): `APPROVE->APPROVE` 60, `ESCALATE->APPROVE` 2, `ESCALATE->ESCALATE` 5, `REJECT->APPROVE` 1, `REJECT->REJECT` 10

**Fraud scenarios detected (per-document score >= 0.3):** duplicate_claim 1/1, name_mismatch (not visible) 0/1, readmission_30d 1/1

False-positive fraud escalations on non-fraud documents: 0

**Edge cases handled as labelled:** blurred_scan 1/1, blurred_scan (not visible) 0/1, expired_id 2/2, expiring_soon_id 3/3, missing_fields 5/5, tampered_id (not visible) 0/1, uncovered_procedure 3/3, unknown_document 2/2

<details><summary>Decision errors</summary>

- id_PT_39451: expected ESCALATE got APPROVE (R4_default) [label not visible] - all checks passed
- id_PT_62383: expected REJECT got APPROVE (R4_default) [label not visible] - all checks passed
- rx_PT_88139: expected ESCALATE got APPROVE (R4_default) [label not visible] - all checks passed

</details>

#### Extraction detail

All scored fields across document types: **98.5%**. By type: ID_DOCUMENT 83.0%, CLAIM_FORM 100.0%, DISCHARGE_SUMMARY 100.0%, PRESCRIPTION 100.0%, POLICY_AMENDMENT 100.0%

| Field | Accuracy | n |
|---|---|---|
| CLAIM_FORM.attending_physician | 100.0% | 14 |
| CLAIM_FORM.billing_provider | 100.0% | 16 |
| CLAIM_FORM.claim_number | 100.0% | 16 |
| CLAIM_FORM.cpt_codes | 100.0% | 16 |
| CLAIM_FORM.icd_codes | 100.0% | 16 |
| CLAIM_FORM.line_charges | 100.0% | 16 |
| CLAIM_FORM.patient_dob | 100.0% | 16 |
| CLAIM_FORM.patient_name | 100.0% | 16 |
| CLAIM_FORM.policy_number | 100.0% | 16 |
| CLAIM_FORM.provider_npi | 100.0% | 14 |
| CLAIM_FORM.service_date | 100.0% | 16 |
| CLAIM_FORM.total_charge | 100.0% | 16 |
| DISCHARGE_SUMMARY.admit_date | 100.0% | 15 |
| DISCHARGE_SUMMARY.attending_physician | 100.0% | 15 |
| DISCHARGE_SUMMARY.discharge_date | 100.0% | 15 |
| DISCHARGE_SUMMARY.facility | 100.0% | 15 |
| DISCHARGE_SUMMARY.patient_dob | 100.0% | 15 |
| DISCHARGE_SUMMARY.patient_name | 100.0% | 15 |
| DISCHARGE_SUMMARY.primary_icd | 100.0% | 15 |
| ID_DOCUMENT.dob | 100.0% | 14 |
| ID_DOCUMENT.expiry_date | 75.0% | 12 |
| ID_DOCUMENT.name_on_id | 100.0% | 15 |
| ID_DOCUMENT.policy_number | 16.7% | 6 |
| POLICY_AMENDMENT.amendment_type | 100.0% | 15 |
| POLICY_AMENDMENT.dob | 100.0% | 15 |
| POLICY_AMENDMENT.effective_date | 100.0% | 15 |
| POLICY_AMENDMENT.policy_number | 100.0% | 15 |
| POLICY_AMENDMENT.policyholder | 100.0% | 15 |
| PRESCRIPTION.dea_number | 100.0% | 14 |
| PRESCRIPTION.drugs | 100.0% | 14 |
| PRESCRIPTION.patient_dob | 100.0% | 15 |
| PRESCRIPTION.patient_name | 100.0% | 15 |
| PRESCRIPTION.prescriber | 100.0% | 15 |
| PRESCRIPTION.prescriber_npi | 100.0% | 15 |
| PRESCRIPTION.rx_date | 100.0% | 15 |

<details><summary>Field misses</summary>

- id_PT_19116.policy_number: gt='MED-GLD-6770619' got=None
- id_PT_39451.policy_number: gt='MED-GLD-5446912' got=None
- id_PT_71993.expiry_date: gt='2029-02-16' got=None
- id_PT_47353.policy_number: gt='MED-GLD-8670955' got=None
- id_PT_50538.policy_number: gt='MED-GLD-1744682' got=None
- id_PT_72021.expiry_date: gt='2029-05-06' got=None
- id_PT_88139.policy_number: gt='MED-GLD-8563202' got=None
- id_PT_55056.expiry_date: gt='2029-01-02' got=None

</details>

#### Retrieval detail

Gold sections come from `eval/retrieval_gold.json`, built from the policy text (not retriever output).

#### Operations

- Cases: 17, documents: 78
- Case latency (cold path incl. LLM): p50 8.3s, p95 13.5s
- Cost without cache: $2.15 total, $0.127/case, $0.028/document. Spent this run: $0.13
- Cost by agent: classifier $0.03, extractor $0.92, policy $0.66, fraud $0.42, justify $0.13
- LLM calls: 135 (113 served from cache); retries on Opus: {'extractor': 5, 'classifier': 1}
- Mean OCR grounding rate 98.4%; mean support rate (grounded or corroborated by the member database) 99.2%


---

## Corrected dataset (tampering, name mismatch and blur actually drawn), all documents

_Generated 2026-10-05T15:49:42 by `make eval`. Prompts are tuned on the dev split only; held-out and seed-7 numbers are reported without tuning._

#### Rubric metrics

| Rubric criterion (weight) | Metric | Result |
|---|---|---|
| Classification (20%) | document-type accuracy | **100.0%** (155 docs) |
| Extraction (20%) | required claim fields correct (ICD, CPT, line amounts, total, NPI, provider) | **100.0%** (181 fields) |
| Policy retrieval (15%) | Recall@3 of the governing policy section per billed code / MRR | **100.0%** / 0.9828 (87 queries) |
| Decision correctness (25%) | per-document decision accuracy, all labels | **98.1%** (155 docs) |
| | ... on labels visible in the pixels | **98.7%** (154 docs) |
| | case roll-up accuracy | 91.2% (34 cases) |

#### Decisions

Accuracy by true document type: ID_DOCUMENT 93.3%, CLAIM_FORM 96.8%, DISCHARGE_SUMMARY 100.0%, PRESCRIPTION 100.0%, POLICY_AMENDMENT 100.0%, UNKNOWN 100.0%

Confusion (expected -> predicted): `APPROVE->APPROVE` 122, `ESCALATE->APPROVE` 1, `ESCALATE->ESCALATE` 11, `REJECT->APPROVE` 1, `REJECT->ESCALATE` 1, `REJECT->REJECT` 19

**Fraud scenarios detected (per-document score >= 0.3):** amount_under_10k (not visible) 0/1, date_conflict 1/1, duplicate_claim 1/1, name_mismatch 0/1, proc_diag_mismatch 1/1, readmission_30d 1/1

False-positive fraud escalations on non-fraud documents: 0

**Edge cases handled as labelled:** blurred_scan 2/2, expired_id 5/5, expiring_soon_id 5/5, missing_fields 8/8, tampered_id 1/3, uncovered_procedure 5/5, unknown_document 4/4

<details><summary>Decision errors</summary>

- claim_PT_69470: expected ESCALATE got APPROVE (R4_default) [label not visible] - all checks passed
- id_PT_57795: expected REJECT got ESCALATE (R3_fraud_or_low_confidence) - KYC warnings: typography_inconsistent
- id_PT_74454: expected REJECT got APPROVE (R4_default) - all checks passed

</details>

#### Extraction detail

All scored fields across document types: **98.8%**. By type: ID_DOCUMENT 87.8%, CLAIM_FORM 99.7%, DISCHARGE_SUMMARY 100.0%, PRESCRIPTION 100.0%, POLICY_AMENDMENT 100.0%

| Field | Accuracy | n |
|---|---|---|
| CLAIM_FORM.attending_physician | 100.0% | 27 |
| CLAIM_FORM.billing_provider | 100.0% | 31 |
| CLAIM_FORM.claim_number | 100.0% | 31 |
| CLAIM_FORM.cpt_codes | 100.0% | 31 |
| CLAIM_FORM.icd_codes | 100.0% | 30 |
| CLAIM_FORM.line_charges | 100.0% | 31 |
| CLAIM_FORM.patient_dob | 96.8% | 31 |
| CLAIM_FORM.patient_name | 100.0% | 31 |
| CLAIM_FORM.policy_number | 100.0% | 31 |
| CLAIM_FORM.provider_npi | 100.0% | 27 |
| CLAIM_FORM.service_date | 100.0% | 31 |
| CLAIM_FORM.total_charge | 100.0% | 31 |
| DISCHARGE_SUMMARY.admit_date | 100.0% | 30 |
| DISCHARGE_SUMMARY.attending_physician | 100.0% | 30 |
| DISCHARGE_SUMMARY.discharge_date | 100.0% | 30 |
| DISCHARGE_SUMMARY.facility | 100.0% | 30 |
| DISCHARGE_SUMMARY.patient_dob | 100.0% | 30 |
| DISCHARGE_SUMMARY.patient_name | 100.0% | 30 |
| DISCHARGE_SUMMARY.primary_icd | 100.0% | 30 |
| ID_DOCUMENT.dob | 100.0% | 24 |
| ID_DOCUMENT.expiry_date | 83.3% | 24 |
| ID_DOCUMENT.name_on_id | 100.0% | 30 |
| ID_DOCUMENT.policy_number | 41.7% | 12 |
| POLICY_AMENDMENT.amendment_type | 100.0% | 30 |
| POLICY_AMENDMENT.dob | 100.0% | 30 |
| POLICY_AMENDMENT.effective_date | 100.0% | 30 |
| POLICY_AMENDMENT.policy_number | 100.0% | 30 |
| POLICY_AMENDMENT.policyholder | 100.0% | 30 |
| PRESCRIPTION.dea_number | 100.0% | 29 |
| PRESCRIPTION.drugs | 100.0% | 29 |
| PRESCRIPTION.patient_dob | 100.0% | 30 |
| PRESCRIPTION.patient_name | 100.0% | 30 |
| PRESCRIPTION.prescriber | 100.0% | 30 |
| PRESCRIPTION.prescriber_npi | 100.0% | 30 |
| PRESCRIPTION.rx_date | 100.0% | 30 |

<details><summary>Field misses</summary>

- id_PT_19116.policy_number: gt='MED-GLD-6770619' got=None
- id_PT_39451.policy_number: gt='MED-GLD-5446912' got=None
- id_PT_71993.expiry_date: gt='2029-02-16' got=None
- claim_PT_82132.patient_dob: gt='11/14/1951' got=None
- id_PT_47353.policy_number: gt='MED-GLD-8670955' got=None
- id_PT_15075.expiry_date: gt='2025-05-04' got=None
- id_PT_50538.policy_number: gt='MED-GLD-1744682' got=None
- id_PT_72021.expiry_date: gt='2029-05-06' got=None
- id_PT_67125.policy_number: gt='MED-GLD-1327691' got=None
- id_PT_99687.policy_number: gt='MED-GLD-6218367' got=None
- id_PT_88139.policy_number: gt='MED-GLD-8563202' got=None
- id_PT_55056.expiry_date: gt='2029-01-02' got=None

</details>

#### Retrieval detail

Gold sections come from `eval/retrieval_gold.json`, built from the policy text (not retriever output).

#### Operations

- Cases: 34, documents: 155
- Case latency (cold path incl. LLM): p50 4.4s, p95 8.5s
- Cost without cache: $4.25 total, $0.125/case, $0.027/document. Spent this run: $0.05
- Cost by agent: classifier $0.06, extractor $1.82, kyc_visual $0.03, policy $1.26, fraud $0.83, justify $0.25
- LLM calls: 272 (254 served from cache); retries on Opus: {'extractor': 10, 'kyc_visual': 1, 'classifier': 2}
- Mean OCR grounding rate 98.2%; mean support rate (grounded or corroborated by the member database) 98.8%


---

## Unseen generalisation set (generator seed 7), all documents

_Generated 2026-10-05T15:54:26 by `make eval`. Prompts are tuned on the dev split only; held-out and seed-7 numbers are reported without tuning._

#### Rubric metrics

| Rubric criterion (weight) | Metric | Result |
|---|---|---|
| Classification (20%) | document-type accuracy | **100.0%** (155 docs) |
| Extraction (20%) | required claim fields correct (ICD, CPT, line amounts, total, NPI, provider) | **100.0%** (183 fields) |
| Policy retrieval (15%) | Recall@3 of the governing policy section per billed code / MRR | **100.0%** / 0.9943 (87 queries) |
| Decision correctness (25%) | per-document decision accuracy, all labels | **96.1%** (155 docs) |
| | ... on labels visible in the pixels | **100.0%** (149 docs) |
| | case roll-up accuracy | 82.3% (34 cases) |

#### Decisions

Accuracy by true document type: ID_DOCUMENT 86.7%, CLAIM_FORM 93.5%, DISCHARGE_SUMMARY 100.0%, PRESCRIPTION 100.0%, POLICY_AMENDMENT 100.0%, UNKNOWN 100.0%

Confusion (expected -> predicted): `APPROVE->APPROVE` 122, `ESCALATE->APPROVE` 2, `ESCALATE->ESCALATE` 10, `REJECT->APPROVE` 4, `REJECT->REJECT` 17

**Fraud scenarios detected (per-document score >= 0.3):** amount_under_10k (not visible) 0/1, date_conflict 1/1, duplicate_claim 1/1, name_mismatch (not visible) 0/1, proc_diag_mismatch 1/1, readmission_30d 1/1

False-positive fraud escalations on non-fraud documents: 0

**Edge cases handled as labelled:** blurred_scan 2/2, expired_id 5/5, expiring_soon_id 5/5, missing_fields 7/7, missing_fields (not visible) 0/1, tampered_id (not visible) 0/3, uncovered_procedure 5/5, unknown_document 4/4

<details><summary>Decision errors</summary>

- claim_PT_51175: expected ESCALATE got APPROVE (R4_default) [label not visible] - fraud signal llm:discharge_date_mismatch (w=0.2): Claim lists discharge date 2025-02-21, but discharge_PT_51175 records discharge on 2025-02-20 (rx_PT_51175 is also dated 2025-02-20). This could overstate the length of s
- id_PT_56591: expected ESCALATE got APPROVE (R4_default) [label not visible] - all checks passed
- id_PT_83336: expected REJECT got APPROVE (R4_default) [label not visible] - all checks passed
- id_PT_72109: expected REJECT got APPROVE (R4_default) [label not visible] - all checks passed
- id_PT_45213: expected REJECT got APPROVE (R4_default) [label not visible] - all checks passed
- claim_PT_45523: expected REJECT got APPROVE (R4_default) [label not visible] - fraud signal llm:claim_number_year_mismatch (w=0.1): Claim number UB04-CLM-2024-00028 contains the year 2024, but all service and admission dates are in 2025.

</details>

#### Extraction detail

All scored fields across document types: **98.5%**. By type: ID_DOCUMENT 84.4%, CLAIM_FORM 99.7%, DISCHARGE_SUMMARY 100.0%, PRESCRIPTION 100.0%, POLICY_AMENDMENT 100.0%

| Field | Accuracy | n |
|---|---|---|
| CLAIM_FORM.attending_physician | 100.0% | 28 |
| CLAIM_FORM.billing_provider | 100.0% | 31 |
| CLAIM_FORM.claim_number | 100.0% | 31 |
| CLAIM_FORM.cpt_codes | 100.0% | 31 |
| CLAIM_FORM.icd_codes | 100.0% | 31 |
| CLAIM_FORM.line_charges | 100.0% | 31 |
| CLAIM_FORM.patient_dob | 96.8% | 31 |
| CLAIM_FORM.patient_name | 100.0% | 31 |
| CLAIM_FORM.policy_number | 100.0% | 31 |
| CLAIM_FORM.provider_npi | 100.0% | 28 |
| CLAIM_FORM.service_date | 100.0% | 31 |
| CLAIM_FORM.total_charge | 100.0% | 31 |
| DISCHARGE_SUMMARY.admit_date | 100.0% | 30 |
| DISCHARGE_SUMMARY.attending_physician | 100.0% | 30 |
| DISCHARGE_SUMMARY.discharge_date | 100.0% | 30 |
| DISCHARGE_SUMMARY.facility | 100.0% | 30 |
| DISCHARGE_SUMMARY.patient_dob | 100.0% | 30 |
| DISCHARGE_SUMMARY.patient_name | 100.0% | 30 |
| DISCHARGE_SUMMARY.primary_icd | 100.0% | 30 |
| ID_DOCUMENT.dob | 100.0% | 24 |
| ID_DOCUMENT.expiry_date | 66.7% | 24 |
| ID_DOCUMENT.name_on_id | 100.0% | 30 |
| ID_DOCUMENT.policy_number | 50.0% | 12 |
| POLICY_AMENDMENT.amendment_type | 100.0% | 30 |
| POLICY_AMENDMENT.dob | 100.0% | 30 |
| POLICY_AMENDMENT.effective_date | 100.0% | 30 |
| POLICY_AMENDMENT.policy_number | 100.0% | 30 |
| POLICY_AMENDMENT.policyholder | 100.0% | 30 |
| PRESCRIPTION.dea_number | 100.0% | 29 |
| PRESCRIPTION.drugs | 100.0% | 29 |
| PRESCRIPTION.patient_dob | 100.0% | 30 |
| PRESCRIPTION.patient_name | 100.0% | 30 |
| PRESCRIPTION.prescriber | 100.0% | 30 |
| PRESCRIPTION.prescriber_npi | 100.0% | 30 |
| PRESCRIPTION.rx_date | 100.0% | 30 |

<details><summary>Field misses</summary>

- id_PT_51175.policy_number: gt='MED-GLD-2728987' got=None
- id_PT_83148.expiry_date: gt='2029-10-02' got=None
- id_PT_23393.policy_number: gt='MED-GLD-2179699' got=None
- id_PT_39234.expiry_date: gt='2026-01-20' got=None
- claim_PT_36787.patient_dob: gt='07/24/1960' got=None
- id_PT_95964.expiry_date: gt='2025-02-04' got=None
- id_PT_18094.policy_number: gt='MED-GLD-9782983' got=None
- id_PT_83336.expiry_date: gt='2029-08-10' got=None
- id_PT_49977.policy_number: gt='MED-GLD-5493940' got=None
- id_PT_61522.expiry_date: gt='2029-09-15' got='2028-09-15'
- id_PT_72109.policy_number: gt='MED-GLD-1316094' got=None
- id_PT_73231.expiry_date: gt='2029-01-19' got=None
- id_PT_55083.expiry_date: gt='2025-06-18' got=None
- id_PT_55044.policy_number: gt='MED-GLD-4413086' got=None
- id_PT_41992.expiry_date: gt='2029-04-16' got=None

</details>

#### Retrieval detail

Gold sections come from `eval/retrieval_gold.json`, built from the policy text (not retriever output).

#### Operations

- Cases: 34, documents: 155
- Case latency (cold path incl. LLM): p50 7.9s, p95 10.5s
- Cost without cache: $4.14 total, $0.122/case, $0.027/document. Spent this run: $0.24
- Cost by agent: classifier $0.07, extractor $1.77, policy $1.21, fraud $0.84, justify $0.25
- LLM calls: 267 (226 served from cache); retries on Opus: {'extractor': 8, 'classifier': 3}
- Mean OCR grounding rate 98.5%; mean support rate (grounded or corroborated by the member database) 99.3%


---

## Unseen set with the tampering, name mismatch and blur drawn (corrected seed 7), all documents

_Generated 2026-10-05T15:58:20 by `make eval`. Prompts are tuned on the dev split only; held-out and seed-7 numbers are reported without tuning._

#### Rubric metrics

| Rubric criterion (weight) | Metric | Result |
|---|---|---|
| Classification (20%) | document-type accuracy | **100.0%** (155 docs) |
| Extraction (20%) | required claim fields correct (ICD, CPT, line amounts, total, NPI, provider) | **100.0%** (183 fields) |
| Policy retrieval (15%) | Recall@3 of the governing policy section per billed code / MRR | **100.0%** / 0.9943 (87 queries) |
| Decision correctness (25%) | per-document decision accuracy, all labels | **98.1%** (155 docs) |
| | ... on labels visible in the pixels | **99.4%** (153 docs) |
| | case roll-up accuracy | 91.2% (34 cases) |

#### Decisions

Accuracy by true document type: ID_DOCUMENT 96.7%, CLAIM_FORM 93.5%, DISCHARGE_SUMMARY 100.0%, PRESCRIPTION 100.0%, POLICY_AMENDMENT 100.0%, UNKNOWN 100.0%

Confusion (expected -> predicted): `APPROVE->APPROVE` 122, `ESCALATE->APPROVE` 1, `ESCALATE->ESCALATE` 11, `REJECT->APPROVE` 1, `REJECT->ESCALATE` 1, `REJECT->REJECT` 19

**Fraud scenarios detected (per-document score >= 0.3):** amount_under_10k (not visible) 0/1, date_conflict 1/1, duplicate_claim 1/1, name_mismatch 0/1, proc_diag_mismatch 1/1, readmission_30d 1/1

False-positive fraud escalations on non-fraud documents: 0

**Edge cases handled as labelled:** blurred_scan 2/2, expired_id 5/5, expiring_soon_id 5/5, missing_fields 7/7, missing_fields (not visible) 0/1, tampered_id 2/3, uncovered_procedure 5/5, unknown_document 4/4

<details><summary>Decision errors</summary>

- claim_PT_51175: expected ESCALATE got APPROVE (R4_default) [label not visible] - fraud signal llm:discharge_date_mismatch (w=0.2): Claim lists discharge date 2025-02-21, but discharge_PT_51175 records discharge on 2025-02-20 (rx_PT_51175 is also dated 2025-02-20). This could overstate the length of s
- id_PT_72109: expected REJECT got ESCALATE (R3_fraud_or_low_confidence) - KYC warnings: typography_inconsistent
- claim_PT_45523: expected REJECT got APPROVE (R4_default) [label not visible] - fraud signal llm:claim_number_year_mismatch (w=0.1): Claim number UB04-CLM-2024-00028 contains the year 2024, but all service and admission dates are in 2025.

</details>

#### Extraction detail

All scored fields across document types: **98.6%**. By type: ID_DOCUMENT 85.6%, CLAIM_FORM 99.7%, DISCHARGE_SUMMARY 100.0%, PRESCRIPTION 100.0%, POLICY_AMENDMENT 100.0%

| Field | Accuracy | n |
|---|---|---|
| CLAIM_FORM.attending_physician | 100.0% | 28 |
| CLAIM_FORM.billing_provider | 100.0% | 31 |
| CLAIM_FORM.claim_number | 100.0% | 31 |
| CLAIM_FORM.cpt_codes | 100.0% | 31 |
| CLAIM_FORM.icd_codes | 100.0% | 31 |
| CLAIM_FORM.line_charges | 100.0% | 31 |
| CLAIM_FORM.patient_dob | 96.8% | 31 |
| CLAIM_FORM.patient_name | 100.0% | 31 |
| CLAIM_FORM.policy_number | 100.0% | 31 |
| CLAIM_FORM.provider_npi | 100.0% | 28 |
| CLAIM_FORM.service_date | 100.0% | 31 |
| CLAIM_FORM.total_charge | 100.0% | 31 |
| DISCHARGE_SUMMARY.admit_date | 100.0% | 30 |
| DISCHARGE_SUMMARY.attending_physician | 100.0% | 30 |
| DISCHARGE_SUMMARY.discharge_date | 100.0% | 30 |
| DISCHARGE_SUMMARY.facility | 100.0% | 30 |
| DISCHARGE_SUMMARY.patient_dob | 100.0% | 30 |
| DISCHARGE_SUMMARY.patient_name | 100.0% | 30 |
| DISCHARGE_SUMMARY.primary_icd | 100.0% | 30 |
| ID_DOCUMENT.dob | 100.0% | 24 |
| ID_DOCUMENT.expiry_date | 70.8% | 24 |
| ID_DOCUMENT.name_on_id | 100.0% | 30 |
| ID_DOCUMENT.policy_number | 50.0% | 12 |
| POLICY_AMENDMENT.amendment_type | 100.0% | 30 |
| POLICY_AMENDMENT.dob | 100.0% | 30 |
| POLICY_AMENDMENT.effective_date | 100.0% | 30 |
| POLICY_AMENDMENT.policy_number | 100.0% | 30 |
| POLICY_AMENDMENT.policyholder | 100.0% | 30 |
| PRESCRIPTION.dea_number | 100.0% | 29 |
| PRESCRIPTION.drugs | 100.0% | 29 |
| PRESCRIPTION.patient_dob | 100.0% | 30 |
| PRESCRIPTION.patient_name | 100.0% | 30 |
| PRESCRIPTION.prescriber | 100.0% | 30 |
| PRESCRIPTION.prescriber_npi | 100.0% | 30 |
| PRESCRIPTION.rx_date | 100.0% | 30 |

<details><summary>Field misses</summary>

- id_PT_51175.policy_number: gt='MED-GLD-2728987' got=None
- id_PT_83148.expiry_date: gt='2029-10-02' got=None
- id_PT_23393.policy_number: gt='MED-GLD-2179699' got=None
- id_PT_39234.expiry_date: gt='2026-01-20' got=None
- claim_PT_36787.patient_dob: gt='07/24/1960' got=None
- id_PT_95964.expiry_date: gt='2025-02-04' got=None
- id_PT_18094.policy_number: gt='MED-GLD-9782983' got=None
- id_PT_49977.policy_number: gt='MED-GLD-5493940' got=None
- id_PT_61522.expiry_date: gt='2029-09-15' got='2028-09-15'
- id_PT_72109.policy_number: gt='MED-GLD-1316094' got=None
- id_PT_73231.expiry_date: gt='2029-01-19' got=None
- id_PT_55083.expiry_date: gt='2025-06-18' got=None
- id_PT_55044.policy_number: gt='MED-GLD-4413086' got=None
- id_PT_41992.expiry_date: gt='2029-04-16' got=None

</details>

#### Retrieval detail

Gold sections come from `eval/retrieval_gold.json`, built from the policy text (not retriever output).

#### Operations

- Cases: 34, documents: 155
- Case latency (cold path incl. LLM): p50 4.1s, p95 27.0s
- Cost without cache: $4.22 total, $0.124/case, $0.027/document. Spent this run: $0.27
- Cost by agent: classifier $0.07, extractor $1.79, kyc_visual $0.06, policy $1.21, fraud $0.84, justify $0.25
- LLM calls: 274 (248 served from cache); retries on Opus: {'extractor': 9, 'classifier': 3, 'kyc_visual': 2}
- Mean OCR grounding rate 98.5%; mean support rate (grounded or corroborated by the member database) 99.3%


---

## Spanish and Hindi, dev members

_Generated 2026-10-05T16:02:28 by `make eval`. Prompts are tuned on the dev split only; held-out and seed-7 numbers are reported without tuning._

#### Rubric metrics

| Rubric criterion (weight) | Metric | Result |
|---|---|---|
| Classification (20%) | document-type accuracy | **100.0%** (40 docs) |
| Extraction (20%) | required claim fields correct (ICD, CPT, line amounts, total, NPI, provider) | **100.0%** (72 fields) |
| Policy retrieval (15%) | Recall@3 of the governing policy section per billed code / MRR | **100.0%** / 1.0 (28 queries) |
| Decision correctness (25%) | per-document decision accuracy, all labels | **100.0%** (40 docs) |
| | ... on labels visible in the pixels | **100.0%** (40 docs) |
| | case roll-up accuracy | 100.0% (14 cases) |

#### Decisions

Accuracy by true document type: CLAIM_FORM 100.0%, PRESCRIPTION 100.0%, ID_DOCUMENT 100.0%, DISCHARGE_SUMMARY 100.0%

Confusion (expected -> predicted): `APPROVE->APPROVE` 34, `REJECT->REJECT` 6

**Fraud scenarios detected (per-document score >= 0.3):** none in split

False-positive fraud escalations on non-fraud documents: 1 (claim_PT_99733_es_uncovered score=0.7)

**Edge cases handled as labelled:** expired_id 2/2, missing_fields 2/2, uncovered_procedure 2/2

#### Extraction detail

All scored fields across document types: **99.4%**. By type: CLAIM_FORM 100.0%, PRESCRIPTION 100.0%, ID_DOCUMENT 100.0%, DISCHARGE_SUMMARY 96.4%

| Field | Accuracy | n |
|---|---|---|
| CLAIM_FORM.attending_physician | 100.0% | 12 |
| CLAIM_FORM.billing_provider | 100.0% | 12 |
| CLAIM_FORM.claim_number | 100.0% | 12 |
| CLAIM_FORM.cpt_codes | 100.0% | 12 |
| CLAIM_FORM.icd_codes | 100.0% | 12 |
| CLAIM_FORM.line_charges | 100.0% | 12 |
| CLAIM_FORM.patient_dob | 100.0% | 12 |
| CLAIM_FORM.patient_name | 100.0% | 12 |
| CLAIM_FORM.policy_number | 100.0% | 12 |
| CLAIM_FORM.provider_npi | 100.0% | 12 |
| CLAIM_FORM.service_date | 100.0% | 12 |
| CLAIM_FORM.total_charge | 100.0% | 12 |
| DISCHARGE_SUMMARY.admit_date | 100.0% | 8 |
| DISCHARGE_SUMMARY.attending_physician | 100.0% | 8 |
| DISCHARGE_SUMMARY.discharge_date | 100.0% | 8 |
| DISCHARGE_SUMMARY.facility | 100.0% | 8 |
| DISCHARGE_SUMMARY.patient_dob | 75.0% | 8 |
| DISCHARGE_SUMMARY.patient_name | 100.0% | 8 |
| DISCHARGE_SUMMARY.primary_icd | 100.0% | 8 |
| ID_DOCUMENT.dob | 100.0% | 10 |
| ID_DOCUMENT.expiry_date | 100.0% | 10 |
| ID_DOCUMENT.name_on_id | 100.0% | 10 |
| ID_DOCUMENT.policy_number | 100.0% | 10 |
| PRESCRIPTION.dea_number | 100.0% | 8 |
| PRESCRIPTION.drugs | 100.0% | 10 |
| PRESCRIPTION.patient_dob | 100.0% | 10 |
| PRESCRIPTION.patient_name | 100.0% | 10 |
| PRESCRIPTION.prescriber | 100.0% | 10 |
| PRESCRIPTION.prescriber_npi | 100.0% | 10 |
| PRESCRIPTION.rx_date | 100.0% | 10 |

<details><summary>Field misses</summary>

- dc_PT_99733_hi.patient_dob: gt='02/28/1963' got='28/02/1963'
- dc_PT_69470_hi.patient_dob: gt='02/25/1976' got='25/02/1976'

</details>

#### Retrieval detail

Gold sections come from `eval/retrieval_gold.json`, built from the policy text (not retriever output).

#### Operations

- Cases: 14, documents: 40
- Case latency (cold path incl. LLM): p50 13.3s, p95 27.6s
- Cost without cache: $1.85 total, $0.132/case, $0.046/document. Spent this run: $1.02
- Cost by agent: classifier $0.22, extractor $0.82, policy $0.43, kyc_visual $0.03, fraud $0.28, justify $0.08
- LLM calls: 136 (72 served from cache); retries on Opus: {'extractor': 22, 'classifier': 15}
- Mean OCR grounding rate 68.4%; mean support rate (grounded or corroborated by the member database) 82.0%


---

## Spanish and Hindi, held-out members

_Generated 2026-10-05T16:06:06 by `make eval`. Prompts are tuned on the dev split only; held-out and seed-7 numbers are reported without tuning._

#### Rubric metrics

| Rubric criterion (weight) | Metric | Result |
|---|---|---|
| Classification (20%) | document-type accuracy | **100.0%** (40 docs) |
| Extraction (20%) | required claim fields correct (ICD, CPT, line amounts, total, NPI, provider) | **100.0%** (72 fields) |
| Policy retrieval (15%) | Recall@3 of the governing policy section per billed code / MRR | **100.0%** / 1.0 (26 queries) |
| Decision correctness (25%) | per-document decision accuracy, all labels | **95.0%** (40 docs) |
| | ... on labels visible in the pixels | **95.0%** (40 docs) |
| | case roll-up accuracy | 85.7% (14 cases) |

#### Decisions

Accuracy by true document type: CLAIM_FORM 83.3%, PRESCRIPTION 100.0%, ID_DOCUMENT 100.0%, DISCHARGE_SUMMARY 100.0%

Confusion (expected -> predicted): `APPROVE->APPROVE` 32, `APPROVE->ESCALATE` 2, `REJECT->REJECT` 6

**Fraud scenarios detected (per-document score >= 0.3):** none in split

False-positive fraud escalations on non-fraud documents: 3 (claim_PT_19116_es_expiredid score=0.7, claim_PT_19116_es_uncovered score=0.7, claim_PT_19116_hi_expiredid score=0.7)

**Edge cases handled as labelled:** expired_id 2/2, missing_fields 2/2, uncovered_procedure 2/2

<details><summary>Decision errors</summary>

- claim_PT_19116_es_expiredid: expected APPROVE got ESCALATE (R3_fraud_or_low_confidence) - fraud signal duplicate_claim (w=0.7): duplicate of claim_PT_19116_es (near-identical image)
- claim_PT_19116_hi_expiredid: expected APPROVE got ESCALATE (R3_fraud_or_low_confidence) - fraud signal duplicate_claim (w=0.7): duplicate of claim_PT_19116_hi (near-identical image)

</details>

#### Extraction detail

All scored fields across document types: **99.4%**. By type: CLAIM_FORM 100.0%, PRESCRIPTION 100.0%, ID_DOCUMENT 100.0%, DISCHARGE_SUMMARY 96.4%

| Field | Accuracy | n |
|---|---|---|
| CLAIM_FORM.attending_physician | 100.0% | 12 |
| CLAIM_FORM.billing_provider | 100.0% | 12 |
| CLAIM_FORM.claim_number | 100.0% | 12 |
| CLAIM_FORM.cpt_codes | 100.0% | 12 |
| CLAIM_FORM.icd_codes | 100.0% | 12 |
| CLAIM_FORM.line_charges | 100.0% | 12 |
| CLAIM_FORM.patient_dob | 100.0% | 12 |
| CLAIM_FORM.patient_name | 100.0% | 12 |
| CLAIM_FORM.policy_number | 100.0% | 12 |
| CLAIM_FORM.provider_npi | 100.0% | 12 |
| CLAIM_FORM.service_date | 100.0% | 12 |
| CLAIM_FORM.total_charge | 100.0% | 12 |
| DISCHARGE_SUMMARY.admit_date | 100.0% | 8 |
| DISCHARGE_SUMMARY.attending_physician | 100.0% | 8 |
| DISCHARGE_SUMMARY.discharge_date | 100.0% | 8 |
| DISCHARGE_SUMMARY.facility | 100.0% | 8 |
| DISCHARGE_SUMMARY.patient_dob | 75.0% | 8 |
| DISCHARGE_SUMMARY.patient_name | 100.0% | 8 |
| DISCHARGE_SUMMARY.primary_icd | 100.0% | 8 |
| ID_DOCUMENT.dob | 100.0% | 10 |
| ID_DOCUMENT.expiry_date | 100.0% | 10 |
| ID_DOCUMENT.name_on_id | 100.0% | 10 |
| ID_DOCUMENT.policy_number | 100.0% | 10 |
| PRESCRIPTION.dea_number | 100.0% | 8 |
| PRESCRIPTION.drugs | 100.0% | 10 |
| PRESCRIPTION.patient_dob | 100.0% | 10 |
| PRESCRIPTION.patient_name | 100.0% | 10 |
| PRESCRIPTION.prescriber | 100.0% | 10 |
| PRESCRIPTION.prescriber_npi | 100.0% | 10 |
| PRESCRIPTION.rx_date | 100.0% | 10 |

<details><summary>Field misses</summary>

- dc_PT_20322_hi.patient_dob: gt='03/17/1993' got='17/03/1993'
- dc_PT_39451_hi.patient_dob: gt='09/25/1993' got='25/09/1993'

</details>

#### Retrieval detail

Gold sections come from `eval/retrieval_gold.json`, built from the policy text (not retriever output).

#### Operations

- Cases: 14, documents: 40
- Case latency (cold path incl. LLM): p50 10.3s, p95 20.7s
- Cost without cache: $1.91 total, $0.137/case, $0.048/document. Spent this run: $0.94
- Cost by agent: classifier $0.24, extractor $0.85, policy $0.43, kyc_visual $0.03, fraud $0.28, justify $0.08
- LLM calls: 140 (78 served from cache); retries on Opus: {'extractor': 24, 'classifier': 15}
- Mean OCR grounding rate 66.7%; mean support rate (grounded or corroborated by the member database) 79.0%

