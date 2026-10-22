# Schema coverage checklist: every kind of fact in the 15-claim notes, and where it lives

**Why this file exists.** The sponsor asked us not to miss any entity or relationship. This list was built by reading two claims end to end (6977160: 121 notes; 6977163: 103 notes), sampling every one of the 31 note types across all 15 claims, and then checking the builder's output: **1,509 of 1,513 notes (99.7%)** produce at least one claim event. The 4 that do not are listed in `05_outputs/06_unmapped_notes_for_review.csv`: 2 bill notes cut off mid-sentence, 1 "IME update" that names no exam date or doctor, and 1 correction ("it is right forearm, not left") that is stored as a `CORRECTS` link rather than an event.

Status: **Node** = its own entity; **Edge** = a relationship; **Property** = stored on a node or edge; **Text only** = kept in the note and chunk text but not structured (with the reason).

## A. Who is involved

| Fact in the notes | Example | Where in the schema | Status |
|---|---|---|---|
| Injured worker (also called cx, clmt, EE, IW, pt) | "Chloe Nguyen", "clmt" | `Claimant`; aliases include first name and misspellings ("Calebb", "Juliann") | Node |
| Employer | "City Operations Department" | `Employer` | Node |
| Employer HR / payroll person | "ER contact Frank Nakamura" | `EmployerContact` {contact_role: hr_payroll_contact} -WORKS_FOR-> `Employer` | Node + Edge |
| Worker's supervisor at the employer | "ER supervisor Ravi Brandt" | `EmployerContact` {contact_role: supervisor} | Node |
| Carrier / State Insurance Fund / self-insured employer | "SIF is on the risk" | `Carrier` with aliases | Node |
| Adjuster, assistant, claims supervisor, nurse case manager, pharmacy/benefits specialist | "Daniel Brooks", "-Jamal", "Susan Park RN", "Pam Whitfield" | `ClaimsStaff` -HANDLED_BY{role}- `Claim`; note author via `WRITTEN_BY` | Node + Edge |
| Treating doctor | "Dr Haddad" | `Clinician` {treating_physician} -PRACTICES_AT-> `HealthcareFacility` | Node + Edge |
| Physical therapist | "Dev Whitaker", "PT Lena Castillo at Lakeview PT" | `Clinician` {physical_therapist} | Node |
| IME / peer-review doctor | "IME with Dr Fischer" | `Clinician` {ime_examiner}, kept separate from treating doctors with the same surname | Node |
| Treating clinic, PT clinic, imaging center, pharmacy | "Northeast Diagnostic Imaging", "Harbor Drug" | `HealthcareFacility` {facility_type}; `Claim` -TREATED_AT{service}-> | Node + Edge |
| Claimant's attorney | "Alicia Romano is the worker's attorney" | `Attorney` -REPRESENTED_BY- `Claim` | Node + Edge |
| Who actually wrote a pasted email, text or voicemail | "From: Alicia Romano <...>" inside an adjuster's note | `Note` -CONTAINS_MESSAGE_FROM-> sender | Edge |
| Clinic front-desk staff (first names only) | "Kevin (front desk)" | `CONTAINS_MESSAGE_FROM`.sender_display; the edge points to the clinic | Property (only a first name is given) |
| Status-report recipient (first name only) | "Hi Mei," | `ClaimEvent{status_report_sent}`.recipient_first_name | Property (only a first name) |
| Workers' Compensation Board, law judge | "hearing before the judge" | `Role` nodes; hearings are events | Node (role) |

## B. The injury and medical care

| Fact | Example | Where | Status |
|---|---|---|---|
| Date of injury, how it happened | "DOI Dec 27, clmt backed work van into bollard" | `ClaimEvent{injury_occurred}` (date_of_injury, mechanism) | Node |
| Record categories: nature, body part, cause, county, location | "STRAIN OR TEAR", "MULTIPLE" | `InjuryNature`, `BodyPart{wcio}`, `InjuryCause`, `County`, `IncidentLocation` | Node |
| Diagnosis in the notes, with side | "strain of the low back, hip and both knees" | `Diagnosis` -DIAGNOSIS_AFFECTS{laterality}-> `BodyPart{specific}` | Node + Edge |
| Doctor visits: pain score, exam, assessment, plan, work status, restrictions, next visit | "OFFICE NOTE 12/29/25 (Dr Haddad): SUBJECTIVE..." | `ClaimEvent{medical_visit}` | Node |
| PT sessions: visit n of m, pain before/after, late arrival | "PT visit 2/6 (Riverbend PT)" | `ClaimEvent{therapy_visit}` | Node |
| Imaging ordered and results | "MRI ordered January 7, result January 18: mild disc bulge L4-5" | `ClaimEvent{imaging_ordered}`, `{imaging_result}` | Node |
| Treatments | PT, home exercise program, ice, splint | `Treatment` <-INCLUDES_TREATMENT- event | Node + Edge |
| Medications | Tylenol, naproxen, Flexeril | `Medication` <-RECORDS_MEDICATION- event | Node + Edge |
| Nurse case manager review, barrier to return to work | "Barrier to RTW: Transportation" | `ClaimEvent{nurse_case_review}` | Node |
| Appointments, missed appointments | "next appt 12/14", "no showed the last appt" | `{appointment_scheduled}`, `{missed_appointment}` | Node |
| MMI and permanency rating | "MMI reached, rating pending" | `{permanency_evaluation}` | Node |
| Range of motion, strength grades | "ROM: lumbar flexion limited" | `medical_visit`.findings | Property (one claim, no traversal value) |

## C. Money, authorization and bills

| Fact | Example | Where | Status |
|---|---|---|---|
| Average weekly wage from payroll | "earned about $690 a week" | `{wage_information}` | Node |
| Weekly benefit payments, late checks, direct deposit | "Paid $657.00/wk thru 01JAN26" | `{benefit_payment}` | Node |
| Reserves and authority requests | "med reserve $6,000", "requested more authority" | `{reserve_review}` | Node |
| Total paid to date | "approx $520 paid to date" | `{paid_to_date_statement}`; a decrease is flagged as a conflict | Node |
| Treatment authorization request and decision | "We are requesting 6 PT visits", "approved 6 PT visits, auth # 44790" | `{authorization_request}`, `{authorization_decision}` | Node |
| Variance request (Form MG-2) | "MG-2 rec'd for low back, reviewing" | `{authorization_request}` -REFERENCES_FORM-> `Form MG-2` -INSTANCE_OF-> PS09 | Node + Edge |
| Provider bills and bill review results | "PT visits $87.50 denied - no auth on file", "pended for records" | `{bill_submitted}`, `{bill_review}` | Node |
| Pharmacy network and refill checks | "PPO pharmacy network rule explained" | `{pharmacy_review}` | Node |
| Mileage reimbursement (Form C-257) | "told to send C-257 with receipts" | `{mileage_reimbursement_request}` -INSTANCE_OF-> PS10 | Node + Edge |
| IME fee | "IME fee $22,000" | `ime_report`.fee | Property. **The values ($8,500 to $22,000) match the reserve amounts, not realistic IME fees; likely a generator error.** |

## D. Work status and return to work

| Fact | Example | Where | Status |
|---|---|---|---|
| Work status and restrictions over time | "No lifting over 10 lbs, no repeated bending" | `{work_status_update}` (one per note, so changes over time are kept) | Node |
| Return to full duty date | "Back to full duty from February 18" | `{return_to_full_duty}`; different dates become `CONFLICTS_WITH` | Node + Edge |
| Light or modified duty offer | "We can offer light duty starting Nov 30, 4 hrs/day" | `{light_duty_offer}` | Node |
| Missed days, lateness, called out | "missed 9 days last month" | `{attendance_report}` | Node |

## E. Disputes, legal and Board

| Fact | Example | Where | Status |
|---|---|---|---|
| Accept or dispute decision (Form C-7), late notice | "Disputing for now ... C-7 sent to the Board" | `{compensability_decision}` -INSTANCE_OF-> PS05 | Node |
| Recorded statements (worker, supervisor), witnesses | "Statement from Chloe Nguyen" | `{claimant_statement_taken}`, `{supervisor_statement_taken}` | Node |
| Prior claims search | "prior claims search done, no hits" | `{prior_claims_check}` | Node |
| Hearing or conciliation scheduled | "Next hearing is on November 10" | `{hearing_scheduled}` | Node |
| Hearing held, outcome, adjournment reason | "Hearing held February 20, adjourned for medical records" | `{hearing_held}`; different outcomes for the same date become `CONFLICTS_WITH` | Node + Edge |
| Board administrative determination | "Admin determination notice rec'd 1/22/26" | `{board_determination}` | Node |
| IME scheduled and report | "IME report in: Says tx is reasonable and ongoing" | `{ime_scheduled}`, `{ime_report}` | Node |
| Attorney requests (records, payment, authorization, hearing threat) | "We will be asking for a hearing if there is no response within 10 days" | `{attorney_request}` | Node |
| Section 32 settlement, Medicare check | "need Medicare status check before any Section 32" | `{settlement_discussion}` -INSTANCE_OF-> PS14, PS15 | Node |
| WCB forms sent, received, requested | C-3, C-2F, C-4.2, C-7, C-257, MG-2, RFA-1 | `Form` <-REFERENCES_FORM{action}- event | Node + Edge |

## F. File handling, communication and data quality

| Fact | Example | Where | Status |
|---|---|---|---|
| Calls, emails, failed attempts | "tried clmt again, VM full" | `{contact}`, `{contact_attempt}` | Node |
| Worker messages and concerns | "nobody called me back abt MRI report" | `{worker_message}`.concerns | Node |
| Supervisor instructions and due dates | "need hearing prep done by 08/24/2026" | `{supervisor_direction}` | Node |
| Diary checks and file reviews (claim status as the adjuster states it, next review date) | "File review January 9 ... claim is open, hearing coming up" | `{file_review}` | Node |
| Things the file is waiting for | "Still waiting on wage statement" | `{pending_item}` | Node |
| Closing and reopening | "Closing note", "says ears flared up again" | `{claim_closed}`, `{reopen_request}` | Node |
| A note correcting an earlier note | "Correction to my December 11 note - next appt is 12/12, not 12/14" | `Note` -CORRECTS{wrong_value, right_value}-> `Note`; the wrong event is marked superseded | Edge |
| Duplicate notes | identical text twice | `Note` -DUPLICATES-> `Note` | Edge |
| Copied history paragraphs | "DOI December 9, Chloe was hit..." repeated in later notes | `EVIDENCED_BY.evidence_kind = restated`; `ClaimEvent.support` | Property |
| Cut-off notes | "Employer says Chloe" | `Note.looks_truncated` | Property |
| Wrong claim number in a pasted email | "Subject: RE: Claim 6977136" on claim 6977163 | build report, data issues | Logged |

## G. Deliberately not modeled (and why)

| Fact | Why not |
|---|---|
| Phone, address, "address confirmed same as file" | Personal data with no question value; stays in text. |
| Camera / safety review remarks | One-off remarks; stay in text and chunk search. |
| Claim tier | The sponsor mentioned tiers, but the notes file has no tier field. Add a `Claim.tier` property when the team defines tiers. |
| Industry (NAICS) | Not in the notes file. v0 had an `Industry` node from the NY public file; v1 stores `industry_code_record` on `Claim` when `--ny-claims` is given. |
| WCIO codes | Not in the notes file. Filled from the NY file with `--ny-claims`; until then vocabulary nodes are keyed by name. |
| Note type as an event | The note type is metadata (`Note.note_type`), not a fact: the generator README says note type is "kept as metadata only". |
