"""
03_run_schema_test_questions.py

Loads the graph built by 02_build_graph_from_claim_notes.py into Kuzu (an embedded database that
runs Cypher, so no server is needed), runs the 15 schema test questions, and writes
    05_outputs/schema_test_questions_and_answers.md   question, Cypher, query result, reference answer, evidence
    04_neo4j/03_schema_test_queries.cypher            the same queries for Neo4j Browser

Run from graph_schema_v1/:
    pip install kuzu
    python 03_code/03_run_schema_test_questions.py

Purpose: prove the schema can answer simple-to-hard questions, including conflicting and
unanswerable ones. These are SCHEMA tests, not the project's evaluation set. Keep this file and its
output out of both retrieval indexes (they contain reference answers).
"""
import csv, json, os, shutil, sys, tempfile
from collections import defaultdict

import pandas as pd
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "05_outputs")
TYPE = {"str": "STRING", "int": "INT64", "float": "DOUBLE", "bool": "BOOLEAN", "date": "STRING", "list": "STRING"}

# --------------------------------------------------------------------------------------------
# The questions. level: 1 = simple lookup ... 4 = conflicting or unanswerable.
# reference_answer was written by reading the notes themselves, not copied from the query result.
# --------------------------------------------------------------------------------------------
QUESTIONS = [
 dict(id="Q01", level=1, qclass="Direct",
      question="Who is the treating doctor on claim 6977160, at which clinic, and which carrier insures the claim?",
      cypher=["""MATCH (c:Claim {claim_id:'6977160'})-[s:SEEN_BY]->(d:Clinician)-[:PRACTICES_AT]->(f:HealthcareFacility),
      (c)-[:INSURED_BY]->(car:Carrier)
WHERE s.role = 'treating_physician'
RETURN d.name AS doctor, f.name AS clinic, car.name AS carrier"""],
      reference_answer="Dr Haddad at Upstate Hearing & Balance Center; the carrier is the State Insurance Fund (written 'SIF' in many notes).",
      evidence="SYN-6977160-010 (Dr Haddad's first office note), SYN-6977160-039 (status report: 'treating Dr Haddad', 'State Insurance Fund on the risk')",
      schema_path="Claim -SEEN_BY{treating_physician}-> Clinician -PRACTICES_AT-> HealthcareFacility; Claim -INSURED_BY-> Carrier"),
 dict(id="Q02", level=1, qclass="Direct",
      question="Which claims have a claimant attorney, and who is the attorney on each?",
      cypher=["""MATCH (c:Claim)-[:REPRESENTED_BY]->(a:Attorney)
RETURN c.claim_id AS claim, c.claimant_name AS claimant, a.name AS attorney, a.firm_email_domain AS firm_domain
ORDER BY claim"""],
      reference_answer="Five claims: 6977156 Lena Alvarez, 6977160 Alicia Romano, 6977163 Lena Castillo, 6977175 Victor Brandt, 6977197 Carla Brennan. The other ten claims name no attorney.",
      evidence="'X is the worker's attorney' in copied history, and attorney emails from *law.example addresses (e.g. SYN-6977160-070)",
      schema_path="Claim -REPRESENTED_BY-> Attorney"),
 dict(id="Q03", level=1, qclass="Terminology / alias",
      question="Adjusters write the carrier as 'SIF' or 'State Ins Fund'. Which claims are insured by the State Insurance Fund, and how is the carrier written in their notes?",
      cypher=["""MATCH (c:Claim)-[:INSURED_BY]->(car:Carrier {carrier_id:'CAR-state-insurance-fund'})
OPTIONAL MATCH (c)-[:HAS_NOTE]->(:Note)-[:HAS_CHUNK]->(:Chunk)-[m:MENTIONS]->(car)
RETURN c.claim_id AS claim, collect(DISTINCT m.matched_text) AS written_as
ORDER BY claim"""],
      reference_answer="Seven claims: 6977098, 6977137, 6977140, 6977156, 6977160, 6977175, 6977194. The notes use 'SIF', 'State Ins Fund', 'State Insurance Fund' and the record's upper-case 'STATE INSURANCE FUND'. A keyword search for 'State Insurance Fund' alone would miss the notes that only say 'SIF'.",
      evidence="Carrier (source) column; for example SYN-6977160-005 ('SIF is on the risk') and SYN-6977160-045 ('Copy to State Ins Fund')",
      schema_path="Claim -INSURED_BY-> Carrier <-MENTIONS{matched_text}- Chunk"),
 dict(id="Q04", level=2, qclass="Terminology / alias",
      question="The claim record lists the body part as 'MULTIPLE' on six claims. Which body parts do the notes actually name for those claims?",
      cypher=["""MATCH (c:Claim)-[:HAS_BODY_PART]->(:BodyPart {name:'MULTIPLE'})
MATCH (c)-[:HAS_DIAGNOSIS]->(d:Diagnosis)-[r:DIAGNOSIS_AFFECTS]->(b:BodyPart)
RETURN c.claim_id AS claim, d.text AS diagnosis, collect(DISTINCT b.name) AS body_parts_in_notes
ORDER BY claim"""],
      reference_answer="6977118 low back and both shoulders; 6977121 neck (some notes add upper back and shoulder); 6977144 neck and low back; 6977156 low back, hip and both knees; 6977160 low back, hip and both knees; 6977175 neck, back and both wrists.",
      evidence="'dx ...' phrases in first reports and copied history, e.g. SYN-6977160-014, SYN-6977118-013",
      schema_path="Claim -HAS_BODY_PART-> BodyPart{wcio}; Claim -HAS_DIAGNOSIS-> Diagnosis -DIAGNOSIS_AFFECTS-> BodyPart{specific}"),
 dict(id="Q05", level=2, qclass="Cross-document",
      question="Which New York Medical Treatment Guidelines cover the body parts injured on claim 6977160?",
      cypher=["""MATCH (c:Claim {claim_id:'6977160'})-[:HAS_DIAGNOSIS]->(:Diagnosis)-[:DIAGNOSIS_AFFECTS]->(b:BodyPart)
MATCH (doc:Document)-[g:COVERS_BODY_PART]->(b)
RETURN b.name AS body_part, doc.doc_id AS doc_id, doc.title AS guideline, g.mapping_status AS mapping_status"""],
      reference_answer="Low back: Mid and Low Back Injury MTG (RD15). Hip: Hip and Groin Disorders MTG (RD19). Knees: Knee Injury MTG (RD14). The body-part-to-guideline map is a draft and needs team review.",
      evidence="Diagnosis 'strain of the low back, hip and both knees' (SYN-6977160-024); 02_reference_data/02_body_part_to_treatment_guideline_map.csv; WCB guideline list page",
      schema_path="Claim -> Diagnosis -> BodyPart <-COVERS_BODY_PART- Document"),
 dict(id="Q06", level=2, qclass="Cross-document",
      question="Claim 6977137 is a lost-time claim. Does the weekly payment match the NY rule that benefits are two-thirds of the average weekly wage?",
      cypher=["""MATCH (c:Claim {claim_id:'6977137'})-[:HAS_EVENT]->(w:ClaimEvent {event_type:'wage_information'})
MATCH (c)-[:HAS_EVENT]->(p:ClaimEvent {event_type:'benefit_payment'})
WHERE p.weekly_rate IS NOT NULL
RETURN DISTINCT w.average_weekly_wage AS average_weekly_wage, p.weekly_rate AS weekly_rate,
       w.average_weekly_wage * 2.0 / 3.0 AS two_thirds_of_wage""",
              """MATCH (s:ProcessStep {step_id:'PS07'})-[d:DESCRIBED_IN]->(doc:Document)
RETURN s.name AS rule, s.rule_text AS quote, doc.title AS source"""],
      reference_answer="Yes. The employer reported a weekly wage of about $985; two-thirds of $985 is $656.67, and the ledger pays $657.00 a week. This assumes total disability; the rule also adjusts for degree of disability, which the notes do not state.",
      evidence="SYN-6977137-006 (wage), SYN-6977137-016 ('Paid $657.00/wk'), RD05 lost wage benefits fact sheet (PS07)",
      schema_path="Claim -> ClaimEvent{wage_information}, ClaimEvent{benefit_payment}; ProcessStep -DESCRIBED_IN-> Document"),
 dict(id="Q07", level=2, qclass="Unanswerable",
      question="What did the independent medical examination (IME) find on claim 6977121?",
      cypher=["""MATCH (c:Claim {claim_id:'6977121'})
OPTIONAL MATCH (c)-[:HAS_EVENT]->(e:ClaimEvent)
WHERE e.event_type IN ['ime_scheduled', 'ime_report']
OPTIONAL MATCH (c)-[s:SEEN_BY]->(x:Clinician)
WHERE s.role = 'ime_examiner'
RETURN count(DISTINCT e) AS ime_events, count(DISTINCT x) AS ime_examiners"""],
      reference_answer="Cannot be answered: no IME was scheduled or reported on claim 6977121. A correct system says so instead of borrowing an IME finding from another claim.",
      evidence="No IME note or IME phrase in the 92 notes of claim 6977121",
      schema_path="absence of ClaimEvent{ime_*} and SEEN_BY{ime_examiner}"),
 dict(id="Q08", level=2, qclass="Conflicting (resolved by a correction)",
      question="What is the date of injury on claim 6977182?",
      cypher=["""MATCH (c:Claim {claim_id:'6977182'})-[:HAS_EVENT]->(e:ClaimEvent {event_type:'injury_occurred'})
OPTIONAL MATCH (e)-[x:CONFLICTS_WITH]->(o:ClaimEvent)
RETURN e.event_date AS date_of_injury, e.evidence_count AS notes_supporting, x.resolution AS resolution
ORDER BY notes_supporting DESC""",
              """MATCH (fix:Note)-[r:CORRECTS]->(n:Note)
WHERE fix.claim_id = '6977182' AND r.corrected_fact = 'date of injury'
RETURN fix.note_id AS correction_note, fix.note_date AS written_on, n.note_id AS corrected_note, r.wrong_value AS wrong, r.right_value AS right"""],
      reference_answer="October 20, 2025. One note gave 10/21/2025; the adjuster's correction note SYN-6977182-096 says 'DOI is 10/20/2025 not 10/21/2025'.",
      evidence="SYN-6977182-094 (wrong date), SYN-6977182-096 (correction), first report SYN-6977182-005",
      schema_path="ClaimEvent{injury_occurred} -CONFLICTS_WITH-> ClaimEvent; Note -CORRECTS-> Note"),
 dict(id="Q09", level=3, qclass="Terminology / alias (name collision)",
      question="'Dr Fischer' appears on three claims. Is it the same doctor?",
      cypher=["""MATCH (c:Claim)-[s:SEEN_BY]->(d:Clinician {name:'Dr Fischer'})
OPTIONAL MATCH (d)-[:PRACTICES_AT]->(f:HealthcareFacility)
RETURN d.clinician_id AS node, s.role AS role_on_claim, f.name AS facility, collect(DISTINCT c.claim_id) AS claims"""],
      reference_answer="The notes do not show that it is. Dr Fischer is the treating doctor at North Shore Occupational Health on 6977098, the treating doctor at Capital Region Occupational Health on 6977194, and the IME examiner on 6977160. Only a surname is given, so the graph keeps three separate nodes; merging them would invent a link. An IME examiner who also treats patients elsewhere is possible but unproven here.",
      evidence="Headers 'Dr Fischer (treating provider)' on 6977098 and 6977194; SYN-6977160-043 ('IME sched February 20 with Dr Fischer')",
      schema_path="Clinician keyed by surname + facility; IME examiners keyed separately"),
 dict(id="Q10", level=3, qclass="Multi-hop",
      question="Which claims did the adjuster dispute, did those claims go to a Board hearing or conciliation, and who represented the worker?",
      cypher=["""MATCH (c:Claim)-[:HAS_EVENT]->(d:ClaimEvent {event_type:'compensability_decision'})
WHERE d.decision = 'disputed'
OPTIONAL MATCH (c)-[:HAS_EVENT]->(h:ClaimEvent {event_type:'hearing_held'})
OPTIONAL MATCH (c)-[:REPRESENTED_BY]->(a:Attorney)
RETURN c.claim_id AS claim, d.event_date AS disputed_on, collect(DISTINCT h.event_date) AS hearing_dates,
       a.name AS attorney
ORDER BY claim"""],
      reference_answer="Six claims were disputed (C-7 sent to the Board): 6977098 and 6977100 went to a conciliation conference with no attorney named; 6977156 (Lena Alvarez), 6977160 (Alicia Romano), 6977163 (Lena Castillo) and 6977197 (Carla Brennan) had Board hearings. 6977160 also has a 'second hearing April 11' that appears only in summaries (see Q14).",
      evidence="Compensability Review notes, e.g. SYN-6977160-018; Hearing / Legal notes, e.g. SYN-6977160-050, SYN-6977098-058",
      schema_path="Claim -> ClaimEvent{compensability_decision} ; Claim -> ClaimEvent{hearing_held} ; Claim -REPRESENTED_BY-> Attorney"),
 dict(id="Q11", level=3, qclass="Multi-hop",
      question="On claim 6977160, which bills were denied because no authorization was on file, and what does the file record about authorization?",
      cypher=["""MATCH (c:Claim {claim_id:'6977160'})-[:HAS_EVENT]->(b:ClaimEvent {event_type:'bill_review'})
WHERE b.decision = 'denied'
RETURN b.event_date AS reviewed_on, b.service AS service, b.amount AS amount, b.reason AS reason
ORDER BY reviewed_on""",
              """MATCH (c:Claim {claim_id:'6977160'})-[:HAS_EVENT]->(a:ClaimEvent)
WHERE a.event_type IN ['authorization_request', 'authorization_decision'] OR (a.event_type = 'reserve_review' AND a.summary CONTAINS 'review')
RETURN a.event_date AS date, a.event_type AS event, a.service AS service, a.decision AS decision, a.summary AS summary
ORDER BY date"""],
      reference_answer="Denied for 'no auth on file': PT visits $87.50 (3/20/26), PT visits $253.00 (4/27/26), PT visits $140.75 (5/22/26) and an Rx bill $276 (9/17/26). The clinic asked for 6 PT visits on 12/15/25 and 2/9/26; the supervisor wrote 'ok to approve added PT' on 1/12/26; the only authorization number in the file is #66080, for an ortho consult (9/17/26). The clinic later says it 'rec'd our auth' (7/27/26, 9/2/26), and a PT bill of $447 was paid on 8/7/26. So the file never records a PT authorization decision, which explains the denials.",
      evidence="SYN-6977160-016, -031, -042, -066, -083, -089, -099, -102, -113, -117",
      schema_path="Claim -> ClaimEvent{bill_review, authorization_*}"),
 dict(id="Q12", level=3, qclass="Multi-hop (name collision across claims)",
      question="Carla Brennan and Paula Nakamura each appear on two claims. Are they the same person in the same role each time?",
      cypher=["""MATCH (c:Claim)-[:HAS_EMPLOYER_CONTACT]->(p:EmployerContact)-[:WORKS_FOR]->(e:Employer)
WHERE p.name IN ['Carla Brennan', 'Paula Nakamura']
RETURN p.name AS name, 'employer contact' AS kind, p.contact_role AS role, e.name AS organization, c.claim_id AS claim
UNION ALL
MATCH (c:Claim)-[:REPRESENTED_BY]->(p:Attorney)
WHERE p.name IN ['Carla Brennan', 'Paula Nakamura']
RETURN p.name AS name, 'attorney' AS kind, 'claimant attorney' AS role, p.firm_email_domain AS organization, c.claim_id AS claim"""],
      reference_answer="No. Carla Brennan is the worker's supervisor at Hudson Public Services on 6977100 and the claimant's attorney (brennanlaw) on 6977197. Paula Nakamura is the HR/payroll contact at Hudson Valley Hospitality on 6977182 and at Riverside Food Services on 6977144. The graph keeps four separate nodes because the role or employer differs.",
      evidence="SYN-6977100 supervisor statement header; SYN-6977197 attorney emails; employer emails from paula@hudsonvalleyhospitality.example and paula@riversidefoodservices.example",
      schema_path="EmployerContact keyed by name + employer; Attorney keyed by name + firm"),
 dict(id="Q13", level=4, qclass="Conflicting",
      question="When did Chloe Nguyen (claim 6977160) go back to full duty?",
      cypher=["""MATCH (c:Claim {claim_id:'6977160'})-[:HAS_EVENT]->(e:ClaimEvent)
WHERE e.event_type IN ['return_to_full_duty', 'work_status_update', 'medical_visit']
  AND e.event_date >= '2026-02-15' AND e.event_date <= '2026-04-15'
RETURN e.event_date AS date, e.event_type AS event, e.support AS support, e.work_status AS work_status, e.restrictions AS restrictions
ORDER BY date"""],
      reference_answer="The notes disagree. The copied history says 'Back to full duty from February 18' and the 2/18 work-status note says she is back to full duty, but the same note and the 2/17 note say 'Full duty release expected 3/2'; on 2/26 she is on regular duty with a 20 lb lifting limit; Dr Haddad's 3/4 and 3/18 notes still list 'lifting up to 30 lbs ok, no prolonged bending'; restrictions first read 'Released to full duty, no restr' in the 4/13 file review. A correct answer reports the conflict and the sources rather than one date.",
      evidence="SYN-6977160-046, -049, -054, -056, -057, -064, -080",
      schema_path="Claim -> ClaimEvent{return_to_full_duty, work_status_update, medical_visit} with support = primary / summary_only / restated_only"),
 dict(id="Q14", level=4, qclass="Conflicting / unanswerable",
      question="Was a second Board hearing held on claim 6977160 on April 11, 2026?",
      cypher=["""MATCH (c:Claim {claim_id:'6977160'})-[:HAS_EVENT]->(h:ClaimEvent)
WHERE h.event_type IN ['hearing_held', 'hearing_scheduled']
MATCH (h)-[ev:EVIDENCED_BY]->(n:Note)
RETURN h.event_type AS event, h.event_date AS date, h.outcome AS outcome, h.support AS support,
       collect(DISTINCT ev.evidence_kind) AS evidence_kinds, collect(DISTINCT n.note_id) AS notes
ORDER BY date"""],
      reference_answer="It cannot be confirmed. 'Second hearing April 11' appears only inside copied claim histories (status reports 4/24/26, 7/9/26, 8/31/26; file reviews 5/8/26, 7/7/26; and the history paragraph pasted under the 8/25/26 eCase note). No note records the hearing first-hand: every legal entry from 2/23/26 onward says only 'Next hearing is on November 10'. The graph marks this event support = restated_only, so a correct system answers 'not confirmed' and cites both sides.",
      evidence="SYN-6977160-052, -068, -077, -079, -119, -124 (legal notes: next hearing Nov 10); SYN-6977160-082, -084, -097, -098, -106, -108 (copied history: second hearing April 11)",
      schema_path="ClaimEvent.support and EVIDENCED_BY.evidence_kind"),
 dict(id="Q15", level=4, qclass="Conflicting",
      question="What was the outcome of the April 14, 2026 hearing on claim 6977156?",
      cypher=["""MATCH (c:Claim {claim_id:'6977156'})-[:HAS_EVENT]->(h:ClaimEvent {event_type:'hearing_held'})
WHERE h.event_date = '2026-04-14'
MATCH (h)-[ev:EVIDENCED_BY]->(n:Note)
RETURN h.outcome AS outcome, collect(n.note_id) AS notes, min(n.note_date) AS first_said, max(n.note_date) AS last_said""",
              """MATCH (a:ClaimEvent)-[x:CONFLICTS_WITH]->(b:ClaimEvent)
WHERE a.claim_id = '6977156' AND x.fact STARTS WITH 'hearing_outcome'
RETURN x.fact AS fact, x.value_a AS value_a, x.value_b AS value_b, x.resolution AS resolution"""],
      reference_answer="The notes give two outcomes. SYN-6977156-073 (4/14/26) says the judge's decision was received and nothing more is needed; SYN-6977156-074 (4/15/26) and later summaries say the judge reserved decision. The decision itself is not in the file. A correct answer reports both and does not pick one.",
      evidence="SYN-6977156-073, SYN-6977156-074, later file reviews",
      schema_path="ClaimEvent{hearing_held} -CONFLICTS_WITH-> ClaimEvent{hearing_held}"),
]


def main():
    try:
        import kuzu
    except ImportError:
        sys.exit("pip install kuzu   (embedded Cypher database used to run the test questions)")
    schema = yaml.safe_load(open(os.path.join(ROOT, "01_schema/01_graph_schema_definition_v1.yaml")))
    nodes = pd.read_csv(os.path.join(OUT, "02_graph_nodes_all.csv"))
    rels = pd.read_csv(os.path.join(OUT, "03_graph_relationships_all.csv"))
    work = tempfile.mkdtemp(prefix="kuzu_")
    db = kuzu.Database(os.path.join(work, "db"))
    con = kuzu.Connection(db)

    # node tables
    for lab, spec in schema["node_labels"].items():
        props = spec["properties"]
        cols = ", ".join(f"{p} {TYPE[t]}" for p, t in props.items())
        con.execute(f"CREATE NODE TABLE {lab}({cols}, PRIMARY KEY({spec['key']}))")
        sub = nodes[nodes.label == lab]
        rows = []
        for pj in sub.properties_json:
            d = json.loads(pj)
            rows.append({p: (json.dumps(d[p]) if isinstance(d.get(p), list) else d.get(p)) for p in props})
        f = os.path.join(work, f"n_{lab}.csv")
        df = pd.DataFrame(rows, columns=list(props))
        for p_, t_ in props.items():
            if t_ == "int":
                df[p_] = pd.to_numeric(df[p_], errors="coerce").astype("Int64")
            elif t_ == "float":
                df[p_] = pd.to_numeric(df[p_], errors="coerce")
            elif t_ == "bool":
                df[p_] = df[p_].map(lambda v: None if v is None or (isinstance(v, float) and pd.isna(v)) else ("true" if v else "false"))
        df.to_csv(f, index=False)
        if rows:
            con.execute(f"COPY {lab} FROM '{f}' (header=true, parallel=false)")
    # relationship tables
    prov = ["source_type", "source_ids", "method", "review_status", "schema_version", "scope_claim_id"]
    for rt, spec in schema["relationship_types"].items():
        sub = rels[rels.type == rt]
        extra = sorted({k for pj in sub.properties_json for k in json.loads(pj)})
        cols = prov + [k for k in extra if k not in prov]
        pairs = ", ".join(f"FROM {a} TO {b}" for a in spec["from"] for b in spec["to"])
        con.execute(f"CREATE REL TABLE {rt}({pairs}, " + ", ".join(f"{c} STRING" for c in cols) + ")")
        groups = defaultdict(list)
        for r in sub.itertuples():
            fl, fk = r.from_node_id.split(":", 1); tl, tk = r.to_node_id.split(":", 1)
            d = json.loads(r.properties_json)
            row = {"from": fk, "to": tk, "source_type": r.source_type, "source_ids": r.source_ids, "method": r.method,
                   "review_status": r.review_status, "schema_version": r.schema_version, "scope_claim_id": r.scope_claim_id}
            row.update({k: (json.dumps(v) if isinstance(v, (list, dict)) else v) for k, v in d.items()})
            groups[(fl, tl)].append(row)
        for (fl, tl), rows in groups.items():
            f = os.path.join(work, f"r_{rt}_{fl}_{tl}.csv")
            pd.DataFrame(rows, columns=["from", "to"] + cols).to_csv(f, index=False)
            con.execute(f"COPY {rt} FROM '{f}' (header=true, from='{fl}', to='{tl}', parallel=false)")

    # check counts
    loaded_n = sum(con.execute(f"MATCH (n:{lab}) RETURN count(n)").get_next()[0] for lab in schema["node_labels"])
    loaded_r = sum(con.execute(f"MATCH ()-[r:{rt}]->() RETURN count(r)").get_next()[0] for rt in schema["relationship_types"])

    md = ["# Schema test questions and answers\n",
          f"Graph loaded into Kuzu (embedded Cypher database): {loaded_n:,} nodes and {loaded_r:,} relationships "
          f"(build files: {len(nodes):,} and {len(rels):,}). Every query below was executed; the tables are the real results.\n",
          "**Keep this file out of both retrieval indexes.** It contains reference answers.\n",
          "Classes follow 10_Stack_and_Evaluation_Proposal. Level 1 = simple lookup, 2 = needs a second hop or a rule, "
          "3 = several hops or entity resolution, 4 = conflicting or unanswerable. Questions avoid claims 6977163, 6977175 and "
          "6977178 where possible, because those are in the pilot evaluation set (20_Eval_Questions_Pilot_3_Claims).\n",
          "| ID | Level | Class | Question |\n|---|---|---|---|"]
    for q in QUESTIONS:
        md.append(f"| {q['id']} | {q['level']} | {q['qclass']} | {q['question']} |")
    cy_out = ["// 03_schema_test_queries.cypher -- GENERATED by 03_code/03_run_schema_test_questions.py",
              "// Paste one query at a time into Neo4j Browser after loading 02_load_graph_generated.cypher.", ""]
    failures = 0
    for q in QUESTIONS:
        md.append(f"\n---\n\n## {q['id']} (level {q['level']}, {q['qclass']})\n\n**Question.** {q['question']}\n")
        md.append(f"**Schema path used.** {q['schema_path']}\n")
        for i, cyq in enumerate(q["cypher"], 1):
            cy_out += [f"// {q['id']}.{i}  {q['question']}", cyq + ";", ""]
            md.append(f"**Cypher {i}.**\n\n```cypher\n{cyq}\n```\n")
            try:
                df = con.execute(cyq).get_as_df().astype(object)
                df = df.map(lambda v: (round(v, 2) if isinstance(v, float) else v))
                md.append(f"**Result {i}** ({len(df)} rows):\n\n" + (df.to_markdown(index=False) if len(df) else "_no rows_") + "\n")
            except Exception as e:
                failures += 1
                md.append(f"**Result {i}: QUERY FAILED** `{str(e)[:300]}`\n")
        md.append(f"**Reference answer (written from the notes).** {q['reference_answer']}\n")
        md.append(f"**Evidence.** {q['evidence']}\n")
    open(os.path.join(OUT, "07_schema_test_questions_and_answers.md"), "w").write("\n".join(md) + "\n")
    open(os.path.join(ROOT, "04_neo4j", "03_schema_test_queries.cypher"), "w").write("\n".join(cy_out) + "\n")
    shutil.rmtree(work, ignore_errors=True)
    print(f"loaded nodes={loaded_n} rels={loaded_r}; questions={len(QUESTIONS)} failed_queries={failures}")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
