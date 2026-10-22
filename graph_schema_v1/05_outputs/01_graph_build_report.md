# Graph build report (schema v1.0.0)

Built 2026-10-21 19:14 from 15 claims and 1513 notes.

**5,856 nodes, 23,326 relationships, 2,491 claim events. Schema violations: 0.**

## Nodes by label

| Label | Count |
|---|---|
| Claim | 15 |
| Claimant | 15 |
| Employer | 12 |
| Carrier | 8 |
| County | 9 |
| IncidentLocation | 15 |
| InjuryNature | 5 |
| BodyPart | 21 |
| InjuryCause | 10 |
| ClaimsStaff | 16 |
| EmployerContact | 30 |
| HealthcareFacility | 21 |
| Clinician | 28 |
| Attorney | 5 |
| Diagnosis | 15 |
| Treatment | 10 |
| Medication | 6 |
| Note | 1513 |
| Chunk | 1560 |
| Document | 19 |
| ClaimEvent | 2491 |
| ProcessStep | 18 |
| Form | 7 |
| Role | 7 |

## Relationships by type

| Type | Count |
|---|---|
| FILED_BY | 15 |
| HAS_EMPLOYER | 15 |
| INSURED_BY | 15 |
| OCCURRED_IN_COUNTY | 15 |
| OCCURRED_AT | 15 |
| LOCATED_IN | 15 |
| HAS_INJURY_NATURE | 15 |
| HAS_BODY_PART | 15 |
| HAS_CAUSE | 15 |
| HANDLED_BY | 67 |
| HAS_EMPLOYER_CONTACT | 30 |
| WORKS_FOR | 30 |
| TREATED_AT | 52 |
| SEEN_BY | 28 |
| PRACTICES_AT | 24 |
| REPRESENTED_BY | 5 |
| HAS_DIAGNOSIS | 15 |
| DIAGNOSIS_AFFECTS | 34 |
| HAS_NOTE | 1513 |
| NEXT_NOTE | 1498 |
| WRITTEN_BY | 1513 |
| CONTAINS_MESSAGE_FROM | 239 |
| CORRECTS | 19 |
| DUPLICATES | 5 |
| HAS_CHUNK | 1560 |
| NEXT_CHUNK | 47 |
| MENTIONS | 4195 |
| HAS_EVENT | 2491 |
| EVIDENCED_BY | 3790 |
| NEXT_EVENT | 2476 |
| INVOLVES | 2053 |
| ABOUT_DIAGNOSIS | 43 |
| INCLUDES_TREATMENT | 348 |
| RECORDS_MEDICATION | 29 |
| REFERENCES_FORM | 282 |
| INSTANCE_OF | 698 |
| CONFLICTS_WITH | 42 |
| DESCRIBED_IN | 23 |
| PERFORMED_BY | 18 |
| USES_FORM | 6 |
| PRECEDES | 7 |
| COVERS_BODY_PART | 11 |

## Review status of relationships

| Status | Count | Meaning |
|---|---|---|
| unreviewed | 13710 | extracted from note text by rules; audit a sample |
| approved | 8853 | deterministic, from structured columns or note headers |
| draft | 763 | curated by us from public documents; needs team review |

## Claim events by type

| Event type | Count |
|---|---|
| contact | 290 |
| file_review | 252 |
| work_status_update | 222 |
| paid_to_date_statement | 178 |
| pending_item | 133 |
| medical_visit | 96 |
| reserve_review | 93 |
| form_activity | 86 |
| therapy_visit | 85 |
| bill_review | 84 |
| bill_submitted | 80 |
| authorization_request | 80 |
| appointment_scheduled | 74 |
| contact_attempt | 72 |
| worker_message | 57 |
| mileage_reimbursement_request | 56 |
| pharmacy_review | 56 |
| light_duty_offer | 42 |
| status_report_sent | 38 |
| attorney_request | 37 |
| supervisor_direction | 30 |
| benefit_payment | 30 |
| authorization_decision | 26 |
| imaging_result | 24 |
| imaging_ordered | 24 |
| attendance_report | 22 |
| return_to_full_duty | 21 |
| claim_closed | 19 |
| injury_occurred | 16 |
| nurse_case_review | 16 |
| first_report_received | 15 |
| prior_claims_check | 15 |
| claimant_statement_taken | 15 |
| supervisor_statement_taken | 15 |
| compensability_decision | 15 |
| hearing_held | 15 |
| missed_appointment | 11 |
| injury_reported_to_employer | 10 |
| employer_reported_to_carrier | 7 |
| hearing_scheduled | 7 |
| wage_information | 7 |
| reopen_request | 7 |
| ime_report | 4 |
| ime_scheduled | 4 |
| permanency_evaluation | 2 |
| settlement_discussion | 2 |
| board_determination | 1 |

## Coverage: notes that produced at least one event

1509 of 1513 notes (99.7%). The rest are listed in `06_unmapped_notes_for_review.csv`.

| Note type | Notes | With an event | % |
|---|---|---|---|
| IME Note | 12 | 11 | 92% |
| Correction | 19 | 18 | 95% |
| Bill Question | 114 | 112 | 98% |
| First Report Summary | 15 | 15 | 100% |
| Diary Entry | 118 | 118 | 100% |
| Contact Attempt | 72 | 72 | 100% |
| Prior Claims Check | 15 | 15 | 100% |
| Contact - Injured Worker | 139 | 139 | 100% |
| Contact - Employer | 93 | 93 | 100% |
| Medical Update | 77 | 77 | 100% |
| Contact - Provider | 58 | 58 | 100% |
| Imaging Result | 28 | 28 | 100% |
| Work Status | 59 | 59 | 100% |
| Statement / Investigation | 15 | 15 | 100% |
| Supervisor Incident Statement | 15 | 15 | 100% |
| Compensability Review | 15 | 15 | 100% |
| Authorization | 47 | 47 | 100% |
| Worker Message | 57 | 57 | 100% |
| Hearing / Legal | 41 | 41 | 100% |
| Therapy Update | 85 | 85 | 100% |
| File Review | 134 | 134 | 100% |
| Reserve Review | 51 | 51 | 100% |
| Status Report | 38 | 38 | 100% |
| Supervisor Direction | 30 | 30 | 100% |
| Pharmacy | 56 | 56 | 100% |
| Closure / Reopen | 19 | 19 | 100% |
| Reopen Inquiry | 7 | 7 | 100% |
| Benefits Payment | 29 | 29 | 100% |
| Nurse Case Manager Note | 16 | 16 | 100% |
| Attorney Correspondence | 37 | 37 | 100% |
| Permanency / Settlement | 2 | 2 | 100% |

## Problems found in the data


### data issue (17)

- Claim 6977118: carrier 'POLICE, FIRE, SANITATION' looks like a self-insured employer, but the synthetic employer is 'Orange Supply Cooperative'
- Claim 6977144: carrier 'WEGMANS FOOD MARKETS, INC.' looks like a self-insured employer, but the synthetic employer is 'Riverside Food Services'
- Claim 6977182: carrier 'WEGMANS FOOD MARKETS, INC.' looks like a self-insured employer, but the synthetic employer is 'Hudson Valley Hospitality'
- Claim 6977197: carrier 'STARBUCKS CORPORATION' looks like a self-insured employer, but the synthetic employer is 'MetroClean Services'
- Claim 6977140: claimant first name 'Maya' is also the first name of claims staff on this claim; first-name mentions are not linked
- Claim 6977144: claimant first name 'Priya' is also the first name of claims staff on this claim; first-name mentions are not linked
- SYN-6977100-090: pasted email subject says claim 6977010, note is filed on claim 6977100
- SYN-6977137-077: pasted email subject says claim 9677137, note is filed on claim 6977137
- SYN-6977163-054: pasted email subject says claim 6977136, note is filed on claim 6977163
- SYN-6977175-006: pasted email subject says claim 6797175, note is filed on claim 6977175
- SYN-6977178-007: pasted email subject says claim 6971778, note is filed on claim 6977178
- SYN-6977178-048: pasted email subject says claim 6977187, note is filed on claim 6977178
- SYN-6977194-010: pasted email subject says claim 6797194, note is filed on claim 6977194
- SYN-6977194-022: pasted email subject says claim 6971794, note is filed on claim 6977194
- SYN-6977194-036: pasted email subject says claim 6977914, note is filed on claim 6977194
- SYN-6977194-042: pasted email subject says claim 6977149, note is filed on claim 6977194
- SYN-6977197-068: pasted email subject says claim 6971797, note is filed on claim 6977197

### ambiguous mention (2)

- Claim 6977140: 'Maya Patel' could be ['Claimant:CLMT-6977140', 'ClaimsStaff:STAFF-maya-patel']; not linked
- Claim 6977144: 'Priya Shah' could be ['Claimant:CLMT-6977144', 'ClaimsStaff:STAFF-priya-shah']; not linked

### fuzzy alias (4)

- Claim 6977144: claimant 'Priya Shah' also written as ['Priyo']
- Claim 6977175: claimant 'Caleb Ward' also written as ['Calebb']
- Claim 6977178: claimant 'Julian Bell' also written as ['Juliann']
- Claim 6977197: claimant 'Camila Morris' also written as ['Camilu']

### truncated note (7)

- SYN-6977100-098: ends with '...ack to full duty Reserves unchanged Will'
- SYN-6977121-049: ends with '...from Dr Lindqvist Dr Lindqvist wants Leo'
- SYN-6977121-081: ends with '... nothing new. Leo Morgan working regular'
- SYN-6977160-047: ends with '...t overtime coverage. Employer says Chloe'
- SYN-6977163-028: ends with '...ab Center called. Asked Dr Haddad for an'
- SYN-6977163-084: ends with '...6 diary - no change. Cx working reggular'
- SYN-6977175-089: ends with '...en at North Shore Occupational Health on'

### conflicts between events (42)
See `05_conflicts_found.csv`.

- claim 6977098: MRI_result_date (same result, two dates): 2026-02-02 vs 2026-02-01 (EV-6977098-imaging_result-c11ab858b2 / EV-6977098-imaging_result-61b1fe5775)
- claim 6977098: paid_to_date_decreased: 4500.0 vs 1360.0 (EV-6977098-paid_to_date_statement-0bcd6ffd24 / EV-6977098-paid_to_date_statement-f361d5811e)
- claim 6977098: hearing_outcome_2026-02-23: no agreement vs issue narrowed (EV-6977098-hearing_held-1fd91eca31 / EV-6977098-hearing_held-d8d5bd442a)
- claim 6977100: paid_to_date_decreased: 12000.0 vs 970.0 (EV-6977100-paid_to_date_statement-7ff0aa7fde / EV-6977100-paid_to_date_statement-6f8e7e72cd)
- claim 6977100: hearing_outcome_2026-01-09: issue narrowed vs no agreement (EV-6977100-hearing_held-4fcba51a3a / EV-6977100-hearing_held-1ed8c58057)
- claim 6977100: return_to_full_duty_date: 2026-02-10 vs 2026-03-23 (EV-6977100-return_to_full_duty-c5a7958d6b / EV-6977100-return_to_full_duty-cc007fdf2a)
- claim 6977118: paid_to_date_decreased: 22000.0 vs 12000.0 (EV-6977118-paid_to_date_statement-cfbb70973b / EV-6977118-paid_to_date_statement-4d3df74eba)
- claim 6977121: paid_to_date_decreased: 15000.0 vs 465.0 (EV-6977121-paid_to_date_statement-c07d3b6604 / EV-6977121-paid_to_date_statement-3c5bd591dc)
- claim 6977137: paid_to_date_decreased: 22000.0 vs 2628.0 (EV-6977137-paid_to_date_statement-55e30ec13d / EV-6977137-paid_to_date_statement-09b8a2da1f)
- claim 6977137: paid_to_date_decreased: 15000.0 vs 14454.0 (EV-6977137-paid_to_date_statement-4e5f1e7ea6 / EV-6977137-paid_to_date_statement-67aefc3d34)
- claim 6977137: paid_to_date_decreased: 14454.0 vs 6000.0 (EV-6977137-paid_to_date_statement-ab6f971593 / EV-6977137-paid_to_date_statement-61998a8453)
- claim 6977137: return_to_full_duty_date: 2026-05-11 vs 2026-05-18 (EV-6977137-return_to_full_duty-f4b861346b / EV-6977137-return_to_full_duty-3c0034dd4a)
- claim 6977140: paid_to_date_decreased: 8500.0 vs 815.0 (EV-6977140-paid_to_date_statement-850bf711ff / EV-6977140-paid_to_date_statement-b4d30f62be)
- claim 6977140: paid_to_date_decreased: 6000.0 vs 1470.0 (EV-6977140-paid_to_date_statement-dc6162f2d5 / EV-6977140-paid_to_date_statement-9abe96837d)
- claim 6977144: MRI_result_date (same result, two dates): 2026-02-09 vs 2026-02-07 (EV-6977144-imaging_result-cbb6ae58f4 / EV-6977144-imaging_result-d8ca7adc35)
- claim 6977144: paid_to_date_decreased: 4500.0 vs 1025.0 (EV-6977144-paid_to_date_statement-d55afab18f / EV-6977144-paid_to_date_statement-dacd08e23b)
- claim 6977144: paid_to_date_decreased: 4500.0 vs 1415.0 (EV-6977144-paid_to_date_statement-9067912e0b / EV-6977144-paid_to_date_statement-758795c704)
- claim 6977144: return_to_full_duty_date: 2026-02-22 vs 2026-03-18 (EV-6977144-return_to_full_duty-f667bf1928 / EV-6977144-return_to_full_duty-6ea402ec26)
- claim 6977156: MRI_result_date (same result, two dates): 2026-01-26 vs 2026-01-24 (EV-6977156-imaging_result-d8dd0bd84b / EV-6977156-imaging_result-2b82c112b3)
- claim 6977156: paid_to_date_decreased: 12000.0 vs 2840.0 (EV-6977156-paid_to_date_statement-803f661e75 / EV-6977156-paid_to_date_statement-7ce8feaf03)
- claim 6977156: paid_to_date_decreased: 17750.0 vs 4500.0 (EV-6977156-paid_to_date_statement-f33d2ce080 / EV-6977156-paid_to_date_statement-9aad3da771)
- claim 6977156: ime_report_dated_before_exam: 2026-03-05 vs 2026-02-20 (EV-6977156-ime_scheduled-86d41d4ed0 / EV-6977156-ime_report-fb80a0dd76)
- claim 6977156: hearing_outcome_2026-04-14: decision received vs judge reserved decision (EV-6977156-hearing_held-d57d29ebc3 / EV-6977156-hearing_held-4e2346e4c6)
- claim 6977156: return_to_full_duty_date: 2026-05-30 vs 2026-06-08 (EV-6977156-return_to_full_duty-60286bad0c / EV-6977156-return_to_full_duty-f2615327ac)
- claim 6977163: paid_to_date_decreased: 6000.0 vs 410.0 (EV-6977163-paid_to_date_statement-8734d5583f / EV-6977163-paid_to_date_statement-83187918c8)
- claim 6977163: paid_to_date_decreased: 6000.0 vs 410.0 (EV-6977163-paid_to_date_statement-84b03e5faf / EV-6977163-paid_to_date_statement-4ab1f3906b)
- claim 6977163: paid_to_date_decreased: 22000.0 vs 410.0 (EV-6977163-paid_to_date_statement-5ea7361b10 / EV-6977163-paid_to_date_statement-4c064750a3)
- claim 6977163: return_to_full_duty_date: 2025-12-11 vs 2025-12-09 (EV-6977163-return_to_full_duty-72b315f750 / EV-6977163-return_to_full_duty-c61306157d)
- claim 6977163: hearing_outcome_2026-03-31: decision received vs judge reserved decision (EV-6977163-hearing_held-b4ffb781f3 / EV-6977163-hearing_held-8b7e394c9a)
- claim 6977175: paid_to_date_decreased: 12000.0 vs 410.0 (EV-6977175-paid_to_date_statement-ca04e6d0e8 / EV-6977175-paid_to_date_statement-9241396179)
- claim 6977175: paid_to_date_decreased: 12000.0 vs 630.0 (EV-6977175-paid_to_date_statement-a726ea34a7 / EV-6977175-paid_to_date_statement-cbc77e9d73)
- claim 6977175: paid_to_date_decreased: 4500.0 vs 630.0 (EV-6977175-paid_to_date_statement-c051efbc2c / EV-6977175-paid_to_date_statement-4576909012)
- claim 6977182: date_of_injury: 2025-10-20 vs 2025-10-21 (EV-6977182-injury_occurred-1624661a8e / EV-6977182-injury_occurred-c4bb978c94)
- claim 6977182: paid_to_date_decreased: 22000.0 vs 630.0 (EV-6977182-paid_to_date_statement-d4d852c8ab / EV-6977182-paid_to_date_statement-5f19499c76)
- claim 6977182: paid_to_date_decreased: 8500.0 vs 630.0 (EV-6977182-paid_to_date_statement-1ba2c616b7 / EV-6977182-paid_to_date_statement-7b3d20a104)
- claim 6977194: paid_to_date_decreased: 6000.0 vs 760.0 (EV-6977194-paid_to_date_statement-011d46b25c / EV-6977194-paid_to_date_statement-9296268c60)
- claim 6977194: paid_to_date_decreased: 22000.0 vs 1415.0 (EV-6977194-paid_to_date_statement-4df5a73e24 / EV-6977194-paid_to_date_statement-44bac4b3b2)
- claim 6977197: paid_to_date_decreased: 15000.0 vs 620.0 (EV-6977197-paid_to_date_statement-17703b525d / EV-6977197-paid_to_date_statement-4c49fbcb5a)
- claim 6977197: paid_to_date_decreased: 22000.0 vs 1805.0 (EV-6977197-paid_to_date_statement-de72705613 / EV-6977197-paid_to_date_statement-4009d74538)
- claim 6977197: hearing_outcome_2026-04-19: decision received vs judge reserved decision (EV-6977197-hearing_held-41025e7322 / EV-6977197-hearing_held-daaf199c6e)
- claim 6977197: ime_report_dated_before_exam: 2026-03-09 vs 2026-02-25 (EV-6977197-ime_scheduled-28c7394092 / EV-6977197-ime_report-d48a27d5ad)
- claim 6977197: return_to_full_duty_date: 2026-03-06 vs 2026-04-22 (EV-6977197-return_to_full_duty-8aefa22367 / EV-6977197-return_to_full_duty-807a7dd211)

### same event, different values (8)

- EV-6977098-hearing_held-d8d5bd442a (hearing_held, claim 6977098): {"adjournment_reason": [{"value": "wage rate", "notes": ["SYN-6977098-058"]}, {"value": "medical bills", "notes": ["SYN-6977098-074", "SYN-6977098-082", "SYN-6977098-086", "SYN-6977098-103"]}]}
- EV-6977100-hearing_held-4fcba51a3a (hearing_held, claim 6977100): {"adjournment_reason": [{"value": "wage rate", "notes": ["SYN-6977100-065", "SYN-6977100-091", "SYN-6977100-100"]}, {"value": "medical bills", "notes": ["SYN-6977100-087"]}, {"value": "causation", "notes": ["SYN-6977100-108"]}]}
- EV-6977118-imaging_result-eb509a7fcc (imaging_result, claim 6977118): {"result_text": [{"value": "mild disc bulge l4-5, no stenosis radiologist says full report in 2 days", "notes": ["SYN-6977118-039"]}, {"value": "mild disc bulge l4-5, no stenosis", "notes": ["SYN-6977118-040", "SYN-6977118-056", "SYN-6977118-062", "SYN-6977118-073", "SYN-6977118-074", "SYN-6977118-0
- EV-6977156-ime_report-fb80a0dd76 (ime_report, claim 6977156): {"finding": [{"value": "supports a work-related injury, no ongoing disability", "notes": ["SYN-6977156-064", "SYN-6977156-083", "SYN-6977156-090", "SYN-6977156-103", "SYN-6977156-107"]}, {"value": "supports work-related injury, no ongoing disability", "notes": ["SYN-6977156-096"]}]}
- EV-6977156-hearing_held-8dfa88eead (hearing_held, claim 6977156): {"adjournment_reason": [{"value": "medical records", "notes": ["SYN-6977156-055"]}, {"value": "IME report", "notes": ["SYN-6977156-056"]}, {"value": "the attorney to submit position", "notes": ["SYN-6977156-064"]}, {"value": "wage info", "notes": ["SYN-6977156-066"]}]}
- EV-6977160-ime_report-423a97b095 (ime_report, claim 6977160): {"finding": [{"value": "says tx is reasonable and ongoing", "notes": ["SYN-6977160-061"]}, {"value": "tx is reasonable and ongoing", "notes": ["SYN-6977160-061", "SYN-6977160-084", "SYN-6977160-097", "SYN-6977160-106"]}, {"value": "treatment is reasonable and ongoing", "notes": ["SYN-6977160-082", "
- EV-6977163-hearing_held-c289c3f5dc (hearing_held, claim 6977163): {"adjournment_reason": [{"value": "medical records", "notes": ["SYN-6977163-057", "SYN-6977163-061", "SYN-6977163-080"]}, {"value": "IME report", "notes": ["SYN-6977163-058", "SYN-6977163-079"]}, {"value": "wage info", "notes": ["SYN-6977163-077"]}]}
- EV-6977197-hearing_held-9345ce33b7 (hearing_held, claim 6977197): {"adjournment_reason": [{"value": "the attorney to submit position", "notes": ["SYN-6977197-054"]}, {"value": "IME report", "notes": ["SYN-6977197-056", "SYN-6977197-066", "SYN-6977197-080"]}, {"value": "medical records", "notes": ["SYN-6977197-077"]}]}

## Notes

- NY claims file not given: wcio_code and *_record properties left empty (pass --ny-claims to fill them)
- merged year-less injury_occurred evidence 2025-05-01 into 2015-05-01 (claim 6977163)
