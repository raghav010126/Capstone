# Evaluation report: official / dev split

_Generated 2026-10-05T00:09:49 by `make eval`. Prompts are tuned on the dev split only; held-out and seed-7 numbers are reported without tuning._

## Rubric metrics

| Rubric criterion (weight) | Metric | Result |
|---|---|---|
| Classification (20%) | document-type accuracy | **100.0%** (77 docs) |
| Extraction (20%) | required claim fields correct (ICD, CPT, line amounts, total, NPI, provider) | **100.0%** (87 fields) |
| Policy retrieval (15%) | Recall@3 of the governing policy section per billed code / MRR | **100.0%** / 0.9884 (43 queries) |
| Decision correctness (25%) | per-document decision accuracy, all labels | **96.1%** (77 docs) |
| | ... on labels visible in the pixels | **100.0%** (74 docs) |
| | case roll-up accuracy | 82.3% (17 cases) |

## Decisions

Accuracy by true document type: ID_DOCUMENT 86.7%, CLAIM_FORM 93.3%, DISCHARGE_SUMMARY 100.0%, PRESCRIPTION 100.0%, POLICY_AMENDMENT 100.0%, UNKNOWN 100.0%

Confusion (expected -> predicted): `APPROVE->APPROVE` 62, `ESCALATE->APPROVE` 1, `ESCALATE->ESCALATE` 4, `REJECT->APPROVE` 2, `REJECT->REJECT` 8

**Fraud scenarios detected (per-document score >= 0.3):** amount_under_10k (not visible) 0/1, date_conflict 1/1, proc_diag_mismatch 1/1

False-positive fraud escalations on non-fraud documents: 0

**Edge cases handled as labelled:** expired_id 3/3, expiring_soon_id 2/2, missing_fields 3/3, tampered_id (not visible) 0/2, uncovered_procedure 2/2, unknown_document 2/2

<details><summary>Decision errors</summary>

- claim_PT_69470: expected ESCALATE got APPROVE (R4_default) [label not visible] - all checks passed
- id_PT_57795: expected REJECT got APPROVE (R4_default) [label not visible] - KYC warnings: id_layout_issues
- id_PT_74454: expected REJECT got APPROVE (R4_default) [label not visible] - KYC warnings: id_layout_issues

</details>

## Extraction detail

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

## Retrieval detail

Gold sections come from `eval/retrieval_gold.json`, built from the policy text (not retriever output).

## Operations

- Cases: 17, documents: 77
- Case latency (cold path incl. LLM): p50 18.3s, p95 26.9s
- Cost without cache: $2.67 total, $0.157/case, $0.035/document. Spent this run: $0.65
- Cost by agent: classifier $0.52, extractor $0.86, kyc_visual $0.15, policy $0.60, fraud $0.41, justify $0.12
- LLM calls: 223 (195 served from cache); retries on Opus: {'extractor': 3, 'kyc_visual': 3, 'classifier': 1}
- Mean OCR grounding rate 97.9%; mean support rate (grounded or corroborated by the member database) 98.5%

