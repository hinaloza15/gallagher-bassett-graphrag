from pathlib import Path
import ast
import json
import math
import os
import pandas as pd
import yaml
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

SCHEMA_FILE = Path("schema/graph_schema_definition_v1.yaml")
NODES_FILE = Path("data/graph/nodes.csv")
RELS_FILE = Path("data/graph/relationships.csv")

URI = os.getenv("NEO4J_URI")
USER = os.getenv("NEO4J_USER", "neo4j")
PASSWORD = os.getenv("NEO4J_PASSWORD")
DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")


def normalize_claim_id(value):
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text


def parse_value(v):
    if pd.isna(v):
        return None
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        if s in {"True", "False"}:
            return s == "True"
        if s.startswith("[") and s.endswith("]"):
            try:
                return ast.literal_eval(s)
            except Exception:
                return s
        return s
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


def clean_props(row, excluded):
    props = {}
    for k, v in row.items():
        if k in excluded:
            continue
        if k == "claim_id":
            parsed = normalize_claim_id(v)
        else:
            parsed = parse_value(v)
        if parsed is not None:
            props[k] = parsed
    return props


def main():
    if not URI or not PASSWORD:
        raise RuntimeError("Set NEO4J_URI, NEO4J_USER and NEO4J_PASSWORD in .env")

    with open(SCHEMA_FILE, "r", encoding="utf-8") as f:
        schema = yaml.safe_load(f)

    allowed_labels = set(schema["node_labels"].keys())
    allowed_rel_types = set(schema["relationship_types"].keys())
    key_by_label = {label: spec["key"] for label, spec in schema["node_labels"].items()}

    nodes = pd.read_csv(NODES_FILE)
    rels = pd.read_csv(RELS_FILE)

    bad_labels = set(nodes["label"]) - allowed_labels
    bad_rels = set(rels["type"]) - allowed_rel_types
    if bad_labels:
        raise ValueError(f"Unknown labels: {sorted(bad_labels)}")
    if bad_rels:
        raise ValueError(f"Unknown relationship types: {sorted(bad_rels)}")

    driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))

    with driver.session(database=DATABASE) as session:
        session.run("RETURN 1").consume()
        print("Connected to Neo4j")

        for label in sorted(set(nodes["label"])):
            key = key_by_label[label]
            session.run(
                f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:`{label}`) REQUIRE n.`{key}` IS UNIQUE"
            ).consume()

        for label, group in nodes.groupby("label"):
            key = key_by_label[label]
            rows = []
            for _, row in group.iterrows():
                props = clean_props(row.to_dict(), {"label", "key_name", "key_value"})
                key_value = str(row["key_value"]).strip()
                if label == "Claim":
                    key_value = normalize_claim_id(key_value)
                props[key] = key_value
                rows.append({"key": key_value, "props": props})

            q = f"""
            UNWIND $rows AS row
            MERGE (n:`{label}` {{`{key}`: row.key}})
            SET n += row.props
            """
            for i in range(0, len(rows), 500):
                session.run(q, rows=rows[i:i+500]).consume()
            print(f"Loaded {label}: {len(rows)}")

        group_cols = ["start_label", "start_key", "type", "end_label", "end_key"]
        for keys, group in rels.groupby(group_cols):
            start_label, start_key, rel_type, end_label, end_key = keys
            rows = []
            for _, row in group.iterrows():
                raw_props = row.get("properties_json")
                props = json.loads(raw_props) if isinstance(raw_props, str) and raw_props.strip() else {}
                if "scope_claim_id" in props:
                    props["scope_claim_id"] = normalize_claim_id(props["scope_claim_id"])

                start_value = str(row["start_value"]).strip()
                end_value = str(row["end_value"]).strip()
                if start_label == "Claim" and start_key == "claim_id":
                    start_value = normalize_claim_id(start_value)
                if end_label == "Claim" and end_key == "claim_id":
                    end_value = normalize_claim_id(end_value)

                rows.append({"start": start_value, "end": end_value, "props": props})

            q = f"""
            UNWIND $rows AS row
            MATCH (a:`{start_label}` {{`{start_key}`: row.start}})
            MATCH (b:`{end_label}` {{`{end_key}`: row.end}})
            MERGE (a)-[r:`{rel_type}`]->(b)
            SET r += row.props
            """
            for i in range(0, len(rows), 500):
                session.run(q, rows=rows[i:i+500]).consume()

    driver.close()
    print("Graph build complete")


if __name__ == "__main__":
    main()
