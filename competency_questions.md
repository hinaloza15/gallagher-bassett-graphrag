# Competency questions on the demo graph

Each question tests whether the schema can answer a project question type. Answers are computed in Python (networkx) on the same nodes and relationships the Cypher file loads. The Cypher is the equivalent query for Neo4j; it has not been run against a Neo4j server yet.

## CQ1 Direct lookup: who handles claim 6977119, who treats it, who insures it, which body part?

Adjuster **Maya Patel**, provider **Empire Physical Medicine**, carrier **CNY OTHER THAN ED, HED WATER**, body part **MULTIPLE**.

```cypher
MATCH (c:Claim {claim_id: 6977119})
OPTIONAL MATCH (c)-[:HANDLED_BY]->(a:Adjuster)
OPTIONAL MATCH (c)-[:TREATED_BY]->(p:Provider)
OPTIONAL MATCH (c)-[:INSURED_BY]->(k:Carrier)
OPTIONAL MATCH (c)-[:AFFECTS_BODY_PART]->(b:BodyPart)
RETURN a.name, p.name, k.name, b.name
```

## CQ2 Cross-claim, 2 hops: which other claims does Maya Patel (adjuster) handle?

5 other claims: 6977098, 6977140, 6977159, 6977175, 6977193.

```cypher
MATCH (:Claim {claim_id: 6977119})-[:HANDLED_BY]->(a:Adjuster)<-[:HANDLED_BY]-(o:Claim)
WHERE o.claim_id <> 6977119
RETURN a.name, collect(o.claim_id)
```

## CQ3 Claim to public document, 2 hops: which treatment guideline covers each claim's injured body part?

| Claim | Body part | Guideline (mapping awaiting review) |
| --- | --- | --- |
| 6977099 | LOWER BACK AREA | Medical Treatment Guidelines: Mid and Low Back Injury |
| 6977100 | HAND | Medical Treatment Guidelines: Hand, Wrist and Forearm Injuries |
| 6977137 | KNEE | Medical Treatment Guidelines: Knee Injury |
| 6977166 | KNEE | Medical Treatment Guidelines: Knee Injury |
| 6977180 | WRIST | Medical Treatment Guidelines: Hand, Wrist and Forearm Injuries |
| 6977182 | LOWER ARM | Medical Treatment Guidelines: Hand, Wrist and Forearm Injuries |
| 6977194 | KNEE | Medical Treatment Guidelines: Knee Injury |
| 6977196 | WRIST | Medical Treatment Guidelines: Hand, Wrist and Forearm Injuries |
| 6977197 | KNEE | Medical Treatment Guidelines: Knee Injury |

9 of 34 demo claims reach a guideline; the rest have body parts with no uploaded guideline or a mapping still under review (see schema/body_part_guideline_map.csv).

```cypher
MATCH (c:Claim)-[:AFFECTS_BODY_PART]->(b:BodyPart)<-[:COVERS_BODY_PART]-(d:Document {doc_type: 'treatment_guideline'})
RETURN c.claim_id, b.name, d.title
```

## CQ4 Process: what must the claimant do, with which form, and by when?

| Step | Action | Form | Deadline |
| --- | --- | --- | --- |
| PS01 | Seek medical care | none | immediately |
| PS02 | Notify employer in writing of when, where and how the injury happened | none | within 30 days of injury |
| PS03 | Tell health care providers the injury is work-related and name the employer's insurer | none | not stated |
| PS04 | File an Employee Claim with the Board | C-3 | within two years of the injury or illness |
| PS05 | File a Limited Release of Health Information | C-3.3 | not stated |
| PS10 | Attend follow-up medical visits | none | 15 days after the injury, then every 90 days while lost time continues |
| PS13 | Appeal the judge's decision in writing | none | within 30 days of the filing date |
| PS14 | Apply for disability benefits while a disputed claim is heard | DB-450 | not stated |
| PS15 | Request reimbursement of medical travel expenses | C-257 | submit receipts at least every six months |

```cypher
MATCH (s:ProcessStep)-[:PERFORMED_BY]->(:Role {role_name: 'Claimant'})
OPTIONAL MATCH (s)-[:USES_FORM]->(f:Form)
RETURN s.step_id, s.name, collect(f.form_code), s.deadline_text ORDER BY s.step_id
```

## CQ5 Traceability: which text supports "claim 6977119 is handled by Maya Patel"?

The HANDLED_BY edge comes from the synthetic record field (method structured_field). Text evidence: 1 chunk(s) mention the adjuster within claim 6977119's notes:

- `SYN-6977119-02#0` characters 26 to 36: "...Adjuster progress note by Maya Patel for claim 6977119. Reviewed t..."

```cypher
MATCH (ch:Chunk)-[m:MENTIONS]->(a:Adjuster)<-[:HANDLED_BY]-(c:Claim {claim_id: 6977119})
WHERE m.scope_claim_id = 6977119
RETURN ch.chunk_id, m.span_start, m.span_end, ch.text
```

## CQ6 Entity resolution: is "Maya Patel" one person or two?

- `Adjuster:ADJ-MAYA-PATEL` linked to claim(s) 6977098, 6977119, 6977140, 6977159, 6977175, 6977193
- `Claimant:CLMT-6977140` linked to claim(s) 6977140

The schema keys people by role and ID, never by name, so the claimant and the adjuster stay separate nodes; merging by name would join them. In this demo set the two even share claim 6977140, which is a synthetic-data error (an adjuster would not handle their own claim) to fix in the data generator.

