"""
Improved graph-first GraphRAG retriever.

Architecture
------------
question
  -> rules + schema-constrained Qwen3 14B query planner
  -> intent-specific Neo4j traversal
  -> graph structural scoring
  -> BGE-M3 semantic reranking inside graph-selected evidence
  -> coverage-aware Top-K selection

There is NO global vector search before the graph. This remains genuinely
Graph-first and is intentionally different from the vector-seeded Hybrid path.
"""
from __future__ import annotations

import math
import os
import re
from functools import lru_cache
from collections import defaultdict
from datetime import date, datetime
from typing import Dict, Iterable, List, Optional

from dotenv import load_dotenv
from neo4j import GraphDatabase

from src.retrieval.common import normalize_claim_id, semantic_rank
from src.retrieval.question_analyzer import analyze_question

load_dotenv()
URI = os.getenv("NEO4J_URI")
USER = os.getenv("NEO4J_USER", "neo4j")
PASSWORD = os.getenv("NEO4J_PASSWORD")
DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")

# Tunable on DEV questions only. Graph must matter, but semantic relevance still
# protects against broad graph traversals.
SEMANTIC_WEIGHT = float(os.getenv("GRAPHRAG_SEMANTIC_WEIGHT", "0.60"))
GRAPH_WEIGHT = 1.0 - SEMANTIC_WEIGHT
MAX_CANDIDATES = int(os.getenv("GRAPHRAG_MAX_CANDIDATES", "120"))

MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6,
    "july": 7, "jul": 7, "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}


def _question_months(question: str) -> set[int]:
    q = question.lower()
    return {num for name, num in MONTHS.items() if re.search(rf"\\b{re.escape(name)}\\b", q)}


def _question_cutoff(question: str):
    """Parse simple 'by March 11' style cutoffs as (month, day)."""
    q = question.lower()
    names = "|".join(sorted(MONTHS, key=len, reverse=True))
    m = re.search(rf"\\bby\\s+({names})\\s+(\\d{{1,2}})\\b", q)
    if not m:
        return None
    return MONTHS[m.group(1)], int(m.group(2))


def _quoted_names(question: str) -> list[str]:
    vals = re.findall(r"['\"]([^'\"]{2,80})['\"]", question)
    # Keep likely human-name variants; avoid quoted technical terms.
    out = []
    for v in vals:
        v = v.strip()
        if 1 < len(v.split()) <= 5 and any(ch.isalpha() for ch in v):
            out.append(v)
    return list(dict.fromkeys(out))


def _parse_date_parts(value):
    if not value:
        return None
    text = str(value)
    # neo4j dates normally stringify as YYYY-MM-DD
    m = re.search(r"(\\d{4})-(\\d{2})-(\\d{2})", text)
    if not m:
        return None
    return tuple(map(int, m.groups()))


def _temporal_bonus(question: str, row: dict) -> float:
    parts = _parse_date_parts(row.get("event_date") or row.get("note_date"))
    if not parts:
        return 0.0
    _, month, day = parts
    bonus = 0.0
    months = _question_months(question)
    if months and month in months:
        bonus += 0.22
    cutoff = _question_cutoff(question)
    if cutoff:
        cm, cd = cutoff
        if (month, day) <= (cm, cd):
            bonus += 0.14
        else:
            bonus -= 0.18
    return bonus


@lru_cache(maxsize=1)
def _available_relationships() -> frozenset[str]:
    """Read the relationships actually loaded in Neo4j, not just those in YAML."""
    driver = _driver()
    try:
        with driver.session(database=DATABASE) as session:
            vals = session.run("CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType")
            return frozenset(str(r["relationshipType"]) for r in vals)
    finally:
        driver.close()


def _has_rel(name: str) -> bool:
    try:
        return name in _available_relationships()
    except Exception:
        return True


def _driver():
    if not URI or not PASSWORD:
        raise RuntimeError("Set NEO4J_URI, NEO4J_USER and NEO4J_PASSWORD in .env")
    return GraphDatabase.driver(URI, auth=(USER, PASSWORD))


def _date_text(value) -> str:
    if value is None:
        return ""
    if hasattr(value, "iso_format"):
        try:
            return value.iso_format()
        except Exception:
            pass
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _add_candidate(store: Dict[str, dict], row: dict, structural_score: float, reason: str):
    chunk_id = row.get("chunk_id")
    if not chunk_id:
        return
    chunk_id = str(chunk_id)
    item = store.setdefault(chunk_id, {
        "chunk_id": chunk_id,
        "note_id": str(row.get("note_id") or ""),
        "note_date": _date_text(row.get("note_date")),
        "event_type": str(row.get("event_type") or ""),
        "event_date": _date_text(row.get("event_date")),
        "restrictions": str(row.get("restrictions") or ""),
        "work_status": str(row.get("work_status") or ""),
        "structural_score": 0.0,
        "graph_reasons": [],
    })
    evidence_kind = str(row.get("evidence_kind") or "").lower()
    support = str(row.get("support") or "").lower()
    dynamic = float(structural_score)
    if evidence_kind == "primary" or support == "primary":
        dynamic += 0.22
    elif evidence_kind == "restated" or support == "restated":
        dynamic -= 0.05
    if str(row.get("restrictions") or "").strip():
        dynamic += 0.16
    if str(row.get("work_status") or "").strip():
        dynamic += 0.10
    item["structural_score"] = max(float(item["structural_score"]), dynamic)
    if reason not in item["graph_reasons"]:
        item["graph_reasons"].append(reason)
    # Prefer populated metadata from any path that found this candidate.
    for key in ["note_id", "note_date", "event_type", "event_date", "restrictions", "work_status"]:
        if not item.get(key) and row.get(key) is not None:
            item[key] = _date_text(row.get(key)) if "date" in key else str(row.get(key))


def _collect(session, query: str, store: Dict[str, dict], score: float, reason: str, **params):
    for row in session.run(query, **params):
        _add_candidate(store, dict(row), score, reason)


def _event_candidates(session, claim_id: str, event_types: List[str], store: Dict[str, dict]):
    if not event_types:
        return
    query = """
    MATCH (c:Claim {claim_id: $claim_id})-[:HAS_EVENT]->(e:ClaimEvent)
    WHERE e.event_type IN $event_types
    MATCH (e)-[eb:EVIDENCED_BY]->(n:Note)-[:HAS_CHUNK]->(ch:Chunk)
    RETURN DISTINCT ch.chunk_id AS chunk_id, n.note_id AS note_id,
           n.note_date AS note_date, e.event_type AS event_type,
           e.event_date AS event_date, e.restrictions AS restrictions,
           e.work_status AS work_status, eb.evidence_kind AS evidence_kind, e.support AS support
    """
    _collect(session, query, store, 1.00, "direct_event_match", claim_id=claim_id, event_types=event_types)


def _timeline_candidates(session, claim_id: str, event_types: List[str], store: Dict[str, dict]):
    # Direct matching events are strongest. Neighbor events receive a lower score
    # and are used for chronology/context rather than dominating semantic matches.
    _event_candidates(session, claim_id, event_types, store)
    if not event_types:
        return
    query = """
    MATCH (c:Claim {claim_id: $claim_id})-[:HAS_EVENT]->(seed:ClaimEvent)
    WHERE seed.event_type IN $event_types
    MATCH (seed)-[:NEXT_EVENT*1..2]-(e:ClaimEvent)
    MATCH (e)-[eb:EVIDENCED_BY]->(n:Note)-[:HAS_CHUNK]->(ch:Chunk)
    RETURN DISTINCT ch.chunk_id AS chunk_id, n.note_id AS note_id,
           n.note_date AS note_date, e.event_type AS event_type,
           e.event_date AS event_date, e.restrictions AS restrictions,
           e.work_status AS work_status
    """
    _collect(session, query, store, 0.58, "timeline_neighbor", claim_id=claim_id, event_types=event_types)


def _correction_candidates(session, claim_id: str, store: Dict[str, dict]):
    # Retrieve BOTH sides of every explicit correction pair. This is where a graph
    # should have a clear advantage over plain vector similarity.
    query = """
    MATCH (c:Claim {claim_id: $claim_id})-[:HAS_NOTE]->(newer:Note)-[:CORRECTS]->(older:Note)
    UNWIND [newer, older] AS n
    MATCH (n)-[:HAS_CHUNK]->(ch:Chunk)
    RETURN DISTINCT ch.chunk_id AS chunk_id, n.note_id AS note_id,
           n.note_date AS note_date, '' AS event_type, null AS event_date,
           '' AS restrictions, '' AS work_status
    """
    _collect(session, query, store, 1.35, "correction_pair", claim_id=claim_id)

    # If CONFLICTS_WITH exists in later graph versions, use it too. It is harmless
    # when the relationship type has no instances.
    if not _has_rel("CONFLICTS_WITH"):
        return
    conflict_query = """
    MATCH (c:Claim {claim_id: $claim_id})-[:HAS_EVENT]->(a:ClaimEvent)-[:CONFLICTS_WITH]-(b:ClaimEvent)
    UNWIND [a,b] AS e
    MATCH (e)-[eb:EVIDENCED_BY]->(n:Note)-[:HAS_CHUNK]->(ch:Chunk)
    RETURN DISTINCT ch.chunk_id AS chunk_id, n.note_id AS note_id,
           n.note_date AS note_date, e.event_type AS event_type,
           e.event_date AS event_date, e.restrictions AS restrictions,
           e.work_status AS work_status
    """
    _collect(session, conflict_query, store, 1.25, "conflicting_event_pair", claim_id=claim_id)


def _treatment_candidates(session, claim_id: str, store: Dict[str, dict]):
    query = """
    MATCH (c:Claim {claim_id: $claim_id})-[:HAS_EVENT]->(e:ClaimEvent)-[:INCLUDES_TREATMENT]->(:Treatment)
    MATCH (e)-[eb:EVIDENCED_BY]->(n:Note)-[:HAS_CHUNK]->(ch:Chunk)
    RETURN DISTINCT ch.chunk_id AS chunk_id, n.note_id AS note_id,
           n.note_date AS note_date, e.event_type AS event_type,
           e.event_date AS event_date, e.restrictions AS restrictions,
           e.work_status AS work_status
    """
    _collect(session, query, store, 1.00, "treatment_path", claim_id=claim_id)


def _medication_candidates(session, claim_id: str, store: Dict[str, dict]):
    query = """
    MATCH (c:Claim {claim_id: $claim_id})-[:HAS_EVENT]->(e:ClaimEvent)-[:RECORDS_MEDICATION]->(:Medication)
    MATCH (e)-[eb:EVIDENCED_BY]->(n:Note)-[:HAS_CHUNK]->(ch:Chunk)
    RETURN DISTINCT ch.chunk_id AS chunk_id, n.note_id AS note_id,
           n.note_date AS note_date, e.event_type AS event_type,
           e.event_date AS event_date, e.restrictions AS restrictions,
           e.work_status AS work_status
    """
    _collect(session, query, store, 1.00, "medication_path", claim_id=claim_id)


def _clinician_candidates(session, claim_id: str, store: Dict[str, dict]):
    # Current graph represents clinician-authored notes via WRITTEN_BY.
    query = """
    MATCH (c:Claim {claim_id: $claim_id})-[:HAS_NOTE]->(n:Note)-[:WRITTEN_BY]->(:Clinician)
    MATCH (n)-[:HAS_CHUNK]->(ch:Chunk)
    RETURN DISTINCT ch.chunk_id AS chunk_id, n.note_id AS note_id,
           n.note_date AS note_date, '' AS event_type, null AS event_date,
           '' AS restrictions, '' AS work_status
    """
    _collect(session, query, store, 0.86, "clinician_authored_note", claim_id=claim_id)


def _staff_candidates(session, claim_id: str, store: Dict[str, dict]):
    query = """
    MATCH (c:Claim {claim_id: $claim_id})-[:HAS_NOTE]->(n:Note)-[:WRITTEN_BY]->(:ClaimsStaff)
    MATCH (n)-[:HAS_CHUNK]->(ch:Chunk)
    RETURN DISTINCT ch.chunk_id AS chunk_id, n.note_id AS note_id,
           n.note_date AS note_date, '' AS event_type, null AS event_date,
           '' AS restrictions, '' AS work_status
    """
    _collect(session, query, store, 0.72, "claims_staff_authored_note", claim_id=claim_id)


def _entity_resolution_candidates(session, claim_id: str, question: str, store: Dict[str, dict]):
    # First retrieve notes that literally contain quoted/name variants from the
    # question. This is critical for misspellings such as Juliann/Julian while
    # remaining generic (no benchmark names are hardcoded).
    names = _quoted_names(question)
    if names:
        query = """
        MATCH (c:Claim {claim_id: $claim_id})-[:HAS_NOTE]->(n:Note)-[:HAS_CHUNK]->(ch:Chunk)
        WHERE any(name IN $names WHERE toLower(n.text) CONTAINS toLower(name))
        RETURN DISTINCT ch.chunk_id AS chunk_id, n.note_id AS note_id,
               n.note_date AS note_date, '' AS event_type, null AS event_date,
               '' AS restrictions, '' AS work_status
        """
        _collect(session, query, store, 1.30, "name_variant_text_evidence", claim_id=claim_id, names=names)

    # Role-aware graph evidence for exact names that map to graph people.
    query = """
    MATCH (c:Claim {claim_id: $claim_id})
    OPTIONAL MATCH (c)-[:FILED_BY]->(cl:Claimant)
    OPTIONAL MATCH (c)-[:HANDLED_BY]->(st:ClaimsStaff)
    OPTIONAL MATCH (c)-[:SEEN_BY]->(dr:Clinician)
    WITH c, [x IN collect(DISTINCT cl) + collect(DISTINCT st) + collect(DISTINCT dr)
             WHERE x IS NOT NULL AND x.name IS NOT NULL AND toLower($question) CONTAINS toLower(x.name)] AS people
    UNWIND people AS p
    OPTIONAL MATCH (n:Note)-[:WRITTEN_BY]->(p)
    WHERE n.claim_id = $claim_id
    OPTIONAL MATCH (n)-[:HAS_CHUNK]->(ch:Chunk)
    RETURN DISTINCT ch.chunk_id AS chunk_id, n.note_id AS note_id,
           n.note_date AS note_date, '' AS event_type, null AS event_date,
           '' AS restrictions, '' AS work_status
    """
    _collect(session, query, store, 1.05, "role_aware_entity_match", claim_id=claim_id, question=question)

    # Low-weight claim scope is only a last supporting pool, not the main signal.
    claimant_query = """
    MATCH (c:Claim {claim_id: $claim_id})-[:FILED_BY]->(cl:Claimant)
    WHERE cl.name IS NOT NULL AND toLower($question) CONTAINS toLower(cl.name)
    MATCH (c)-[:HAS_NOTE]->(n:Note)-[:HAS_CHUNK]->(ch:Chunk)
    RETURN DISTINCT ch.chunk_id AS chunk_id, n.note_id AS note_id,
           n.note_date AS note_date, '' AS event_type, null AS event_date,
           '' AS restrictions, '' AS work_status
    """
    _collect(session, claimant_query, store, 0.22, "claimant_claim_scope", claim_id=claim_id, question=question)


def _body_part_candidates(session, claim_id: str, store: Dict[str, dict]):
    # Use the structured edge only if it is actually loaded. The current prototype
    # graph may omit this optional relationship even though it exists in the YAML.
    if _has_rel("HAS_BODY_PART"):
        query = """
        MATCH (c:Claim {claim_id: $claim_id})-[:HAS_BODY_PART]->(:BodyPart)
        MATCH (c)-[:HAS_EVENT]->(e:ClaimEvent)
        WHERE e.event_type IN ['injury_occurred','medical_visit','imaging_result']
        MATCH (e)-[eb:EVIDENCED_BY]->(n:Note)-[:HAS_CHUNK]->(ch:Chunk)
        RETURN DISTINCT ch.chunk_id AS chunk_id, n.note_id AS note_id,
               n.note_date AS note_date, e.event_type AS event_type,
               e.event_date AS event_date, e.restrictions AS restrictions,
               e.work_status AS work_status, eb.evidence_kind AS evidence_kind, e.support AS support
        """
        _collect(session, query, store, 0.95, "body_part_graph_path", claim_id=claim_id)
    else:
        # Graph-scoped textual fallback: Claim -> Note -> Chunk. This stays inside
        # the claim graph but does not pretend an unloaded BodyPart edge exists.
        query = """
        MATCH (c:Claim {claim_id: $claim_id})-[:HAS_NOTE]->(n:Note)-[:HAS_CHUNK]->(ch:Chunk)
        RETURN DISTINCT ch.chunk_id AS chunk_id, n.note_id AS note_id,
               n.note_date AS note_date, '' AS event_type, null AS event_date,
               '' AS restrictions, '' AS work_status
        """
        _collect(session, query, store, 0.46, "body_part_claim_graph_fallback", claim_id=claim_id)


def _location_candidates(session, claim_id: str, store: Dict[str, dict]):
    query = """
    MATCH (c:Claim {claim_id: $claim_id})-[:OCCURRED_IN_COUNTY]->(:County)
    MATCH (c)-[:HAS_EVENT]->(e:ClaimEvent)
    WHERE e.event_type = 'injury_occurred'
    MATCH (e)-[eb:EVIDENCED_BY]->(n:Note)-[:HAS_CHUNK]->(ch:Chunk)
    RETURN DISTINCT ch.chunk_id AS chunk_id, n.note_id AS note_id,
           n.note_date AS note_date, e.event_type AS event_type,
           e.event_date AS event_date, e.restrictions AS restrictions,
           e.work_status AS work_status
    """
    _collect(session, query, store, 0.95, "injury_location_path", claim_id=claim_id)


def _provenance_candidates(session, claim_id: str, event_types: List[str], store: Dict[str, dict]):
    # Provenance should prefer notes explicitly attached to relevant events rather
    # than opening every Note in the claim.
    if event_types:
        _event_candidates(session, claim_id, event_types, store)
    else:
        query = """
        MATCH (c:Claim {claim_id: $claim_id})-[:HAS_EVENT]->(e:ClaimEvent)-[:EVIDENCED_BY]->(n:Note)-[:HAS_CHUNK]->(ch:Chunk)
        RETURN DISTINCT ch.chunk_id AS chunk_id, n.note_id AS note_id,
               n.note_date AS note_date, e.event_type AS event_type,
               e.event_date AS event_date, e.restrictions AS restrictions,
               e.work_status AS work_status
        """
        _collect(session, query, store, 0.74, "event_provenance", claim_id=claim_id)


def _graph_fallback(session, claim_id: str, store: Dict[str, dict]):
    # Still graph-first: Claim -> Event -> Evidence -> Note -> Chunk. This is more
    # meaningful than immediately opening every claim chunk.
    query = """
    MATCH (c:Claim {claim_id: $claim_id})-[:HAS_EVENT]->(e:ClaimEvent)-[:EVIDENCED_BY]->(n:Note)-[:HAS_CHUNK]->(ch:Chunk)
    RETURN DISTINCT ch.chunk_id AS chunk_id, n.note_id AS note_id,
           n.note_date AS note_date, e.event_type AS event_type,
           e.event_date AS event_date, e.restrictions AS restrictions,
           e.work_status AS work_status
    LIMIT 250
    """
    _collect(session, query, store, 0.42, "graph_event_fallback", claim_id=claim_id)


def graph_candidates(question: str, claim_id: str, analysis: Dict[str, List[str]]) -> Dict[str, dict]:
    claim_id = normalize_claim_id(claim_id)
    intents = set(analysis.get("intents", []))
    entities = set(analysis.get("entities", []))
    relationships = set(analysis.get("relationships", []))
    event_types = analysis.get("event_types", [])

    store: Dict[str, dict] = {}
    driver = _driver()
    try:
        with driver.session(database=DATABASE) as session:
            # Conflict is deliberately first and receives the strongest structural
            # evidence because explicit CORRECTS edges are highly informative.
            if "conflict" in intents or "CORRECTS" in relationships:
                _correction_candidates(session, claim_id, store)

            if "timeline" in intents or "NEXT_EVENT" in relationships:
                _timeline_candidates(session, claim_id, event_types, store)
            elif event_types:
                _event_candidates(session, claim_id, event_types, store)

            if "Treatment" in entities or "INCLUDES_TREATMENT" in relationships:
                _treatment_candidates(session, claim_id, store)
            if "Medication" in entities or "RECORDS_MEDICATION" in relationships:
                _medication_candidates(session, claim_id, store)
            if "Clinician" in entities or "SEEN_BY" in relationships:
                _clinician_candidates(session, claim_id, store)
            if "ClaimsStaff" in entities or "WRITTEN_BY" in relationships:
                _staff_candidates(session, claim_id, store)
            if "entity_resolution" in intents:
                _entity_resolution_candidates(session, claim_id, question, store)
            if "BodyPart" in entities:
                _body_part_candidates(session, claim_id, store)
            if "County" in entities:
                _location_candidates(session, claim_id, store)
            if "provenance" in intents or "EVIDENCED_BY" in relationships:
                _provenance_candidates(session, claim_id, event_types, store)

            if not store:
                _graph_fallback(session, claim_id, store)
    finally:
        driver.close()

    # Bound reranking cost. Structural score, not arbitrary DB order, decides
    # which candidates survive when the graph path is broad.
    ordered = sorted(store.values(), key=lambda x: x["structural_score"], reverse=True)
    return {x["chunk_id"]: x for x in ordered[:MAX_CANDIDATES]}


def _normalize_semantic(scores: List[float]) -> List[float]:
    if not scores:
        return []
    lo, hi = min(scores), max(scores)
    if math.isclose(lo, hi):
        return [1.0 for _ in scores]
    return [(s - lo) / (hi - lo) for s in scores]


def _state_signature(row: dict) -> str:
    parts = [
        str(row.get("event_type") or "").lower().strip(),
        str(row.get("restrictions") or "").lower().strip(),
        str(row.get("work_status") or "").lower().strip(),
    ]
    return "|".join(parts)


def _dedupe_by_note(rows: List[dict]) -> List[dict]:
    best = {}
    for row in rows:
        note_id = row.get("note_id") or row.get("chunk_id")
        if note_id not in best or row["final_score"] > best[note_id]["final_score"]:
            best[note_id] = row
    return sorted(best.values(), key=lambda x: x["final_score"], reverse=True)


def _select_multi_intent(rows: List[dict], event_types: List[str], top_k: int) -> List[dict]:
    """Guarantee topical coverage instead of allowing one sub-intent to take all K."""
    selected, used_notes = [], set()
    for event_type in event_types:
        candidates = [r for r in rows if r.get("event_type") == event_type and r.get("note_id") not in used_notes]
        if candidates:
            pick = max(candidates, key=lambda x: x["final_score"])
            selected.append(pick)
            used_notes.add(pick.get("note_id"))
            if len(selected) >= top_k:
                return selected
    for row in rows:
        if row.get("note_id") not in used_notes:
            selected.append(row)
            used_notes.add(row.get("note_id"))
        if len(selected) >= top_k:
            break
    return selected


def _select_timeline(rows: List[dict], top_k: int) -> List[dict]:
    """Prefer distinct, well-supported status/restriction transitions."""
    if not rows:
        return []
    by_state = {}
    for row in rows:
        sig = _state_signature(row)
        if sig == "||":
            sig = f"note:{row.get('note_id')}"
        if sig not in by_state or row["final_score"] > by_state[sig]["final_score"]:
            by_state[sig] = row
    states = list(by_state.values())

    # Rank by evidence quality first. Earlier code forced earliest/latest events,
    # which selected weak copied-history notes and hurt the dev benchmark.
    states.sort(key=lambda r: r["final_score"], reverse=True)
    selected = states[:top_k]
    # Display chronologically after selection so the answer generator sees a
    # coherent timeline without sacrificing retrieval quality.
    selected.sort(key=lambda r: (r.get("event_date") or r.get("note_date") or ""))
    return selected


def _select_provenance(rows: List[dict], question: str, top_k: int) -> List[dict]:
    """Prefer explicit, date-relevant, primary evidence for source questions."""
    months = _question_months(question)
    cutoff = _question_cutoff(question)
    rescored = []
    for row in rows:
        r = dict(row)
        bonus = 0.0
        reasons = r.get("graph_reasons", [])
        if "direct_event_match" in reasons:
            bonus += 0.10
        parts = _parse_date_parts(r.get("event_date") or r.get("note_date"))
        if parts:
            _, m, d = parts
            if months and m in months:
                bonus += 0.28
            if cutoff and (m, d) <= cutoff:
                bonus += 0.10
        # Explicit restriction/status metadata is especially useful for work-status provenance.
        if str(r.get("restrictions") or "").strip():
            bonus += 0.14
        if str(r.get("work_status") or "").strip():
            bonus += 0.08
        r["final_score"] += bonus
        rescored.append(r)
    rescored.sort(key=lambda x: x["final_score"], reverse=True)
    return rescored[:top_k]


def _ensure_correction_pair(rows: List[dict], top_k: int) -> List[dict]:
    correction_rows = [r for r in rows if "correction_pair" in r.get("graph_reasons", [])]
    selected = []
    used = set()
    # Prefer up to two distinct correction-pair notes first.
    for row in sorted(correction_rows, key=lambda x: x["final_score"], reverse=True):
        if row.get("note_id") not in used:
            selected.append(row)
            used.add(row.get("note_id"))
        if len(selected) >= min(2, top_k):
            break
    for row in rows:
        if row.get("note_id") not in used:
            selected.append(row)
            used.add(row.get("note_id"))
        if len(selected) >= top_k:
            break
    return selected


def retrieve(question: str, claim_id: str, top_k=5):
    claim_id = normalize_claim_id(claim_id)
    analysis = analyze_question(question)
    candidate_meta = graph_candidates(question, claim_id, analysis)
    candidate_ids = list(candidate_meta)

    if not candidate_ids:
        return []

    # Ask BGE for enough rows to allow the graph-aware selector to diversify Top-K.
    semantic_rows = semantic_rank(
        question,
        claim_id,
        top_k=min(len(candidate_ids), MAX_CANDIDATES),
        candidate_ids=candidate_ids,
    )
    semantic_norm = _normalize_semantic([r["semantic_score"] for r in semantic_rows])

    ranked = []
    max_structural = max([m["structural_score"] for m in candidate_meta.values()] or [1.0])
    for row, sem_norm in zip(semantic_rows, semantic_norm):
        meta = candidate_meta.get(row["chunk_id"], {})
        graph_norm = float(meta.get("structural_score", 0.0)) / max_structural
        final_score = SEMANTIC_WEIGHT * sem_norm + GRAPH_WEIGHT * graph_norm + _temporal_bonus(question, meta)
        out = dict(row)
        out.update({
            "graph_score": graph_norm,
            "final_score": final_score,
            "graph_reasons": meta.get("graph_reasons", []),
            "event_type": meta.get("event_type", ""),
            "event_date": meta.get("event_date", ""),
            "note_date": meta.get("note_date", ""),
            "restrictions": meta.get("restrictions", ""),
            "work_status": meta.get("work_status", ""),
        })
        ranked.append(out)

    ranked.sort(key=lambda x: x["final_score"], reverse=True)
    ranked = _dedupe_by_note(ranked)

    intents = set(analysis.get("intents", []))
    if "conflict" in intents or "CORRECTS" in set(analysis.get("relationships", [])):
        selected = _ensure_correction_pair(ranked, top_k)
    elif "timeline" in intents:
        selected = _select_timeline(ranked, top_k)
        # If timeline diversity yielded fewer than K, fill with next best evidence.
        used = {r.get("note_id") for r in selected}
        for row in ranked:
            if row.get("note_id") not in used:
                selected.append(row)
                used.add(row.get("note_id"))
            if len(selected) >= top_k:
                break
    elif "provenance" in intents:
        selected = _select_provenance(ranked, question, top_k)
    elif "multi_note" in intents and len(analysis.get("event_types", [])) > 1:
        selected = _select_multi_intent(ranked, analysis["event_types"], top_k)
    else:
        selected = ranked[:top_k]

    for rank, row in enumerate(selected[:top_k], start=1):
        row["rank"] = rank
        row["retrieval_method"] = "graphrag_llm_planned_graph_first"
        row["detected_intents"] = analysis.get("intents", [])
        row["detected_entities"] = analysis.get("entities", [])
        row["detected_event_types"] = analysis.get("event_types", [])
        row["detected_relationships"] = analysis.get("relationships", [])
        row["planner"] = analysis.get("planner", "")
        row["candidate_count"] = len(candidate_ids)

    return selected[:top_k]


if __name__ == "__main__":
    tests = [
        ("How did the claimant's work restrictions change over time?", "6977160"),
        ("The notes list December 15 and December 16 as the DOI. Which date is correct?", "6977178"),
        ("Which notes support Chloe Nguyen's March work restrictions?", "6977160"),
    ]
    for q, claim in tests:
        print("\nQUESTION:", q)
        print("PLAN:", analyze_question(q))
        for row in retrieve(q, claim, top_k=5):
            print(row["rank"], row["note_id"], f"final={row['final_score']:.3f}", row["graph_reasons"])
            print(row["text"][:220].replace("\n", " "), "\n")
