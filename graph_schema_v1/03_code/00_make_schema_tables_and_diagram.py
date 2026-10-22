"""
00_make_schema_tables_and_diagram.py

Reads 01_schema/01_graph_schema_definition_v1.yaml (the single source of truth) and writes the
human-readable versions next to it:
    01_schema/02_entity_definitions.csv        one row per node label
    01_schema/03_relationship_definitions.csv  one row per relationship type and (from -> to) pair
    01_schema/05_schema_diagram.svg / .png     layered diagram (needs Graphviz 'dot' installed)
If 05_outputs/02_graph_nodes_all.csv exists, counts from the last build are added.

Run from graph_schema_v1/:   python 03_code/00_make_schema_tables_and_diagram.py
"""
import csv, json, os, shutil, subprocess
from collections import Counter

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = os.path.join(ROOT, "01_schema")

EXAMPLE_KEYS = {
    "Claim": "6977160", "Claimant": "CLMT-6977160", "Employer": "EMP-city-operations-department",
    "Carrier": "CAR-state-insurance-fund", "County": "Rockland", "IncidentLocation": "LOC-rockland-county-warehouse",
    "InjuryNature": "NAT-strain-or-tear", "BodyPart": "BP-wcio-multiple / BP-specific-low-back",
    "InjuryCause": "CAU-motor-vehicle-collision-or-sideswipe-with-another-vehicle", "ClaimsStaff": "STAFF-daniel-brooks",
    "EmployerContact": "ERC-frank-nakamura-city-operations-department", "HealthcareFacility": "FAC-upstate-hearing-and-balance-center",
    "Clinician": "CLIN-haddad-upstate-hearing-and-balance-center", "Attorney": "ATTY-alicia-romano-romanolaw",
    "Diagnosis": "DX-6977160-strain-of-the-low-back-hip-and-both-knees", "Treatment": "physical-therapy",
    "Medication": "tylenol", "Note": "SYN-6977160-024", "Chunk": "SYN-6977160-024-C01", "Document": "RD15",
    "ClaimEvent": "EV-6977160-hearing_held-<hash>", "ProcessStep": "PS10", "Form": "C-257", "Role": "claimant",
}
SOURCE = {
    "L1_claim_record": "Structured columns of the notes file (same value on every note of a claim)",
    "L2_people_and_orgs": "Note headers (author, role) and note text (names, pasted emails)",
    "L3_medical": "Note text (dx phrases, plans, medication lists)",
    "L4_notes_and_text": "The notes file itself; reference documents once downloaded",
    "L5_claim_events": "Note text, by extraction rules (or the team's LLM / System 1 extractor)",
    "L6_process_knowledge": "02_reference_data seed files built from public WCB documents",
}


def main():
    sc = yaml.safe_load(open(os.path.join(S, "01_graph_schema_definition_v1.yaml")))
    ncount, rcount = Counter(), Counter()
    nf = os.path.join(ROOT, "05_outputs", "02_graph_nodes_all.csv")
    rf = os.path.join(ROOT, "05_outputs", "03_graph_relationships_all.csv")
    if os.path.exists(nf):
        ncount = Counter(r["label"] for r in csv.DictReader(open(nf)))
        rcount = Counter((r["type"], r["from_node_id"].split(":")[0], r["to_node_id"].split(":")[0]) for r in csv.DictReader(open(rf)))

    with open(os.path.join(S, "02_entity_definitions.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["layer", "node_label", "what_it_is", "key_property", "example_key", "properties", "where_it_comes_from", "required_for_every_claim", "count_in_last_build"])
        for lab, spec in sc["node_labels"].items():
            w.writerow([spec["layer"], lab, spec["description"], spec["key"], EXAMPLE_KEYS.get(lab, ""),
                        "; ".join(spec["properties"]), SOURCE[spec["layer"]], "yes" if spec["required"] else "no", ncount.get(lab, "")])
    with open(os.path.join(S, "03_relationship_definitions.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["layer", "relationship_type", "from_label", "to_label", "meaning", "created_by", "count_in_last_build"])
        for rt, spec in sc["relationship_types"].items():
            for a in spec["from"]:
                for b in spec["to"]:
                    w.writerow([spec["layer"], rt, a, b, spec["meaning"], spec["created_by"], rcount.get((rt, a, b), "")])

    # ------------------------------------------------------------------ diagram
    colors = {"L1_claim_record": "#E8F1FB", "L2_people_and_orgs": "#EAF6EC", "L3_medical": "#FDF3E4",
              "L4_notes_and_text": "#F1EEF8", "L5_claim_events": "#FCE9EC", "L6_process_knowledge": "#EEF2F3"}
    titles = {"L1_claim_record": "1. Claim record", "L2_people_and_orgs": "2. People and organizations", "L3_medical": "3. Medical",
              "L4_notes_and_text": "4. Notes and text", "L5_claim_events": "5. Claim events", "L6_process_knowledge": "6. Public process knowledge"}
    lines = ['digraph G {', 'graph [rankdir=LR, compound=true, fontname="Helvetica", fontsize=12, nodesep=0.25, ranksep=0.7, pad=0.3, labelloc=t, label="GraphRAG schema v1: 24 node labels, 42 relationship types. Solid box = present for every claim; dashed box = present when the notes mention it; dashed arrow = goes to any person or organization. Numbers = nodes in the last build."];',
             'node [shape=box, style="rounded,filled", fillcolor=white, fontname="Helvetica", fontsize=11, penwidth=1];',
             'edge [fontname="Helvetica", fontsize=8, color="#666666", arrowsize=0.6];']
    for layer, t in titles.items():
        lines.append(f'subgraph cluster_{layer} {{ label="{t}"; style="rounded,filled"; fillcolor="{colors[layer]}"; color="#BBBBBB";')
        for lab, spec in sc["node_labels"].items():
            if spec["layer"] == layer:
                n = ncount.get(lab, "")
                lines.append(f'  {lab} [label="{lab}' + (f'\\n({n:,})' if n else '') + '"' + ('' if spec["required"] else ', style="rounded,filled,dashed"') + '];')
        lines.append('}')
    many = {"MENTIONS": ("Chunk", "ClaimsStaff", "cluster_L2_people_and_orgs"), "INVOLVES": ("ClaimEvent", "Clinician", "cluster_L2_people_and_orgs"),
            "CONTAINS_MESSAGE_FROM": ("Note", "Attorney", "cluster_L2_people_and_orgs"), "WRITTEN_BY": ("Note", "ClaimsStaff", "cluster_L2_people_and_orgs")}
    for rt, spec in sc["relationship_types"].items():
        if rt in many:
            a, b, cl = many[rt]
            lines.append(f'{a} -> {b} [label="{rt}", lhead={cl}, style=dashed];')
            continue
        for a in spec["from"]:
            for b in spec["to"]:
                if a == b:
                    lines.append(f'{a} -> {b} [label="{rt}"];')
                else:
                    lines.append(f'{a} -> {b} [label="{rt}"];')
    lines.append('}')
    dot = os.path.join(S, "05_schema_diagram.dot")
    open(dot, "w").write("\n".join(lines))
    if shutil.which("dot"):
        for fmt in ("svg", "png"):
            subprocess.run(["dot", f"-T{fmt}", "-Gdpi=150" if fmt == "png" else "-Gdpi=72", dot, "-o", os.path.join(S, f"05_schema_diagram.{fmt}")], check=True)
        print("diagram written")
    else:
        print("Graphviz not installed: only the .dot file was written")
    print("tables written")


if __name__ == "__main__":
    main()
