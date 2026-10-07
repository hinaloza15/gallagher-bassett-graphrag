# GraphRAG Graph Schema v0 (draft for midterm)

**Owner:** Keya · **Project:** GraphRAG vs. Hybrid RAG for claims knowledge (IDS 560 Group 3, sponsor Gallagher Bassett) · **Date:** Oct 6, 2026 · **Status:** draft, tested on the demo data; not final until the data decision gate.

The schema has **18 node labels and 27 relationship types in four layers**: claim facts, text for retrieval, claims-process knowledge from public WCB documents, and a reserved event layer. Loaded with the demo data (34 claims, 102 synthetic notes, 7 public WCB documents), it produces **492 nodes and 1,377 relationships with 0 schema violations**. It answers all six test questions in `out/competency_questions.md`.

![Schema diagram with demo counts](out/schema_diagram.png)

Numbers in brackets in the diagram are node counts in the demo graph. Dashed grey parts are reserved for v1 and not populated yet.

---

## 1. How the team's proposed entities map to the schema

| Proposed entity | Schema label | Change and why |
| --- | --- | --- |
| Claim | `Claim` | Kept. Key = WCB Claim Identifier. |
| Claimant | `Claimant` | Kept. Key = `CLMT-<claim_id>`, never the name (see finding 2). |
| Employer | `Employer` | Kept. Industry is **not** stored on Employer (finding 3). |
| Adjuster | `Adjuster` | Kept. |
| Provider | `Provider` | Kept. |
| Injury | `Injury` | Kept, defined as the **WCIO nature of injury** (e.g. STRAIN OR TEAR), keyed by WCIO code. |
| Body Part | `BodyPart` | Kept, keyed by **WCIO part-of-body code**, not name: names repeat across codes (finding 5). |
| Cause of Injury | `InjuryCause` | Kept, keyed by WCIO cause code. |
| Carrier | `Carrier` | Kept. Carrier type (private, SIF, self-insured) is a property. |
| County | `County` | Kept. |
| Policy Document | `Document` + `Chunk`, plus `ProcessStep`, `Form`, `Role` | Split. A document is the text we retrieve; the steps, forms and roles inside it are what GraphRAG traverses. `doc_type` = `claim_note`, `process_guide` or `treatment_guideline`. |
| (added) | `Industry` | The public record gives a 2-digit NAICS sector for each claim. |
| (added) | `Location` | The demo notes give a detailed incident location inside a county. |
| (added) | `ClaimEvent` (reserved) | For workflow facts (referral, modified duty offer, escalation). The demo notes contain none yet (finding 4). |

## 2. Design rules (from Emil's guidance and the SOW)

1. **Fixed list.** Loading and extraction may create only the labels and relationship types in `schema/graph_schema_v0.yaml`. Anything else is rejected and logged for review, so the graph cannot grow without limit.
2. **Node or property?** Make something a node only if many claims share it **and** we want to traverse through it (who else has this adjuster, which guideline covers this body part), or if it has its own relationships. Everything else stays a property. That is why status, highest process, district, hearing count and attorney flag are properties of `Claim`.
3. **Keys are codes or IDs, never names.** Vocabulary nodes use official codes (WCIO, NAICS); people and organizations use stable IDs. Names are display properties.
4. **Provenance on every relationship:** `source_type`, `source_id`, `method`, `review_status` and `schema_version`, plus `chunk_id`, character span, `confidence` and `scope_claim_id` where they apply. Deterministic edges from structured fields are `approved`. Edges derived from text or curated tables start `unreviewed`.
5. **Facts stay inside their claim.** Text-derived edges carry `scope_claim_id`, and note text is matched only against the entities of that note's own claim. This stops a fact about one synthetic claim from leaking into another.
6. **Mandatory vs. optional.** Mandatory = every claim links to it whenever the public record has a value: Claim, Claimant, Carrier, Injury, BodyPart, InjuryCause, County, Industry. Optional = exists only in synthetic or extracted data: Employer, Adjuster, Provider, Location, process nodes, events. A missing value creates **no edge**. It never creates an "UNKNOWN" node, which would become a giant hub.
7. **Humans validate the start.** The schema, the body-part-to-guideline table and the process seed are drafts for team and sponsor review, not facts the model decided.

## 3. Entity definitions

| Label | What it is | Key | Main properties | Source | Required | Growth | Demo count |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Claim | One workers' compensation claim | `claim_id` | accident/assembly date, claim injury type, current status, highest process, district, attorney flag, hearing count, claim type | Public record | Yes | Linear | 34 |
| Claimant | The injured worker on a claim | `claimant_id` | name (synthetic), age at injury, gender | Public record + synthetic | Yes | Linear | 34 |
| Employer | Employer of record | `employer_id` | name | Synthetic | No | Entity | 16 |
| Adjuster | Person handling the claim for the carrier or TPA | `adjuster_id` | name | Synthetic | No | Entity | 6 |
| Provider | Treating clinic or provider | `provider_id` | name | Synthetic | No | Entity | 8 |
| Carrier | Insurer, state fund or self-insured employer | `carrier_id` | name, carrier type | Public record | Yes | Entity | 24 |
| Injury | WCIO nature of injury | `wcio_nature_code` | name | Public record | Yes | Bounded | 11 |
| BodyPart | WCIO part of body | `wcio_body_code` | name | Public record | Yes | Bounded | 25 |
| InjuryCause | WCIO cause of injury | `wcio_cause_code` | name | Public record | Yes | Bounded | 17 |
| County | NY county of injury | `name` | | Public record | Yes | Bounded | 17 |
| Location | Detailed incident location | `location_id` | name | Synthetic | No | Entity | 32 |
| Industry | 2-digit NAICS sector | `naics2` | name | Public record | Yes | Bounded | 11 |
| Document | A retrievable source document | `doc_id` | doc type, note type, title, synthetic flag, path, license note | Notes + public docs | Yes | Linear | 109 |
| Chunk | Passage of a document; unit of retrieval and citation | `chunk_id` | text, position, word count, embedding (later) | Derived | Yes | Linear | 122 |
| ProcessStep | A step in the claims process | `step_id` | name, deadline text, deadline days, condition | Public WCB docs (curated) | No | Bounded | 15 |
| Form | A WCB form | `form_code` | name | Public WCB docs | No | Bounded | 5 |
| Role | Generic process role | `role_name` | instance label, description | Public WCB docs | No | Bounded | 6 |
| ClaimEvent | Workflow event on a claim (reserved) | `event_id` | event type, date, description | Future notes | No | Linear | 0 |

BodyPart has 25 nodes: 18 come from the demo claims and 7 from the guideline mapping table (e.g. SHOULDER(S)), so guidelines can link to them before claims with those body parts arrive.

## 4. Relationship definitions

| Type | From → To | Meaning | Created by | Demo count |
| --- | --- | --- | --- | --- |
| FILED_BY | Claim → Claimant | Claim filed by this worker | Structured field | 34 |
| INVOLVES_EMPLOYER | Claim → Employer | Employer of record | Synthetic field | 34 |
| INSURED_BY | Claim → Carrier | Carrier responsible | Structured field | 34 |
| HANDLED_BY | Claim → Adjuster | Adjuster on the claim | Synthetic field | 34 |
| TREATED_BY | Claim → Provider | Treating provider | Synthetic field | 34 |
| HAS_INJURY | Claim → Injury | Nature of injury | Structured field | 34 |
| AFFECTS_BODY_PART | Claim → BodyPart | Injured body part | Structured field | 34 |
| CAUSED_BY | Claim → InjuryCause | Cause of injury | Structured field | 34 |
| OCCURRED_IN | Claim → County | County of injury | Structured field | 34 |
| OCCURRED_AT | Claim → Location | Detailed location | Synthetic field | 34 |
| IN_COUNTY | Location → County | Location lies in county | Synthetic field | 32 |
| IN_INDUSTRY | Claim → Industry | Industry sector on the record | Structured field | 34 |
| ABOUT_CLAIM | Document → Claim | Note belongs to claim | Structured field | 102 |
| HAS_CHUNK | Document → Chunk | Document split into chunks | Chunking | 122 |
| NEXT_CHUNK | Chunk → Chunk | Reading order in long documents | Chunking | 17 |
| MENTIONS | Chunk → any entity | Text names this entity: the bridge between text search and the graph | Rule match (later: LLM or System 1) | 678 |
| COVERS_BODY_PART | Document → BodyPart | Treatment guideline applies to body part | Curated table | 12 |
| PERFORMED_BY | ProcessStep → Role | Who does the step | Curated seed | 16 |
| USES_FORM | ProcessStep → Form | Form used in the step | Curated seed | 5 |
| PRECEDES | ProcessStep → ProcessStep | Order stated in the source | Curated seed | 4 |
| DESCRIBED_IN | ProcessStep → Document | Where the step is described (with chunk) | Curated seed | 15 |
| HAS_EVENT, DEPENDS_ON, EVENT_PRECEDES, DELAYS, ESCALATES_TO, INVOLVES_ROLE | Claim/ClaimEvent → ClaimEvent/Role | Reserved for event-bearing notes | Future extraction | 0 |

## 5. What the demo data showed (please read: some need fixes)

1. **Structured fields are consistent.** County, carrier, nature, body part, cause and status in `GB_102_Synthetic_Notes.csv` match the NY public record for all 34 claims (0 mismatches).
2. **Same person name in two roles, and a data error.** Maya Patel, Daniel Brooks and Priya Shah are each a claimant on one claim **and** the adjuster on six. In claims 6977140, 6977141 and 6977144, the claimant and the adjuster are the same name, which means an adjuster handling their own claim. **Fix in the data generator.** The schema keeps them as separate nodes, and the loader refuses to guess: 12 ambiguous name matches are logged in `out/graph_stats.md`, not linked.
3. **One employer, several industries.** For example, Harborview Community Health appears under 3 different industry sectors across its claims. Industry therefore hangs off `Claim` (from the public record), not `Employer`. If synthetic employers should be realistic, the generator should keep each employer in one sector.
4. **The demo notes contain no workflow events.** Every note restates fields that already exist in the structured record (dates, carrier, body part, status). So this demo can test entity lookup, cross-claim links and links to public documents, but **not** the multi-hop workflow questions GraphRAG is meant to win on, such as "what is needed before benefits can be assigned". For that, a subset of claims needs notes with events, like DOC-1001 to DOC-1012 in the earlier demo workbook. That is what `ClaimEvent` is reserved for.
5. **Body-part names are not unique.** In the full 2026 file, "SOFT TISSUE" is code 18 and code 25, "DISC" is 22 and 43, and "SPINAL CORD" is 23 and 47. Keying by name would merge different body regions.
6. **Hub nodes.** In the full 2026 file, body part MULTIPLE has 33,520 claims and STATE INSURANCE FUND has 31,965. Traversing through such nodes connects almost everything, so GraphRAG retrieval should skip or down-weight very high-degree nodes. (HippoRAG weights nodes by specificity for a similar reason.)
7. **Licensing.** The four Medical Treatment Guidelines PDFs say they may be viewed and printed for internal reference only and must not be redistributed. **Do not commit those PDFs to a public GitHub repository.** The graph stores only their title and file name; they are not chunked here.

## 6. Will it scale? (vocabulary sizes in the full 2026 file, 185,145 claims)

| Label | Distinct values | Growth |
| --- | --- | --- |
| Injury (WCIO nature) | 56 | Bounded |
| BodyPart (WCIO part of body) | 53 | Bounded |
| InjuryCause (WCIO cause) | 77 | Bounded |
| Industry (NAICS 2-digit) | 24 | Bounded |
| County of Injury | 63 | Bounded |
| Carrier | 1,114 | Grows with distinct carriers |
| Claim, Claimant | 185,145 | One per claim |

Vocabulary layers stay small however many claims are loaded. Only claim-level nodes, documents and chunks grow with the data, which is expected.

## 7. Reserved event layer (v1) and the demo workbook's relationship words

| Workbook relationship | v1 schema | Note |
| --- | --- | --- |
| REQUIRES | DEPENDS_ON | "A requires B" is stored as A DEPENDS_ON B |
| DELAYS | DELAYS | Same |
| ESCALATES_TO | ESCALATES_TO | Same |
| PRECEDES, FOLLOWS | EVENT_PRECEDES | FOLLOWS is stored in the reverse direction |
| INCREASES, AFFECTS, ASSOCIATED_WITH, TRIGGERS | Not included yet | These claim a causal or statistical effect that one synthetic note cannot establish. To discuss with Emil. |

## 8. Change control

1. Extraction output that does not fit the schema goes to a review log, not into the graph.
2. A proposed new label or relationship needs: a benchmark question that requires it, three example sentences from the corpus, and a reviewer.
3. Accepted changes bump `schema_version` (0.1.0 → 0.2.0) and are recorded below. Every edge carries the version that created it, so old and new edges can be told apart.

| Version | Date | Change |
| --- | --- | --- |
| 0.1.0 | 2026-10-06 | First draft, tested on demo data |

## 9. Open questions for Emil and the team

1. Does the claim-layer list match how GB thinks about a claim at a high level? Anything missing: nurse case manager, attorney as an entity, employer location?
2. Is `Injury` as "nature of injury" the right meaning, or should we have one injury node per claim to allow several injuries on one claim?
3. Which event types matter most for v1 (referral, modified duty, IME, escalation, hearing)?
4. Should cross-claim links (claims sharing a provider, employer or adjuster) be part of the evaluation questions, given that fraud detection is out of scope in the SOW?
5. Who on the team reviews the body-part-to-guideline table and the 15 process steps before they count as approved?
6. Can the data generator add WCIO and NAICS codes to the demo CSV? Then the loader would not need the 76 MB NY file.

## 10. Files

```
README.md                          this document
schema/graph_schema_v0.yaml        machine-readable schema: labels, keys, properties, relationships, enums
schema/body_part_guideline_map.csv WCIO body part -> treatment guideline (draft; status per row)
seed/process_steps_seed.csv        15 claims-process steps, each with a verbatim quote from a WCB document
seed/forms_seed.csv, roles_seed.csv
neo4j/constraints.cypher           uniqueness constraints, full-text and vector indexes (Neo4j 5)
src/build_demo_graph.py            builds and validates the demo graph; writes everything in out/
out/nodes.csv, out/edges.csv       the demo graph, with provenance on every edge
out/load_demo_graph.cypher         MERGE/CREATE statements to load it into an empty Neo4j database
out/graph.json                     nodes and links without chunks, for the UI graph view
out/graph_stats.md                 counts, coverage, hubs, data problems found
out/competency_questions.md        six test questions, answers, and the Cypher for each
out/schema_diagram.png/.svg/.dot   the diagram above
```

### Run it

```bash
pip install -r requirements.txt          # pandas, pyyaml, networkx; Graphviz optional for the diagram
python src/build_demo_graph.py \
  --notes data/GB_102_Synthetic_Notes.csv \
  --claims data/Assembled_Workers__Compensation_Claims.csv \
  --public-dir data/public_docs \
  --out out
```

The Python validation and test questions were run. The Cypher files have **not** been executed against a Neo4j server yet (none was available where this was built). Whoever sets up Neo4j should run `neo4j/constraints.cypher`, then `out/load_demo_graph.cypher`, on an empty database and report any errors. The load file uses CREATE for relationships, so running it twice duplicates them.
