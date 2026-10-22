# Schema test questions and answers

Graph loaded into Kuzu (embedded Cypher database): 5,856 nodes and 23,326 relationships (build files: 5,856 and 23,326). Every query below was executed; the tables are the real results.

**Keep this file out of both retrieval indexes.** It contains reference answers.

Classes follow 10_Stack_and_Evaluation_Proposal. Level 1 = simple lookup, 2 = needs a second hop or a rule, 3 = several hops or entity resolution, 4 = conflicting or unanswerable. Questions avoid claims 6977163, 6977175 and 6977178 where possible, because those are in the pilot evaluation set (20_Eval_Questions_Pilot_3_Claims).

| ID | Level | Class | Question |
|---|---|---|---|
| Q01 | 1 | Direct | Who is the treating doctor on claim 6977160, at which clinic, and which carrier insures the claim? |
| Q02 | 1 | Direct | Which claims have a claimant attorney, and who is the attorney on each? |
| Q03 | 1 | Terminology / alias | Adjusters write the carrier as 'SIF' or 'State Ins Fund'. Which claims are insured by the State Insurance Fund, and how is the carrier written in their notes? |
| Q04 | 2 | Terminology / alias | The claim record lists the body part as 'MULTIPLE' on six claims. Which body parts do the notes actually name for those claims? |
| Q05 | 2 | Cross-document | Which New York Medical Treatment Guidelines cover the body parts injured on claim 6977160? |
| Q06 | 2 | Cross-document | Claim 6977137 is a lost-time claim. Does the weekly payment match the NY rule that benefits are two-thirds of the average weekly wage? |
| Q07 | 2 | Unanswerable | What did the independent medical examination (IME) find on claim 6977121? |
| Q08 | 2 | Conflicting (resolved by a correction) | What is the date of injury on claim 6977182? |
| Q09 | 3 | Terminology / alias (name collision) | 'Dr Fischer' appears on three claims. Is it the same doctor? |
| Q10 | 3 | Multi-hop | Which claims did the adjuster dispute, did those claims go to a Board hearing or conciliation, and who represented the worker? |
| Q11 | 3 | Multi-hop | On claim 6977160, which bills were denied because no authorization was on file, and what does the file record about authorization? |
| Q12 | 3 | Multi-hop (name collision across claims) | Carla Brennan and Paula Nakamura each appear on two claims. Are they the same person in the same role each time? |
| Q13 | 4 | Conflicting | When did Chloe Nguyen (claim 6977160) go back to full duty? |
| Q14 | 4 | Conflicting / unanswerable | Was a second Board hearing held on claim 6977160 on April 11, 2026? |
| Q15 | 4 | Conflicting | What was the outcome of the April 14, 2026 hearing on claim 6977156? |

---

## Q01 (level 1, Direct)

**Question.** Who is the treating doctor on claim 6977160, at which clinic, and which carrier insures the claim?

**Schema path used.** Claim -SEEN_BY{treating_physician}-> Clinician -PRACTICES_AT-> HealthcareFacility; Claim -INSURED_BY-> Carrier

**Cypher 1.**

```cypher
MATCH (c:Claim {claim_id:'6977160'})-[s:SEEN_BY]->(d:Clinician)-[:PRACTICES_AT]->(f:HealthcareFacility),
      (c)-[:INSURED_BY]->(car:Carrier)
WHERE s.role = 'treating_physician'
RETURN d.name AS doctor, f.name AS clinic, car.name AS carrier
```

**Result 1** (1 rows):

| doctor    | clinic                           | carrier              |
|:----------|:---------------------------------|:---------------------|
| Dr Haddad | Upstate Hearing & Balance Center | STATE INSURANCE FUND |

**Reference answer (written from the notes).** Dr Haddad at Upstate Hearing & Balance Center; the carrier is the State Insurance Fund (written 'SIF' in many notes).

**Evidence.** SYN-6977160-010 (Dr Haddad's first office note), SYN-6977160-039 (status report: 'treating Dr Haddad', 'State Insurance Fund on the risk')


---

## Q02 (level 1, Direct)

**Question.** Which claims have a claimant attorney, and who is the attorney on each?

**Schema path used.** Claim -REPRESENTED_BY-> Attorney

**Cypher 1.**

```cypher
MATCH (c:Claim)-[:REPRESENTED_BY]->(a:Attorney)
RETURN c.claim_id AS claim, c.claimant_name AS claimant, a.name AS attorney, a.firm_email_domain AS firm_domain
ORDER BY claim
```

**Result 1** (5 rows):

|   claim | claimant      | attorney      | firm_domain         |
|--------:|:--------------|:--------------|:--------------------|
| 6977156 | Emma Rivera   | Lena Alvarez  | alvarezlaw.example  |
| 6977160 | Chloe Nguyen  | Alicia Romano | romanolaw.example   |
| 6977163 | Mia Lopez     | Lena Castillo | castillolaw.example |
| 6977175 | Caleb Ward    | Victor Brandt | brandtlaw.example   |
| 6977197 | Camila Morris | Carla Brennan | brennanlaw.example  |

**Reference answer (written from the notes).** Five claims: 6977156 Lena Alvarez, 6977160 Alicia Romano, 6977163 Lena Castillo, 6977175 Victor Brandt, 6977197 Carla Brennan. The other ten claims name no attorney.

**Evidence.** 'X is the worker's attorney' in copied history, and attorney emails from *law.example addresses (e.g. SYN-6977160-070)


---

## Q03 (level 1, Terminology / alias)

**Question.** Adjusters write the carrier as 'SIF' or 'State Ins Fund'. Which claims are insured by the State Insurance Fund, and how is the carrier written in their notes?

**Schema path used.** Claim -INSURED_BY-> Carrier <-MENTIONS{matched_text}- Chunk

**Cypher 1.**

```cypher
MATCH (c:Claim)-[:INSURED_BY]->(car:Carrier {carrier_id:'CAR-state-insurance-fund'})
OPTIONAL MATCH (c)-[:HAS_NOTE]->(:Note)-[:HAS_CHUNK]->(:Chunk)-[m:MENTIONS]->(car)
RETURN c.claim_id AS claim, collect(DISTINCT m.matched_text) AS written_as
ORDER BY claim
```

**Result 1** (7 rows):

|   claim | written_as                                        |
|--------:|:--------------------------------------------------|
| 6977098 | ['State Ins Fund', 'SIF', 'State Insurance Fund'] |
| 6977137 | ['SIF', 'State Insurance Fund', 'State Ins Fund'] |
| 6977140 | ['State Insurance Fund', 'SIF', 'State Ins Fund'] |
| 6977156 | ['SIF', 'State Ins Fund', 'State Insurance Fund'] |
| 6977160 | ['State Insurance Fund', 'State Ins Fund', 'SIF'] |
| 6977175 | ['State Insurance Fund', 'SIF', 'State Ins Fund'] |
| 6977194 | ['State Insurance Fund', 'State Ins Fund', 'SIF'] |

**Reference answer (written from the notes).** Seven claims: 6977098, 6977137, 6977140, 6977156, 6977160, 6977175, 6977194. The notes use 'SIF', 'State Ins Fund', 'State Insurance Fund' and the record's upper-case 'STATE INSURANCE FUND'. A keyword search for 'State Insurance Fund' alone would miss the notes that only say 'SIF'.

**Evidence.** Carrier (source) column; for example SYN-6977160-005 ('SIF is on the risk') and SYN-6977160-045 ('Copy to State Ins Fund')


---

## Q04 (level 2, Terminology / alias)

**Question.** The claim record lists the body part as 'MULTIPLE' on six claims. Which body parts do the notes actually name for those claims?

**Schema path used.** Claim -HAS_BODY_PART-> BodyPart{wcio}; Claim -HAS_DIAGNOSIS-> Diagnosis -DIAGNOSIS_AFFECTS-> BodyPart{specific}

**Cypher 1.**

```cypher
MATCH (c:Claim)-[:HAS_BODY_PART]->(:BodyPart {name:'MULTIPLE'})
MATCH (c)-[:HAS_DIAGNOSIS]->(d:Diagnosis)-[r:DIAGNOSIS_AFFECTS]->(b:BodyPart)
RETURN c.claim_id AS claim, d.text AS diagnosis, collect(DISTINCT b.name) AS body_parts_in_notes
ORDER BY claim
```

**Result 1** (6 rows):

|   claim | diagnosis                                   | body_parts_in_notes          |
|--------:|:--------------------------------------------|:-----------------------------|
| 6977118 | sprain of the low back and both shoulders   | ['low back', 'shoulder']     |
| 6977121 | strain of the neck, upper back and shoulder | ['back', 'neck', 'shoulder'] |
| 6977144 | contusion of the neck and low back          | ['low back', 'neck']         |
| 6977156 | strain of the low back, hip and both knees  | ['hip', 'knee', 'low back']  |
| 6977160 | strain of the low back, hip and both knees  | ['hip', 'knee', 'low back']  |
| 6977175 | strain of the neck, back and wrists         | ['back', 'neck', 'wrist']    |

**Reference answer (written from the notes).** 6977118 low back and both shoulders; 6977121 neck (some notes add upper back and shoulder); 6977144 neck and low back; 6977156 low back, hip and both knees; 6977160 low back, hip and both knees; 6977175 neck, back and both wrists.

**Evidence.** 'dx ...' phrases in first reports and copied history, e.g. SYN-6977160-014, SYN-6977118-013


---

## Q05 (level 2, Cross-document)

**Question.** Which New York Medical Treatment Guidelines cover the body parts injured on claim 6977160?

**Schema path used.** Claim -> Diagnosis -> BodyPart <-COVERS_BODY_PART- Document

**Cypher 1.**

```cypher
MATCH (c:Claim {claim_id:'6977160'})-[:HAS_DIAGNOSIS]->(:Diagnosis)-[:DIAGNOSIS_AFFECTS]->(b:BodyPart)
MATCH (doc:Document)-[g:COVERS_BODY_PART]->(b)
RETURN b.name AS body_part, doc.doc_id AS doc_id, doc.title AS guideline, g.mapping_status AS mapping_status
```

**Result 1** (3 rows):

| body_part   | doc_id   | guideline                                                     | mapping_status   |
|:------------|:---------|:--------------------------------------------------------------|:-----------------|
| knee        | RD14     | New York Knee Injury Medical Treatment Guidelines             | draft            |
| low back    | RD15     | New York Mid and Low Back Injury Medical Treatment Guidelines | draft            |
| hip         | RD19     | New York Hip and Groin Disorders Medical Treatment Guidelines | draft            |

**Reference answer (written from the notes).** Low back: Mid and Low Back Injury MTG (RD15). Hip: Hip and Groin Disorders MTG (RD19). Knees: Knee Injury MTG (RD14). The body-part-to-guideline map is a draft and needs team review.

**Evidence.** Diagnosis 'strain of the low back, hip and both knees' (SYN-6977160-024); 02_reference_data/02_body_part_to_treatment_guideline_map.csv; WCB guideline list page


---

## Q06 (level 2, Cross-document)

**Question.** Claim 6977137 is a lost-time claim. Does the weekly payment match the NY rule that benefits are two-thirds of the average weekly wage?

**Schema path used.** Claim -> ClaimEvent{wage_information}, ClaimEvent{benefit_payment}; ProcessStep -DESCRIBED_IN-> Document

**Cypher 1.**

```cypher
MATCH (c:Claim {claim_id:'6977137'})-[:HAS_EVENT]->(w:ClaimEvent {event_type:'wage_information'})
MATCH (c)-[:HAS_EVENT]->(p:ClaimEvent {event_type:'benefit_payment'})
WHERE p.weekly_rate IS NOT NULL
RETURN DISTINCT w.average_weekly_wage AS average_weekly_wage, p.weekly_rate AS weekly_rate,
       w.average_weekly_wage * 2.0 / 3.0 AS two_thirds_of_wage
```

**Result 1** (1 rows):

|   average_weekly_wage |   weekly_rate |   two_thirds_of_wage |
|----------------------:|--------------:|---------------------:|
|                   985 |           657 |               656.67 |

**Cypher 2.**

```cypher
MATCH (s:ProcessStep {step_id:'PS07'})-[d:DESCRIBED_IN]->(doc:Document)
RETURN s.name AS rule, s.rule_text AS quote, doc.title AS source
```

**Result 2** (1 rows):

| rule                                                    | quote                                                                                                              | source                          |
|:--------------------------------------------------------|:-------------------------------------------------------------------------------------------------------------------|:--------------------------------|
| Weekly benefit set at two-thirds of average weekly wage | To calculate your benefit, the Board uses two-thirds of your AWW and then adjusts it by your degree of disability. | Lost wage benefits (fact sheet) |

**Reference answer (written from the notes).** Yes. The employer reported a weekly wage of about $985; two-thirds of $985 is $656.67, and the ledger pays $657.00 a week. This assumes total disability; the rule also adjusts for degree of disability, which the notes do not state.

**Evidence.** SYN-6977137-006 (wage), SYN-6977137-016 ('Paid $657.00/wk'), RD05 lost wage benefits fact sheet (PS07)


---

## Q07 (level 2, Unanswerable)

**Question.** What did the independent medical examination (IME) find on claim 6977121?

**Schema path used.** absence of ClaimEvent{ime_*} and SEEN_BY{ime_examiner}

**Cypher 1.**

```cypher
MATCH (c:Claim {claim_id:'6977121'})
OPTIONAL MATCH (c)-[:HAS_EVENT]->(e:ClaimEvent)
WHERE e.event_type IN ['ime_scheduled', 'ime_report']
OPTIONAL MATCH (c)-[s:SEEN_BY]->(x:Clinician)
WHERE s.role = 'ime_examiner'
RETURN count(DISTINCT e) AS ime_events, count(DISTINCT x) AS ime_examiners
```

**Result 1** (1 rows):

|   ime_events |   ime_examiners |
|-------------:|----------------:|
|            0 |               0 |

**Reference answer (written from the notes).** Cannot be answered: no IME was scheduled or reported on claim 6977121. A correct system says so instead of borrowing an IME finding from another claim.

**Evidence.** No IME note or IME phrase in the 92 notes of claim 6977121


---

## Q08 (level 2, Conflicting (resolved by a correction))

**Question.** What is the date of injury on claim 6977182?

**Schema path used.** ClaimEvent{injury_occurred} -CONFLICTS_WITH-> ClaimEvent; Note -CORRECTS-> Note

**Cypher 1.**

```cypher
MATCH (c:Claim {claim_id:'6977182'})-[:HAS_EVENT]->(e:ClaimEvent {event_type:'injury_occurred'})
OPTIONAL MATCH (e)-[x:CONFLICTS_WITH]->(o:ClaimEvent)
RETURN e.event_date AS date_of_injury, e.evidence_count AS notes_supporting, x.resolution AS resolution
ORDER BY notes_supporting DESC
```

**Result 1** (2 rows):

| date_of_injury   |   notes_supporting | resolution                                             |
|:-----------------|-------------------:|:-------------------------------------------------------|
| 2025-10-20       |                 36 | value 2025-10-21 was corrected by note SYN-6977182-096 |
| 2025-10-21       |                  2 | nan                                                    |

**Cypher 2.**

```cypher
MATCH (fix:Note)-[r:CORRECTS]->(n:Note)
WHERE fix.claim_id = '6977182' AND r.corrected_fact = 'date of injury'
RETURN fix.note_id AS correction_note, fix.note_date AS written_on, n.note_id AS corrected_note, r.wrong_value AS wrong, r.right_value AS right
```

**Result 2** (1 rows):

| correction_note   | written_on   | corrected_note   | wrong      | right      |
|:------------------|:-------------|:-----------------|:-----------|:-----------|
| SYN-6977182-096   | 2026-08-04   | SYN-6977182-094  | 10/21/2025 | 10/20/2025 |

**Reference answer (written from the notes).** October 20, 2025. One note gave 10/21/2025; the adjuster's correction note SYN-6977182-096 says 'DOI is 10/20/2025 not 10/21/2025'.

**Evidence.** SYN-6977182-094 (wrong date), SYN-6977182-096 (correction), first report SYN-6977182-005


---

## Q09 (level 3, Terminology / alias (name collision))

**Question.** 'Dr Fischer' appears on three claims. Is it the same doctor?

**Schema path used.** Clinician keyed by surname + facility; IME examiners keyed separately

**Cypher 1.**

```cypher
MATCH (c:Claim)-[s:SEEN_BY]->(d:Clinician {name:'Dr Fischer'})
OPTIONAL MATCH (d)-[:PRACTICES_AT]->(f:HealthcareFacility)
RETURN d.clinician_id AS node, s.role AS role_on_claim, f.name AS facility, collect(DISTINCT c.claim_id) AS claims
```

**Result 1** (3 rows):

| node                                            | role_on_claim      | facility                           | claims      |
|:------------------------------------------------|:-------------------|:-----------------------------------|:------------|
| CLIN-fischer-north-shore-occupational-health    | treating_physician | North Shore Occupational Health    | ['6977098'] |
| CLIN-fischer-ime                                | ime_examiner       | nan                                | ['6977160'] |
| CLIN-fischer-capital-region-occupational-health | treating_physician | Capital Region Occupational Health | ['6977194'] |

**Reference answer (written from the notes).** The notes do not show that it is. Dr Fischer is the treating doctor at North Shore Occupational Health on 6977098, the treating doctor at Capital Region Occupational Health on 6977194, and the IME examiner on 6977160. Only a surname is given, so the graph keeps three separate nodes; merging them would invent a link. An IME examiner who also treats patients elsewhere is possible but unproven here.

**Evidence.** Headers 'Dr Fischer (treating provider)' on 6977098 and 6977194; SYN-6977160-043 ('IME sched February 20 with Dr Fischer')


---

## Q10 (level 3, Multi-hop)

**Question.** Which claims did the adjuster dispute, did those claims go to a Board hearing or conciliation, and who represented the worker?

**Schema path used.** Claim -> ClaimEvent{compensability_decision} ; Claim -> ClaimEvent{hearing_held} ; Claim -REPRESENTED_BY-> Attorney

**Cypher 1.**

```cypher
MATCH (c:Claim)-[:HAS_EVENT]->(d:ClaimEvent {event_type:'compensability_decision'})
WHERE d.decision = 'disputed'
OPTIONAL MATCH (c)-[:HAS_EVENT]->(h:ClaimEvent {event_type:'hearing_held'})
OPTIONAL MATCH (c)-[:REPRESENTED_BY]->(a:Attorney)
RETURN c.claim_id AS claim, d.event_date AS disputed_on, collect(DISTINCT h.event_date) AS hearing_dates,
       a.name AS attorney
ORDER BY claim
```

**Result 1** (6 rows):

|   claim | disputed_on   | hearing_dates                | attorney      |
|--------:|:--------------|:-----------------------------|:--------------|
| 6977098 | 2026-01-06    | ['2026-02-23']               | nan           |
| 6977100 | 2025-12-04    | ['2026-01-09']               | nan           |
| 6977156 | 2026-01-05    | ['2026-03-03', '2026-04-14'] | Lena Alvarez  |
| 6977160 | 2025-12-18    | ['2026-02-20', '2026-04-11'] | Alicia Romano |
| 6977163 | 2025-11-26    | ['2026-02-02', '2026-03-31'] | Lena Castillo |
| 6977197 | 2025-12-29    | ['2026-02-24', '2026-04-19'] | Carla Brennan |

**Reference answer (written from the notes).** Six claims were disputed (C-7 sent to the Board): 6977098 and 6977100 went to a conciliation conference with no attorney named; 6977156 (Lena Alvarez), 6977160 (Alicia Romano), 6977163 (Lena Castillo) and 6977197 (Carla Brennan) had Board hearings. 6977160 also has a 'second hearing April 11' that appears only in summaries (see Q14).

**Evidence.** Compensability Review notes, e.g. SYN-6977160-018; Hearing / Legal notes, e.g. SYN-6977160-050, SYN-6977098-058


---

## Q11 (level 3, Multi-hop)

**Question.** On claim 6977160, which bills were denied because no authorization was on file, and what does the file record about authorization?

**Schema path used.** Claim -> ClaimEvent{bill_review, authorization_*}

**Cypher 1.**

```cypher
MATCH (c:Claim {claim_id:'6977160'})-[:HAS_EVENT]->(b:ClaimEvent {event_type:'bill_review'})
WHERE b.decision = 'denied'
RETURN b.event_date AS reviewed_on, b.service AS service, b.amount AS amount, b.reason AS reason
ORDER BY reviewed_on
```

**Result 1** (4 rows):

| reviewed_on   | service   |   amount | reason          |
|:--------------|:----------|---------:|:----------------|
| 2026-03-20    | PT visits |    87.5  | no auth on file |
| 2026-04-27    | PT visits |   253    | no auth on file |
| 2026-05-22    | PT visits |   140.75 | no auth on file |
| 2026-09-17    | Rx        |   276    | no auth on file |

**Cypher 2.**

```cypher
MATCH (c:Claim {claim_id:'6977160'})-[:HAS_EVENT]->(a:ClaimEvent)
WHERE a.event_type IN ['authorization_request', 'authorization_decision'] OR (a.event_type = 'reserve_review' AND a.summary CONTAINS 'review')
RETURN a.event_date AS date, a.event_type AS event, a.service AS service, a.decision AS decision, a.summary AS summary
ORDER BY date
```

**Result 2** (14 rows):

| date       | event                  | service                            | decision   | summary                                                 |
|:-----------|:-----------------------|:-----------------------------------|:-----------|:--------------------------------------------------------|
| 2025-12-15 | authorization_request  | PT visits                          | nan        | Request for 6 PT visits                                 |
| 2025-12-15 | authorization_request  | office visit                       | nan        | Provider asks to confirm authorization for office visit |
| 2026-01-12 | reserve_review         | nan                                | nan        | Reserve review: reviewed                                |
| 2026-01-19 | authorization_request  | xray                               | nan        | Provider asks to confirm authorization for xray         |
| 2026-02-09 | authorization_request  | PT visits                          | nan        | Request for 6 PT visits                                 |
| 2026-04-01 | authorization_request  | treatment recommended by Dr Haddad | nan        | Attorney requests treatment authorization               |
| 2026-04-06 | authorization_request  | treatment recommended by Dr Haddad | nan        | Attorney requests treatment authorization               |
| 2026-06-22 | authorization_request  | treatment recommended by Dr Haddad | nan        | Attorney requests treatment authorization               |
| 2026-07-02 | reserve_review         | nan                                | nan        | Reserve review: increased                               |
| 2026-08-13 | authorization_request  | treatment recommended by Dr Haddad | nan        | Attorney requests treatment authorization               |
| 2026-09-02 | authorization_request  | treatment recommended by Dr Haddad | nan        | Attorney requests treatment authorization               |
| 2026-09-17 | authorization_decision | ortho consult                      | approved   | Auth 66080 for ortho consult                            |
| 2026-09-21 | reserve_review         | nan                                | nan        | Reserve review: more authority requested                |
| 2026-10-09 | authorization_request  | treatment recommended by Dr Haddad | nan        | Attorney requests treatment authorization               |

**Reference answer (written from the notes).** Denied for 'no auth on file': PT visits $87.50 (3/20/26), PT visits $253.00 (4/27/26), PT visits $140.75 (5/22/26) and an Rx bill $276 (9/17/26). The clinic asked for 6 PT visits on 12/15/25 and 2/9/26; the supervisor wrote 'ok to approve added PT' on 1/12/26; the only authorization number in the file is #66080, for an ortho consult (9/17/26). The clinic later says it 'rec'd our auth' (7/27/26, 9/2/26), and a PT bill of $447 was paid on 8/7/26. So the file never records a PT authorization decision, which explains the denials.

**Evidence.** SYN-6977160-016, -031, -042, -066, -083, -089, -099, -102, -113, -117


---

## Q12 (level 3, Multi-hop (name collision across claims))

**Question.** Carla Brennan and Paula Nakamura each appear on two claims. Are they the same person in the same role each time?

**Schema path used.** EmployerContact keyed by name + employer; Attorney keyed by name + firm

**Cypher 1.**

```cypher
MATCH (c:Claim)-[:HAS_EMPLOYER_CONTACT]->(p:EmployerContact)-[:WORKS_FOR]->(e:Employer)
WHERE p.name IN ['Carla Brennan', 'Paula Nakamura']
RETURN p.name AS name, 'employer contact' AS kind, p.contact_role AS role, e.name AS organization, c.claim_id AS claim
UNION ALL
MATCH (c:Claim)-[:REPRESENTED_BY]->(p:Attorney)
WHERE p.name IN ['Carla Brennan', 'Paula Nakamura']
RETURN p.name AS name, 'attorney' AS kind, 'claimant attorney' AS role, p.firm_email_domain AS organization, c.claim_id AS claim
```

**Result 1** (4 rows):

| name           | kind             | role               | organization              |   claim |
|:---------------|:-----------------|:-------------------|:--------------------------|--------:|
| Carla Brennan  | employer contact | supervisor         | Hudson Public Services    | 6977100 |
| Paula Nakamura | employer contact | hr_payroll_contact | Hudson Valley Hospitality | 6977182 |
| Paula Nakamura | employer contact | hr_payroll_contact | Riverside Food Services   | 6977144 |
| Carla Brennan  | attorney         | claimant attorney  | brennanlaw.example        | 6977197 |

**Reference answer (written from the notes).** No. Carla Brennan is the worker's supervisor at Hudson Public Services on 6977100 and the claimant's attorney (brennanlaw) on 6977197. Paula Nakamura is the HR/payroll contact at Hudson Valley Hospitality on 6977182 and at Riverside Food Services on 6977144. The graph keeps four separate nodes because the role or employer differs.

**Evidence.** SYN-6977100 supervisor statement header; SYN-6977197 attorney emails; employer emails from paula@hudsonvalleyhospitality.example and paula@riversidefoodservices.example


---

## Q13 (level 4, Conflicting)

**Question.** When did Chloe Nguyen (claim 6977160) go back to full duty?

**Schema path used.** Claim -> ClaimEvent{return_to_full_duty, work_status_update, medical_visit} with support = primary / summary_only / restated_only

**Cypher 1.**

```cypher
MATCH (c:Claim {claim_id:'6977160'})-[:HAS_EVENT]->(e:ClaimEvent)
WHERE e.event_type IN ['return_to_full_duty', 'work_status_update', 'medical_visit']
  AND e.event_date >= '2026-02-15' AND e.event_date <= '2026-04-15'
RETURN e.event_date AS date, e.event_type AS event, e.support AS support, e.work_status AS work_status, e.restrictions AS restrictions
ORDER BY date
```

**Result 1** (9 rows):

| date       | event               | support       | work_status                     | restrictions                                  |
|:-----------|:--------------------|:--------------|:--------------------------------|:----------------------------------------------|
| 2026-02-17 | work_status_update  | primary       | is working w/ restr             | nan                                           |
| 2026-02-18 | work_status_update  | primary       | back to full duty               | nan                                           |
| 2026-02-18 | return_to_full_duty | restated_only | nan                             | nan                                           |
| 2026-02-26 | work_status_update  | primary       | working regular duty            | No lifting over 20 lbs, limit bending         |
| 2026-03-04 | medical_visit       | primary       | working regular duty, no issues | lifting up to 30 lbs ok, no prolonged bending |
| 2026-03-11 | work_status_update  | summary_only  | working regular duty, no issues | Lifting up to 30 lbs ok, no prolonged bending |
| 2026-03-18 | medical_visit       | primary       | working regular duty, no issues | lifting up to 30 lbs ok, no prolonged bending |
| 2026-04-03 | medical_visit       | primary       | nan                             | nan                                           |
| 2026-04-13 | work_status_update  | summary_only  | working regular duty, no issues | Released to full duty, no restr               |

**Reference answer (written from the notes).** The notes disagree. The copied history says 'Back to full duty from February 18' and the 2/18 work-status note says she is back to full duty, but the same note and the 2/17 note say 'Full duty release expected 3/2'; on 2/26 she is on regular duty with a 20 lb lifting limit; Dr Haddad's 3/4 and 3/18 notes still list 'lifting up to 30 lbs ok, no prolonged bending'; restrictions first read 'Released to full duty, no restr' in the 4/13 file review. A correct answer reports the conflict and the sources rather than one date.

**Evidence.** SYN-6977160-046, -049, -054, -056, -057, -064, -080


---

## Q14 (level 4, Conflicting / unanswerable)

**Question.** Was a second Board hearing held on claim 6977160 on April 11, 2026?

**Schema path used.** ClaimEvent.support and EVIDENCED_BY.evidence_kind

**Cypher 1.**

```cypher
MATCH (c:Claim {claim_id:'6977160'})-[:HAS_EVENT]->(h:ClaimEvent)
WHERE h.event_type IN ['hearing_held', 'hearing_scheduled']
MATCH (h)-[ev:EVIDENCED_BY]->(n:Note)
RETURN h.event_type AS event, h.event_date AS date, h.outcome AS outcome, h.support AS support,
       collect(DISTINCT ev.evidence_kind) AS evidence_kinds, collect(DISTINCT n.note_id) AS notes
ORDER BY date
```

**Result 1** (4 rows):

| event             | date       | outcome     | support       | evidence_kinds          | notes                                                                                                                                                                                          |
|:------------------|:-----------|:------------|:--------------|:------------------------|:-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| hearing_scheduled | 2026-02-20 | nan         | primary       | ['summary', 'primary']  | ['SYN-6977160-039', 'SYN-6977160-045']                                                                                                                                                         |
| hearing_held      | 2026-02-20 | adjourned   | primary       | ['primary', 'restated'] | ['SYN-6977160-050', 'SYN-6977160-054', 'SYN-6977160-061', 'SYN-6977160-082', 'SYN-6977160-084', 'SYN-6977160-097', 'SYN-6977160-098', 'SYN-6977160-106', 'SYN-6977160-108']                    |
| hearing_held      | 2026-04-11 | unspecified | restated_only | ['restated']            | ['SYN-6977160-082', 'SYN-6977160-084', 'SYN-6977160-097', 'SYN-6977160-098', 'SYN-6977160-106', 'SYN-6977160-108']                                                                             |
| hearing_scheduled | 2026-11-10 | nan         | primary       | ['primary', 'summary']  | ['SYN-6977160-052', 'SYN-6977160-068', 'SYN-6977160-077', 'SYN-6977160-079', 'SYN-6977160-082', 'SYN-6977160-098', 'SYN-6977160-106', 'SYN-6977160-108', 'SYN-6977160-119', 'SYN-6977160-124'] |

**Reference answer (written from the notes).** It cannot be confirmed. 'Second hearing April 11' appears only inside copied claim histories (status reports 4/24/26, 7/9/26, 8/31/26; file reviews 5/8/26, 7/7/26; and the history paragraph pasted under the 8/25/26 eCase note). No note records the hearing first-hand: every legal entry from 2/23/26 onward says only 'Next hearing is on November 10'. The graph marks this event support = restated_only, so a correct system answers 'not confirmed' and cites both sides.

**Evidence.** SYN-6977160-052, -068, -077, -079, -119, -124 (legal notes: next hearing Nov 10); SYN-6977160-082, -084, -097, -098, -106, -108 (copied history: second hearing April 11)


---

## Q15 (level 4, Conflicting)

**Question.** What was the outcome of the April 14, 2026 hearing on claim 6977156?

**Schema path used.** ClaimEvent{hearing_held} -CONFLICTS_WITH-> ClaimEvent{hearing_held}

**Cypher 1.**

```cypher
MATCH (c:Claim {claim_id:'6977156'})-[:HAS_EVENT]->(h:ClaimEvent {event_type:'hearing_held'})
WHERE h.event_date = '2026-04-14'
MATCH (h)-[ev:EVIDENCED_BY]->(n:Note)
RETURN h.outcome AS outcome, collect(n.note_id) AS notes, min(n.note_date) AS first_said, max(n.note_date) AS last_said
```

**Result 1** (2 rows):

| outcome                 | notes                                                                                                                                 | first_said   | last_said   |
|:------------------------|:--------------------------------------------------------------------------------------------------------------------------------------|:-------------|:------------|
| decision received       | ['SYN-6977156-073', 'SYN-6977156-083', 'SYN-6977156-090', 'SYN-6977156-096', 'SYN-6977156-103', 'SYN-6977156-103', 'SYN-6977156-110'] | 2026-04-14   | 2026-07-27  |
| judge reserved decision | ['SYN-6977156-074', 'SYN-6977156-079', 'SYN-6977156-090', 'SYN-6977156-090', 'SYN-6977156-096', 'SYN-6977156-103', 'SYN-6977156-107'] | 2026-04-15   | 2026-07-13  |

**Cypher 2.**

```cypher
MATCH (a:ClaimEvent)-[x:CONFLICTS_WITH]->(b:ClaimEvent)
WHERE a.claim_id = '6977156' AND x.fact STARTS WITH 'hearing_outcome'
RETURN x.fact AS fact, x.value_a AS value_a, x.value_b AS value_b, x.resolution AS resolution
```

**Result 2** (1 rows):

| fact                       | value_a           | value_b                 | resolution   |
|:---------------------------|:------------------|:------------------------|:-------------|
| hearing_outcome_2026-04-14 | decision received | judge reserved decision | unresolved   |

**Reference answer (written from the notes).** The notes give two outcomes. SYN-6977156-073 (4/14/26) says the judge's decision was received and nothing more is needed; SYN-6977156-074 (4/15/26) and later summaries say the judge reserved decision. The decision itself is not in the file. A correct answer reports both and does not pick one.

**Evidence.** SYN-6977156-073, SYN-6977156-074, later file reviews

