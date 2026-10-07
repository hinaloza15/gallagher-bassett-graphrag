# Demo graph statistics

Schema version 0.1.0. Built 2026-10-06 by src/build_demo_graph.py.

**Validation errors: 0**


## Nodes by label

| Label | Count |
| --- | --- |
| Adjuster | 6 |
| BodyPart | 25 |
| Carrier | 24 |
| Chunk | 122 |
| Claim | 34 |
| Claimant | 34 |
| County | 17 |
| Document | 109 |
| Employer | 16 |
| Form | 5 |
| Industry | 11 |
| Injury | 11 |
| InjuryCause | 17 |
| Location | 32 |
| ProcessStep | 15 |
| Provider | 8 |
| Role | 6 |
| **Total** | **492** |

## Relationships by type

| Type | Count |
| --- | --- |
| ABOUT_CLAIM | 102 |
| AFFECTS_BODY_PART | 34 |
| CAUSED_BY | 34 |
| COVERS_BODY_PART | 12 |
| DESCRIBED_IN | 15 |
| FILED_BY | 34 |
| HANDLED_BY | 34 |
| HAS_CHUNK | 122 |
| HAS_INJURY | 34 |
| INSURED_BY | 34 |
| INVOLVES_EMPLOYER | 34 |
| IN_COUNTY | 32 |
| IN_INDUSTRY | 34 |
| MENTIONS | 678 |
| NEXT_CHUNK | 17 |
| OCCURRED_AT | 34 |
| OCCURRED_IN | 34 |
| PERFORMED_BY | 16 |
| PRECEDES | 4 |
| TREATED_BY | 34 |
| USES_FORM | 5 |
| **Total** | **1377** |

## Mandatory coverage (share of claims with each claim-layer relationship)

| Relationship | Claims covered |
| --- | --- |
| FILED_BY | 34 / 34 |
| INVOLVES_EMPLOYER | 34 / 34 |
| INSURED_BY | 34 / 34 |
| HANDLED_BY | 34 / 34 |
| TREATED_BY | 34 / 34 |
| HAS_INJURY | 34 / 34 |
| AFFECTS_BODY_PART | 34 / 34 |
| CAUSED_BY | 34 / 34 |
| OCCURRED_IN | 34 / 34 |
| OCCURRED_AT | 34 / 34 |
| IN_INDUSTRY | 34 / 34 |

## Hub nodes (most claims attached)

| Node | Claims |
| --- | --- |
| Injury: STRAIN OR TEAR | 16 |
| Carrier: STATE INSURANCE FUND | 10 |
| Industry: PUBLIC ADMINISTRATION | 9 |
| BodyPart: MULTIPLE | 9 |
| Injury: CONTUSION | 8 |
| Industry: HEALTH CARE AND SOCIAL ASSISTANCE | 8 |
| County: KINGS | 6 |
| Adjuster: Priya Shah | 6 |

## Same name under different person labels (kept as separate nodes)

- Daniel Brooks: Adjuster, Claimant
- Maya Patel: Adjuster, Claimant
- Priya Shah: Adjuster, Claimant

## Claims where the claimant and the adjuster have the same name (synthetic data error)

- 6977140 (Maya Patel)
- 6977141 (Daniel Brooks)
- 6977144 (Priya Shah)

## Ambiguous mentions (one span matches two entities; not linked, needs review)

- `SYN-6977140-01#0` "Maya Patel": Adjuster:ADJ-MAYA-PATEL, Claimant:CLMT-6977140
- `SYN-6977140-02#0` "Maya Patel": Adjuster:ADJ-MAYA-PATEL, Claimant:CLMT-6977140
- `SYN-6977140-02#0` "Maya Patel": Adjuster:ADJ-MAYA-PATEL, Claimant:CLMT-6977140
- `SYN-6977140-03#0` "Maya Patel": Adjuster:ADJ-MAYA-PATEL, Claimant:CLMT-6977140
- `SYN-6977141-01#0` "Daniel Brooks": Adjuster:ADJ-DANIEL-BROOKS, Claimant:CLMT-6977141
- `SYN-6977141-02#0` "Daniel Brooks": Adjuster:ADJ-DANIEL-BROOKS, Claimant:CLMT-6977141
- `SYN-6977141-02#0` "Daniel Brooks": Adjuster:ADJ-DANIEL-BROOKS, Claimant:CLMT-6977141
- `SYN-6977141-03#0` "Daniel Brooks": Adjuster:ADJ-DANIEL-BROOKS, Claimant:CLMT-6977141
- `SYN-6977144-01#0` "Priya Shah": Adjuster:ADJ-PRIYA-SHAH, Claimant:CLMT-6977144
- `SYN-6977144-02#0` "Priya Shah": Adjuster:ADJ-PRIYA-SHAH, Claimant:CLMT-6977144
- `SYN-6977144-02#0` "Priya Shah": Adjuster:ADJ-PRIYA-SHAH, Claimant:CLMT-6977144
- `SYN-6977144-03#0` "Priya Shah": Adjuster:ADJ-PRIYA-SHAH, Claimant:CLMT-6977144

## Data checks

- Location county equals record county: 34 / 34 claims
- Nodes with no relationships: 1 (Role:Attorney or representative)
- Relationships awaiting human review: 730 of 1377
