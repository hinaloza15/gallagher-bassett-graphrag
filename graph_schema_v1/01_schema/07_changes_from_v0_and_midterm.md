# What changed: v0 (Oct 6) and midterm (Oct 12) to v1 (Oct 21)

| | v0 | Midterm slides | v1 (this folder) |
|---|---|---|---|
| Data | 34 claims, 102 short synthetic notes, 7 public WCB documents | Sample of the new noisy notes | 15 claims, 1,513 noisy notes (92 to 121 per claim), 19 public WCB documents listed |
| Node labels | 18 | 17 | **24** |
| Relationship types | 27 | 26 | **42** |
| Layers | 4 | 4 | **6** |
| Events | Reserved, empty | ClaimEvent introduced | **47 event types**, 2,491 events extracted, every one linked to the notes that support it |
| Tested on real data | Demo data, 6 test questions (Python) | No | **15 test questions run as Cypher** in an embedded graph database, plus a coverage check of every note |

## Entities

| v0 / midterm | v1 | Why |
|---|---|---|
| Claim, Claimant, Employer, Carrier, County | Same | Unchanged |
| Location | `IncidentLocation` | Clearer name |
| Injury | `InjuryNature` | It is the WCIO nature of injury, not a single injury |
| BodyPart | `BodyPart` with `granularity` = wcio or specific | The record says "MULTIPLE"; the notes say "low back, hip and both knees". Both are needed |
| InjuryCause | Same | |
| Industry | Property `industry_code_record` on Claim | Not in the new notes file; filled from the NY file when given |
| Adjuster (v0), Staff (midterm) | `ClaimsStaff` with roles | Adjusters, assistants, supervisors, nurse case managers and specialists all write notes |
| Provider | Split into `HealthcareFacility` and `Clinician` | Notes name both the clinic and the doctor; one doctor surname appears at several clinics, and PT clinics, imaging centers and pharmacies are separate places |
| Attorney (midterm) | `Attorney` | Kept |
| (missing) | **`EmployerContact`** | HR/payroll people and supervisors appear in almost every claim (e.g. "ER contact Frank Nakamura") |
| (missing) | **`Diagnosis`, `Treatment`, `Medication`** | Needed for medical and guideline questions |
| Note (midterm), Document (v0) | `Note` for claim notes, `Document` for public documents | Different sources with different properties |
| Chunk | Same | |
| ClaimEvent | Same label, now with 47 typed events (`04_claim_event_types.csv`) | The core of the new data |
| ProcessStep, Form, Role | Same; 18 steps, 7 forms, 7 roles with quotes from WCB pages | Rebuilt for the forms that actually appear in the notes (C-257, MG-2, C-7, RFA-1...) |

## Relationships added in v1

`HAS_EMPLOYER_CONTACT`, `WORKS_FOR`, `TREATED_AT` (with service type), `SEEN_BY` (with role), `PRACTICES_AT`, `HAS_DIAGNOSIS`, `DIAGNOSIS_AFFECTS`, `CONTAINS_MESSAGE_FROM` (who really wrote a pasted email), `CORRECTS`, `DUPLICATES`, `EVIDENCED_BY` (with evidence kind and the exact quote), `INVOLVES`, `ABOUT_DIAGNOSIS`, `INCLUDES_TREATMENT`, `RECORDS_MEDICATION`, `REFERENCES_FORM`, `INSTANCE_OF`, `CONFLICTS_WITH`, `COVERS_BODY_PART`.

## Relationships removed or renamed

| Old | New | Why |
|---|---|---|
| `INVOLVES_EMPLOYER` | `HAS_EMPLOYER` | Plain name |
| `HANDLED_BY` (Claim to Adjuster) | `HANDLED_BY` (Claim to ClaimsStaff, property `role`) | More roles |
| `TREATED_BY` | `SEEN_BY` + `TREATED_AT` | Doctor and facility are separate |
| `HAS_INJURY`, `AFFECTS_BODY_PART`, `CAUSED_BY` | `HAS_INJURY_NATURE`, `HAS_BODY_PART`, `HAS_CAUSE` | Names match the renamed labels; `AFFECTS` is now reserved for diagnoses (`DIAGNOSIS_AFFECTS`) |
| `OCCURRED_IN`, `IN_COUNTY` | `OCCURRED_IN_COUNTY`, `LOCATED_IN` | Says what the target is |
| `IN_INDUSTRY` | property on Claim | No Industry node in v1 |
| `ABOUT_CLAIM` | `HAS_NOTE` | Direction from claim to note, like the other claim links |
| `HAS_EVENT, DEPENDS_ON, EVENT_PRECEDES, DELAYS, ESCALATES_TO, INVOLVES_ROLE` (reserved) | `HAS_EVENT`, `NEXT_EVENT`, `INVOLVES`, `CONFLICTS_WITH` | The notes describe what happened and when; they do not state that one event delayed or caused another. Causal links were left out because no note supports them |

## Design rules: what stayed, what is new

Kept from v0: fixed list of labels and relationships; node only if shared or traversed; keys are IDs, never names; provenance on every relationship; facts stay inside their claim; a missing value makes no edge.

New in v1:
1. **Never overwrite a disagreement.** Two different values for a one-value fact become two events linked by `CONFLICTS_WITH`. A correction note marks which one is wrong.
2. **First-hand versus copied.** Every piece of evidence is tagged `primary` (the note's own entry), `summary` (status report or file review) or `restated` (copied history paragraph). An event supported only by copied text is marked `restated_only`.
3. **Same name is not the same person.** People are keyed by name plus organization and role. Ambiguous mentions are logged, not guessed.
