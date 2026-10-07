"""Build the demo knowledge graph from schema v0 and validate it.

What it does
  1. Loads the schema (schema/graph_schema_v0.yaml) and seed tables.
  2. Builds nodes and relationships from the demo data:
       - structured fields (public record + synthetic fields) -> deterministic edges
       - claim notes -> Document + Chunk nodes; MENTIONS edges by exact, claim-scoped string match
       - 3 short public WCB documents -> Document + Chunk nodes; MENTIONS of form codes
       - treatment guidelines -> Document nodes + curated COVERS_BODY_PART edges (no chunks here)
       - process seed -> ProcessStep / Form / Role nodes and their edges
  3. Validates every node and edge against the schema (labels, keys, required properties,
     allowed from/to labels, provenance fields, enum values).
  4. Writes nodes.csv, edges.csv, load_demo_graph.cypher, graph.json, graph_stats.md,
     competency_questions.md and a schema diagram (DOT, plus SVG/PNG if Graphviz is installed).

No LLM is used. Text-derived edges are rule-based and start as review_status = "unreviewed".

Usage
  python src/build_demo_graph.py \
      --notes data/GB_102_Synthetic_Notes.csv \
      --claims data/Assembled_Workers__Compensation_Claims.csv \
      --public-dir data/public_docs \
      --out out
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import subprocess
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import networkx as nx
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "0.1.0"

PUBLIC_DOCS = {
    "PUB-WCB-FACTSHEET": ("file-claim-fact-sheet.pdf", "process_guide", "Your workers' compensation benefits (file a claim fact sheet)"),
    "PUB-WCB-QUICKGUIDE": ("ClaimantInformationPacket.pdf", "process_guide", "Quick guide for injured workers"),
    "PUB-WCB-EMPREPORT": ("EMP-TimelyReporting.pdf", "process_guide", "Your responsibilities as an employer: reporting injury and illness"),
    "PUB-MTG-KNEE": ("KneeInjuryMTG2021.pdf", "treatment_guideline", "Medical Treatment Guidelines: Knee Injury"),
    "PUB-MTG-SHOULDER": ("ShoulderInjuryMTG2021.pdf", "treatment_guideline", "Medical Treatment Guidelines: Shoulder Injury"),
    "PUB-MTG-BACK": ("MidandLowBackInjuryMTG2021.pdf", "treatment_guideline", "Medical Treatment Guidelines: Mid and Low Back Injury"),
    "PUB-MTG-HAND": ("HandWristForarmMTG2021.pdf", "treatment_guideline", "Medical Treatment Guidelines: Hand, Wrist and Forearm Injuries"),
}
MTG_LICENSE = ("Adapted by NYS WCB from MDGuidelines (Reed Group). Viewing and printing for internal "
               "reference only; do not redistribute. Keep the PDF out of public repositories.")
FORM_PATTERN = re.compile(r"Form (C-3\.3|C-2F|C-257|C-3|DB-450)\b")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def slug(text: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "-", str(text).upper()).strip("-")


def norm_text(s: str) -> str:
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip()


def iso_date(value) -> str | None:
    if pd.isna(value):
        return None
    return datetime.strptime(str(value), "%m/%d/%Y").date().isoformat()


def none_if_zero(value):
    if pd.isna(value) or value == 0:
        return None
    return int(value)


def pdf_text(path: Path) -> str:
    out = subprocess.run(["pdftotext", str(path), "-"], capture_output=True, text=True, check=True)
    return out.stdout


class Graph:
    """Nodes keyed by (label, key value); edges with provenance."""

    def __init__(self, schema: dict):
        self.schema = schema
        self.nodes: dict[tuple, dict] = {}
        self.edges: list[dict] = []
        self.ambiguous: list[tuple] = []  # (chunk_id, matched text, candidate entities)
        self.checks: list[tuple] = []

    def key_prop(self, label: str) -> str:
        if label not in self.schema["nodes"]:
            raise ValueError(f"Label {label!r} is not in the schema; add it through change control first")
        return self.schema["nodes"][label]["key"]

    def add_node(self, label: str, key, **props) -> tuple:
        ref = (label, key)
        props[self.key_prop(label)] = key
        clean = {k: v for k, v in props.items() if v is not None}
        self.nodes.setdefault(ref, {}).update(clean)
        return ref

    def add_edge(self, rel: str, src: tuple, dst: tuple, **prov) -> None:
        prov.setdefault("schema_version", SCHEMA_VERSION)
        self.edges.append({"type": rel, "from": src, "to": dst,
                           "props": {k: v for k, v in prov.items() if v is not None}})


def structured(source_type: str, source_id: str, claim_id=None) -> dict:
    return dict(source_type=source_type, source_id=source_id, method="structured_field",
                review_status="approved", scope_claim_id=claim_id)


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
def build(args) -> Graph:
    schema = yaml.safe_load((ROOT / "schema" / "graph_schema_v0.yaml").read_text())
    g = Graph(schema)

    notes = pd.read_csv(args.notes)
    claim_ids = sorted(notes["Claim Identifier"].unique())
    record_cols = ["Claim Identifier", "Accident Date", "Assembly Date", "Age at Injury", "Gender",
                   "Attorney/Representative", "Claim Injury Type", "Claim Type", "Current Claim Status",
                   "Highest Process", "District Name", "Hearing Count", "County of Injury", "Carrier Name",
                   "Carrier Type", "Industry Code", "Industry Code Description",
                   "WCIO Nature of Injury Code", "WCIO Nature of Injury Description",
                   "WCIO Part Of Body Code", "WCIO Part Of Body Description",
                   "WCIO Cause of Injury Code", "WCIO Cause of Injury Description"]
    records = pd.read_csv(args.claims, usecols=record_cols, low_memory=False)
    records = records[records["Claim Identifier"].isin(claim_ids)].set_index("Claim Identifier")
    missing = set(claim_ids) - set(records.index)
    if missing:
        raise SystemExit(f"Claims missing from the public record file: {sorted(missing)}")

    per_claim = notes.drop_duplicates("Claim Identifier").set_index("Claim Identifier")
    claim_entities: dict[int, list[tuple]] = defaultdict(list)  # for claim-scoped MENTIONS
    checks = []

    # --- Claim layer -------------------------------------------------------
    for cid in claim_ids:
        cid = int(cid)
        r, s = records.loc[cid], per_claim.loc[cid]
        src = f"NYWCB:{cid}"
        claim = g.add_node("Claim", cid,
                           accident_date=iso_date(r["Accident Date"]),
                           assembly_date=iso_date(r["Assembly Date"]),
                           claim_injury_type=r["Claim Injury Type"],
                           current_status=r["Current Claim Status"],
                           highest_process=re.sub(r"\s+", " ", r["Highest Process"]),
                           district=r["District Name"],
                           attorney_represented=(r["Attorney/Representative"] == "Y"),
                           hearing_count=int(r["Hearing Count"]),
                           claim_type=re.sub(r"\s+", " ", r["Claim Type"]))
        claimant = g.add_node("Claimant", f"CLMT-{cid}", name=s["Synthetic Claimant"],
                              age_at_injury=none_if_zero(r["Age at Injury"]), gender=r["Gender"])
        g.add_edge("FILED_BY", claim, claimant, **structured("public_record", src, cid))

        carrier = g.add_node("Carrier", f"CAR-{slug(r['Carrier Name'])}", name=r["Carrier Name"],
                             carrier_type=r["Carrier Type"])
        g.add_edge("INSURED_BY", claim, carrier, **structured("public_record", src, cid))

        injury = g.add_node("Injury", int(r["WCIO Nature of Injury Code"]), name=r["WCIO Nature of Injury Description"])
        body = g.add_node("BodyPart", int(r["WCIO Part Of Body Code"]), name=r["WCIO Part Of Body Description"])
        cause = g.add_node("InjuryCause", int(r["WCIO Cause of Injury Code"]), name=r["WCIO Cause of Injury Description"])
        county = g.add_node("County", str(r["County of Injury"]).upper())
        industry = g.add_node("Industry", int(r["Industry Code"]), name=r["Industry Code Description"])
        for rel, node in [("HAS_INJURY", injury), ("AFFECTS_BODY_PART", body), ("CAUSED_BY", cause),
                          ("OCCURRED_IN", county), ("IN_INDUSTRY", industry)]:
            g.add_edge(rel, claim, node, **structured("public_record", src, cid))

        syn = f"GB102:{cid}"
        employer = g.add_node("Employer", f"EMP-{slug(s['Synthetic Employer'])}", name=s["Synthetic Employer"])
        adjuster = g.add_node("Adjuster", f"ADJ-{slug(s['Synthetic Adjuster'])}", name=s["Synthetic Adjuster"])
        provider = g.add_node("Provider", f"PRV-{slug(s['Synthetic Provider'])}", name=s["Synthetic Provider"])
        location = g.add_node("Location", f"LOC-{slug(s['Synthetic Location'])}", name=s["Synthetic Location"])
        for rel, node in [("INVOLVES_EMPLOYER", employer), ("HANDLED_BY", adjuster),
                          ("TREATED_BY", provider), ("OCCURRED_AT", location)]:
            g.add_edge(rel, claim, node, **structured("synthetic_field", syn, cid))
        loc_county = s["Synthetic Location"].split(" County")[0].upper()
        checks.append(("location county = record county", cid, loc_county == county[1]))
        loc_county_node = g.add_node("County", loc_county)
        if not any(e["type"] == "IN_COUNTY" and e["from"] == location for e in g.edges):
            g.add_edge("IN_COUNTY", location, loc_county_node, **structured("synthetic_field", syn))

        claim_entities[cid] = [claim, claimant, carrier, injury, body, cause, county, industry,
                               employer, adjuster, provider, location]

    # --- Claim notes: Document + Chunk + MENTIONS ---------------------------
    def mention_terms(ref: tuple) -> list[str]:
        label, key = ref
        props = g.nodes[ref]
        if label == "Claim":
            return [str(key)]
        if label == "County":
            return [f"{key.title()} County"]
        return [props["name"]] if props.get("name") else []

    for _, n in notes.iterrows():
        cid, doc_id = int(n["Claim Identifier"]), n["Note ID"]
        doc = g.add_node("Document", doc_id, doc_type="claim_note", note_type=n["Note Type"],
                         is_synthetic=True, title=f"{n['Note Type']} for claim {cid}")
        g.add_edge("ABOUT_CLAIM", doc, ("Claim", cid), **structured("synthetic_note", doc_id, cid))
        text = n["Synthetic Note Text"]
        chunk = g.add_node("Chunk", f"{doc_id}#0", text=text, position=0, n_words=len(text.split()))
        g.add_edge("HAS_CHUNK", doc, chunk, **structured("synthetic_note", doc_id, cid))
        # Every occurrence of every claim-scoped entity name, then: longest span wins,
        # overlapping shorter spans are dropped ("Manufacturing" inside "Northstar Manufacturing"),
        # and a span that matches two different entities is ambiguous: logged, not linked.
        low = text.lower()
        cands = defaultdict(set)
        for ref in claim_entities[cid]:
            for term in mention_terms(ref):
                t = term.lower()
                start = low.find(t)
                while start >= 0:
                    cands[(start, start + len(t))].add(ref)
                    start = low.find(t, start + 1)
        taken, linked = [], set()
        for (s0, e0), refs in sorted(cands.items(), key=lambda x: (-(x[0][1] - x[0][0]), x[0][0])):
            if any(s0 < e1 and s1 < e0 for s1, e1 in taken):
                continue
            taken.append((s0, e0))
            if len(refs) > 1:
                g.ambiguous.append((chunk[1], text[s0:e0], sorted(f"{l}:{k}" for l, k in refs)))
                continue
            ref = next(iter(refs))
            if ref in linked:
                continue
            linked.add(ref)
            g.add_edge("MENTIONS", chunk, ref, source_type="synthetic_note", source_id=doc_id,
                       method="rule_match", review_status="unreviewed", chunk_id=chunk[1],
                       span_start=s0, span_end=e0, scope_claim_id=cid)

    # --- Public documents ----------------------------------------------------
    public_dir = Path(args.public_dir) if args.public_dir else None
    chunk_texts: dict[str, list[tuple]] = {}
    for doc_id, (fname, dtype, title) in PUBLIC_DOCS.items():
        doc = g.add_node("Document", doc_id, doc_type=dtype, is_synthetic=False, title=title, path=fname,
                         license_note=MTG_LICENSE if dtype == "treatment_guideline" else None)
        if dtype != "process_guide" or public_dir is None or not (public_dir / fname).exists():
            continue
        words = norm_text(pdf_text(public_dir / fname)).split(" ")
        prev = None
        chunk_texts[doc_id] = []
        for i in range(0, len(words), args.chunk_words):
            text = " ".join(words[i:i + args.chunk_words])
            ck = g.add_node("Chunk", f"{doc_id}#{i // args.chunk_words}", text=text,
                            position=i // args.chunk_words, n_words=len(text.split()))
            chunk_texts[doc_id].append((ck, text))
            g.add_edge("HAS_CHUNK", doc, ck, **structured("public_document", doc_id))
            if prev:
                g.add_edge("NEXT_CHUNK", prev, ck, **structured("public_document", doc_id))
            prev = ck

    # --- Process seed: Role, Form, ProcessStep ------------------------------
    seed = ROOT / "seed"
    roles = pd.read_csv(seed / "roles_seed.csv", keep_default_na=False)
    for _, r in roles.iterrows():
        g.add_node("Role", r["role_name"], instance_label=r["instance_label"] or "none", description=r["description"])
    forms = pd.read_csv(seed / "forms_seed.csv")
    for _, f in forms.iterrows():
        g.add_node("Form", f["form_code"], name=f["name"])
    steps = pd.read_csv(seed / "process_steps_seed.csv", dtype=str, keep_default_na=False)
    for _, st in steps.iterrows():
        step = g.add_node("ProcessStep", st["step_id"], name=st["name"],
                          deadline_text=st["deadline_text"] or None,
                          deadline_days=int(st["deadline_days"]) if st["deadline_days"] else None,
                          condition=st["condition"] or None)
    for _, st in steps.iterrows():
        step = ("ProcessStep", st["step_id"])
        prov = dict(source_type="curated", source_id=f"process_steps_seed.csv:{st['step_id']}",
                    method="curated_table", review_status=st["review_status"])
        for role in st["performed_by_role"].split(";"):
            g.add_edge("PERFORMED_BY", step, ("Role", role), **prov)
        if st["form_code"]:
            g.add_edge("USES_FORM", step, ("Form", st["form_code"]), **prov)
        if st["precedes_step_id"]:
            g.add_edge("PRECEDES", step, ("ProcessStep", st["precedes_step_id"]), **prov)
        quote_head = norm_text(st["source_quote"])[:60]
        chunk_id = next((ck[1] for ck, text in chunk_texts.get(st["source_doc_id"], []) if quote_head in text), None)
        g.add_edge("DESCRIBED_IN", step, ("Document", st["source_doc_id"]), chunk_id=chunk_id, **prov)

    # Form mentions in public chunks
    for doc_id, cks in chunk_texts.items():
        for ck, text in cks:
            seen = set()
            for m in FORM_PATTERN.finditer(text):
                code = m.group(1)
                if code in seen:
                    continue
                seen.add(code)
                g.add_edge("MENTIONS", ck, ("Form", code), source_type="public_document", source_id=doc_id,
                           method="rule_match", review_status="unreviewed", chunk_id=ck[1],
                           span_start=m.start(), span_end=m.end())

    # --- Guideline coverage (curated table) ---------------------------------
    gmap = pd.read_csv(ROOT / "schema" / "body_part_guideline_map.csv", dtype=str, keep_default_na=False)
    for _, row in gmap.iterrows():
        if not row["guideline_doc_id"]:
            continue
        body = g.add_node("BodyPart", int(row["wcio_body_code"]), name=row["body_part_name"])
        g.add_edge("COVERS_BODY_PART", ("Document", row["guideline_doc_id"]), body,
                   source_type="curated", source_id=f"body_part_guideline_map.csv:{row['wcio_body_code']}",
                   method="curated_table", review_status="unreviewed")

    g.checks = checks
    return g


# ---------------------------------------------------------------------------
# Validation against the schema
# ---------------------------------------------------------------------------
def validate(g: Graph) -> list[str]:
    sch, errors = g.schema, []
    prov_req = sch["edge_provenance"]["required"]
    for (label, key), props in g.nodes.items():
        spec = sch["nodes"].get(label)
        if spec is None:
            errors.append(f"unknown label {label}")
            continue
        for p in spec["required_props"]:
            if props.get(p) in (None, ""):
                errors.append(f"{label}:{key} missing required property {p}")
        for prop, allowed in spec.get("enums", {}).items():
            if prop in props and props[prop] not in allowed:
                errors.append(f"{label}:{key} {prop}={props[prop]!r} not in enum")
        allowed_props = set(spec["required_props"]) | set(spec["optional_props"])
        extra = set(props) - allowed_props
        if extra:
            errors.append(f"{label}:{key} has properties not in schema: {sorted(extra)}")
    for e in g.edges:
        spec = sch["relationships"].get(e["type"])
        if spec is None:
            errors.append(f"unknown relationship {e['type']}")
            continue
        targets = spec["to"] if isinstance(spec["to"], list) else [spec["to"]]
        if e["from"][0] != spec["from"] or e["to"][0] not in targets:
            errors.append(f"{e['type']} not allowed from {e['from'][0]} to {e['to'][0]}")
        for ref in (e["from"], e["to"]):
            if ref not in g.nodes:
                errors.append(f"{e['type']} points to missing node {ref}")
        for field, allowed in prov_req.items():
            val = e["props"].get(field)
            if val is None:
                errors.append(f"{e['type']} {e['from']}->{e['to']} missing provenance {field}")
            elif isinstance(allowed, list) and val not in allowed:
                errors.append(f"{e['type']} provenance {field}={val!r} not in enum")
    return errors


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------
def cypher_literal(props: dict) -> str:
    return "{" + ", ".join(f"{k}: {json.dumps(v)}" for k, v in props.items()) + "}"


def write_outputs(g: Graph, errors: list[str], out: Path) -> nx.MultiDiGraph:
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "nodes.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["label", "key", "properties_json"])
        for (label, key), props in sorted(g.nodes.items(), key=lambda x: (x[0][0], str(x[0][1]))):
            w.writerow([label, key, json.dumps(props, ensure_ascii=False)])
    with open(out / "edges.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["type", "from_label", "from_key", "to_label", "to_key", "properties_json"])
        for e in g.edges:
            w.writerow([e["type"], *e["from"], *e["to"], json.dumps(e["props"], ensure_ascii=False)])

    lines = ["// Generated by src/build_demo_graph.py. Run neo4j/constraints.cypher first.",
             "// Not yet executed against a Neo4j server; report any syntax problems in the repo."]
    for (label, key), props in g.nodes.items():
        kp = g.key_prop(label)
        rest = {k: v for k, v in props.items() if k != kp}
        lines.append(f"MERGE (n:{label} {{{kp}: {json.dumps(key)}}}) SET n += {cypher_literal(rest)};")
    for e in g.edges:
        (fl, fk), (tl, tk) = e["from"], e["to"]
        lines.append(f"MATCH (a:{fl} {{{g.key_prop(fl)}: {json.dumps(fk)}}}), (b:{tl} {{{g.key_prop(tl)}: {json.dumps(tk)}}}) "
                     f"CREATE (a)-[:{e['type']} {cypher_literal(e['props'])}]->(b);")
    (out / "load_demo_graph.cypher").write_text("\n".join(lines) + "\n")

    G = nx.MultiDiGraph()
    for ref, props in g.nodes.items():
        G.add_node(ref, **props)
    for e in g.edges:
        G.add_edge(e["from"], e["to"], key=e["type"], **e["props"])

    gj = {"nodes": [{"id": f"{l}:{k}", "label": l, "name": p.get("name") or p.get("title") or str(k)}
                    for (l, k), p in g.nodes.items() if l != "Chunk"],
          "links": [{"source": f"{e['from'][0]}:{e['from'][1]}", "target": f"{e['to'][0]}:{e['to'][1]}", "type": e["type"]}
                    for e in g.edges if "Chunk" not in (e["from"][0], e["to"][0])]}
    (out / "graph.json").write_text(json.dumps(gj, indent=1, ensure_ascii=False))
    return G


def stats_report(g: Graph, G: nx.MultiDiGraph, errors: list[str]) -> str:
    nc = Counter(l for l, _ in g.nodes)
    ec = Counter(e["type"] for e in g.edges)
    claims = [r for r in g.nodes if r[0] == "Claim"]
    lines = ["# Demo graph statistics", "",
             f"Schema version {SCHEMA_VERSION}. Built {datetime.now().date().isoformat()} by src/build_demo_graph.py.", "",
             f"**Validation errors: {len(errors)}**", ""]
    lines += [f"- {e}" for e in errors[:50]]
    lines += ["", "## Nodes by label", "", "| Label | Count |", "| --- | --- |"]
    lines += [f"| {l} | {c} |" for l, c in sorted(nc.items())]
    lines += [f"| **Total** | **{sum(nc.values())}** |", "", "## Relationships by type", "", "| Type | Count |", "| --- | --- |"]
    lines += [f"| {t} | {c} |" for t, c in sorted(ec.items())]
    lines += [f"| **Total** | **{sum(ec.values())}** |", ""]

    lines += ["## Mandatory coverage (share of claims with each claim-layer relationship)", "",
              "| Relationship | Claims covered |", "| --- | --- |"]
    for rel, spec in g.schema["relationships"].items():
        if spec["from"] == "Claim" and spec["layer"] == "claim":
            n = sum(1 for c in claims if any(k == rel for _, _, k in G.out_edges(c, keys=True)))
            lines.append(f"| {rel} | {n} / {len(claims)} |")

    lines += ["", "## Hub nodes (most claims attached)", "", "| Node | Claims |", "| --- | --- |"]
    hubs = []
    for ref in g.nodes:
        if ref[0] in ("BodyPart", "Carrier", "Injury", "InjuryCause", "County", "Industry", "Adjuster", "Provider", "Employer"):
            n = sum(1 for u, _, k in G.in_edges(ref, keys=True) if u[0] == "Claim")
            hubs.append((n, ref))
    for n, ref in sorted(hubs, reverse=True)[:8]:
        lines.append(f"| {ref[0]}: {g.nodes[ref].get('name', ref[1])} | {n} |")

    by_name = defaultdict(set)
    for (l, k), p in g.nodes.items():
        if l in ("Claimant", "Adjuster", "Provider", "Employer") and p.get("name"):
            by_name[p["name"]].add(l)
    coll = {n: sorted(ls) for n, ls in by_name.items() if len(ls) > 1}
    lines += ["", "## Same name under different person labels (kept as separate nodes)", ""]
    lines += [f"- {n}: {', '.join(ls)}" for n, ls in sorted(coll.items())] or ["- none"]

    same = []
    for c in claims:
        out_ = {k: v for _, v, k in G.out_edges(c, keys=True)}
        cl, ad = out_.get("FILED_BY"), out_.get("HANDLED_BY")
        if cl and ad and g.nodes[cl].get("name") == g.nodes[ad].get("name"):
            same.append(f"{c[1]} ({g.nodes[cl]['name']})")
    lines += ["", "## Claims where the claimant and the adjuster have the same name (synthetic data error)", ""]
    lines += [f"- {s}" for s in same] or ["- none"]

    lines += ["", "## Ambiguous mentions (one span matches two entities; not linked, needs review)", ""]
    lines += [f"- `{ck}` \"{txt}\": {', '.join(c)}" for ck, txt, c in g.ambiguous] or ["- none"]

    failed = [c for c in g.checks if not c[2]]
    lines += ["", "## Data checks", "", f"- Location county equals record county: {len(g.checks) - len(failed)} / {len(g.checks)} claims"]
    orphans = [r for r in G.nodes if G.degree(r) == 0]
    lines += [f"- Nodes with no relationships: {len(orphans)}" + (f" ({', '.join(f'{l}:{k}' for l, k in orphans)})" if orphans else "")]
    unrev = sum(1 for e in g.edges if e["props"]["review_status"] == "unreviewed")
    lines += [f"- Relationships awaiting human review: {unrev} of {len(g.edges)}"]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Competency questions: can the schema answer the project's question types?
# ---------------------------------------------------------------------------
def competency(g: Graph, G: nx.MultiDiGraph) -> str:
    def out(ref, rel):
        return [v for _, v, k in G.out_edges(ref, keys=True) if k == rel]

    def inn(ref, rel):
        return [u for u, _, k in G.in_edges(ref, keys=True) if k == rel]

    name = lambda r: g.nodes[r].get("name", r[1])
    md = ["# Competency questions on the demo graph", "",
          "Each question tests whether the schema can answer a project question type. Answers are computed "
          "in Python (networkx) on the same nodes and relationships the Cypher file loads. The Cypher is the "
          "equivalent query for Neo4j; it has not been run against a Neo4j server yet.", ""]

    c = ("Claim", 6977119)
    adj, prv, car = out(c, "HANDLED_BY")[0], out(c, "TREATED_BY")[0], out(c, "INSURED_BY")[0]
    body = out(c, "AFFECTS_BODY_PART")[0]
    md += ["## CQ1 Direct lookup: who handles claim 6977119, who treats it, who insures it, which body part?", "",
           f"Adjuster **{name(adj)}**, provider **{name(prv)}**, carrier **{name(car)}**, body part **{name(body)}**.", "",
           "```cypher\nMATCH (c:Claim {claim_id: 6977119})\nOPTIONAL MATCH (c)-[:HANDLED_BY]->(a:Adjuster)\n"
           "OPTIONAL MATCH (c)-[:TREATED_BY]->(p:Provider)\nOPTIONAL MATCH (c)-[:INSURED_BY]->(k:Carrier)\n"
           "OPTIONAL MATCH (c)-[:AFFECTS_BODY_PART]->(b:BodyPart)\nRETURN a.name, p.name, k.name, b.name\n```", ""]

    others = sorted(r[1] for r in inn(adj, "HANDLED_BY") if r != c)
    md += [f"## CQ2 Cross-claim, 2 hops: which other claims does {name(adj)} (adjuster) handle?", "",
           f"{len(others)} other claims: {', '.join(map(str, others))}.", "",
           "```cypher\nMATCH (:Claim {claim_id: 6977119})-[:HANDLED_BY]->(a:Adjuster)<-[:HANDLED_BY]-(o:Claim)\n"
           "WHERE o.claim_id <> 6977119\nRETURN a.name, collect(o.claim_id)\n```", ""]

    rows = []
    for cl in sorted(r for r in g.nodes if r[0] == "Claim"):
        b = out(cl, "AFFECTS_BODY_PART")[0]
        for d in inn(b, "COVERS_BODY_PART"):
            rows.append(f"| {cl[1]} | {name(b)} | {g.nodes[d]['title']} |")
    md += ["## CQ3 Claim to public document, 2 hops: which treatment guideline covers each claim's injured body part?", "",
           "| Claim | Body part | Guideline (mapping awaiting review) |", "| --- | --- | --- |", *rows, "",
           f"{len(rows)} of {sum(1 for r in g.nodes if r[0] == 'Claim')} demo claims reach a guideline; the rest have body parts "
           "with no uploaded guideline or a mapping still under review (see schema/body_part_guideline_map.csv).", "",
           "```cypher\nMATCH (c:Claim)-[:AFFECTS_BODY_PART]->(b:BodyPart)<-[:COVERS_BODY_PART]-(d:Document {doc_type: 'treatment_guideline'})\n"
           "RETURN c.claim_id, b.name, d.title\n```", ""]

    role = ("Role", "Claimant")
    steps = sorted(inn(role, "PERFORMED_BY"), key=lambda r: r[1])
    rows = []
    for st in steps:
        forms = ", ".join(f[1] for f in out(st, "USES_FORM")) or "none"
        rows.append(f"| {st[1]} | {name(st)} | {forms} | {g.nodes[st].get('deadline_text', 'not stated')} |")
    md += ["## CQ4 Process: what must the claimant do, with which form, and by when?", "",
           "| Step | Action | Form | Deadline |", "| --- | --- | --- | --- |", *rows, "",
           "```cypher\nMATCH (s:ProcessStep)-[:PERFORMED_BY]->(:Role {role_name: 'Claimant'})\n"
           "OPTIONAL MATCH (s)-[:USES_FORM]->(f:Form)\nRETURN s.step_id, s.name, collect(f.form_code), s.deadline_text ORDER BY s.step_id\n```", ""]

    support = [(u, d) for u, v, k, d in G.in_edges(adj, keys=True, data=True) if k == "MENTIONS" and d.get("scope_claim_id") == 6977119]
    md += [f"## CQ5 Traceability: which text supports \"claim 6977119 is handled by {name(adj)}\"?", "",
           "The HANDLED_BY edge comes from the synthetic record field (method structured_field). "
           f"Text evidence: {len(support)} chunk(s) mention the adjuster within claim 6977119's notes:", ""]
    for u, d in support:
        t = g.nodes[u]["text"]
        md.append(f"- `{u[1]}` characters {d['span_start']} to {d['span_end']}: \"...{t[max(0, d['span_start'] - 30):d['span_end'] + 30]}...\"")
    md += ["", "```cypher\nMATCH (ch:Chunk)-[m:MENTIONS]->(a:Adjuster)<-[:HANDLED_BY]-(c:Claim {claim_id: 6977119})\n"
           "WHERE m.scope_claim_id = 6977119\nRETURN ch.chunk_id, m.span_start, m.span_end, ch.text\n```", ""]

    people = [r for r in g.nodes if r[0] in ("Claimant", "Adjuster") and g.nodes[r].get("name") == "Maya Patel"]
    md += ["## CQ6 Entity resolution: is \"Maya Patel\" one person or two?", ""]
    for p in sorted(people):
        rel = "FILED_BY" if p[0] == "Claimant" else "HANDLED_BY"
        cl = sorted(r[1] for r in inn(p, rel))
        md.append(f"- `{p[0]}:{p[1]}` linked to claim(s) {', '.join(map(str, cl))}")
    md += ["", "The schema keys people by role and ID, never by name, so the claimant and the adjuster stay separate "
           "nodes; merging by name would join them. In this demo set the two even share claim 6977140, which "
           "is a synthetic-data error (an adjuster would not handle their own claim) to fix in the data generator.", ""]
    return "\n".join(md) + "\n"


def write_diagram(g: Graph, out: Path) -> None:
    nc = Counter(l for l, _ in g.nodes)
    layer_style = {"claim": ("#E8F0FB", "#2F6DB5"), "text": ("#EEF6EC", "#3E8E41"),
                   "process": ("#FFF4E5", "#C77700"), "reserved": ("#F2F2F2", "#888888")}
    titles = {"claim": "Claim layer (public record + synthetic fields)", "text": "Text layer (retrieval)",
              "process": "Process knowledge layer (public WCB documents)", "reserved": "Reserved for v1 (not in demo data)"}
    lines = ["digraph schema {", '  graph [rankdir=LR, fontname="Helvetica", fontsize=12, nodesep=0.35, ranksep=0.7, pad=0.3];',
             '  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=11];',
             '  edge [fontname="Helvetica", fontsize=9, color="#666666"];']
    for layer, (fill, line) in layer_style.items():
        lines.append(f'  subgraph cluster_{layer} {{ label="{titles[layer]}"; style="rounded,dashed"; color="{line}"; fontcolor="{line}";')
        for label, spec in g.schema["nodes"].items():
            if spec["layer"] == layer:
                req = "" if spec["requirement"] == "mandatory" else "\\n(optional)"
                lines.append(f'    {label} [label="{label} ({nc.get(label, 0)}){req}", fillcolor="{fill}", color="{line}"];')
        lines.append("  }")
    event_links = [r for r, s in g.schema["relationships"].items() if s["from"] == s["to"] == "ClaimEvent"]
    if event_links:
        lines.append(f'  ClaimEvent -> ClaimEvent [label="{" / ".join(event_links)}", style=dashed, color="#999999"];')
    for rel, spec in g.schema["relationships"].items():
        if rel in event_links:
            continue
        if rel == "MENTIONS":
            lines.append('  Chunk -> Claim [label="MENTIONS (any entity)", style=dashed];')
            continue
        style = ', style=dashed, color="#999999"' if spec["layer"] == "reserved" else ""
        lines.append(f'  {spec["from"]} -> {spec["to"]} [label="{rel}"{style}];')
    lines.append("}")
    dot = out / "schema_diagram.dot"
    dot.write_text("\n".join(lines) + "\n")
    if shutil.which("dot"):
        for fmt in ("svg", "png"):
            subprocess.run(["dot", f"-T{fmt}", "-Gdpi=160" if fmt == "png" else "-Gdpi=72", str(dot), "-o", str(out / f"schema_diagram.{fmt}")], check=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--notes", required=True, help="GB_102_Synthetic_Notes.csv")
    ap.add_argument("--claims", required=True, help="NY Assembled Workers' Compensation Claims CSV (for WCIO codes and record fields)")
    ap.add_argument("--public-dir", default=None, help="folder with the public WCB PDFs")
    ap.add_argument("--out", default=str(ROOT / "out"))
    ap.add_argument("--chunk-words", type=int, default=150)
    args = ap.parse_args()
    out = Path(args.out)

    g = build(args)
    errors = validate(g)
    G = write_outputs(g, errors, out)
    (out / "graph_stats.md").write_text(stats_report(g, G, errors))
    (out / "competency_questions.md").write_text(competency(g, G))
    write_diagram(g, out)
    print(f"nodes={len(g.nodes)} edges={len(g.edges)} validation_errors={len(errors)} -> {out}")
    for e in errors[:20]:
        print("  ERROR", e)


if __name__ == "__main__":
    main()
