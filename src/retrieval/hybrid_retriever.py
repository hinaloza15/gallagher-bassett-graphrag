"""
Hybrid RAG: vector-seeded graph expansion + planner-driven GraphRAG, fused.

Architecture
------------
question
  ├─ (A) BGE-M3 vector seeds (claim-scoped)
  │       -> Neo4j expansion from seeds (NEXT_NOTE, EVIDENCED_BY/NEXT_EVENT,
  │          CORRECTS/DUPLICATES), now returning event metadata
  └─ (B) rules + schema-constrained Qwen planner
          -> intent-specific Neo4j traversal (same paths as GraphRAG)
  -> union of candidates with graph structural scores
  -> BGE-M3 reranking fused with graph score (+ small vector-seed bonus)
  -> GraphRAG's coverage-aware Top-K (timeline / conflict / provenance / multi-note)

Path A lets vector search find evidence that the planner's graph paths miss;
path B brings in structurally related evidence (correction pairs, timeline
transitions) that is not semantically close to the question. GraphRAG remains
pure graph-first; this is the hybrid of the two.

Set ``mode="seeded"`` (or HYBRID_MODE=seeded) to run the original
vector-seeded-only hybrid for comparison.
"""
from __future__ import annotations

import os
from typing import Dict, List

from dotenv import load_dotenv

from src.retrieval.common import normalize_claim_id, semantic_rank
from src.retrieval.graphrag_retriever import (
    DATABASE,
    MAX_CANDIDATES,
    _add_candidate,
    _driver,
    graph_candidates,
    rank_and_select,
)
from src.retrieval.question_analyzer import analyze_question

load_dotenv()

# Tune on DEV questions only.
HYBRID_MODE = os.getenv("HYBRID_MODE", "fused").strip().lower()
SEED_BONUS = float(os.getenv("HYBRID_SEED_BONUS", "0.08"))

# Structural scores for seed-expansion paths, on the same scale GraphRAG uses
# (direct event match = 1.00, correction pair = 1.35, timeline neighbor = 0.58).
SEED_SCORE = 0.70
SEED_EVENT_SCORE = 0.80
SEED_CORRECTION_SCORE = 1.10
SEED_EVENT_NEIGHBOR_SCORE = 0.50
SEED_NEAR_NOTE_SCORE = 0.30

_META = """
    ch.chunk_id AS chunk_id, n.note_id AS note_id, n.note_date AS note_date,
    e.event_type AS event_type, e.event_date AS event_date,
    e.restrictions AS restrictions, e.work_status AS work_status
"""


def seed_expansion_candidates(session, seed_ids: List[str], claim_id: str, store: Dict[str, dict]):
    """Expand from vector seeds through the graph, keeping event metadata."""
    seed_ids = list(seed_ids)
    if not seed_ids:
        return

    # Seeds themselves, with any event they evidence.
    session_rows = session.run(f"""
        MATCH (n:Note)-[:HAS_CHUNK]->(ch:Chunk) WHERE ch.chunk_id IN $seed_ids
        OPTIONAL MATCH (e:ClaimEvent)-[:EVIDENCED_BY]->(n)
        RETURN {_META}
    """, seed_ids=seed_ids)
    for row in session_rows:
        row = dict(row)
        score = SEED_EVENT_SCORE if row.get("event_type") else SEED_SCORE
        _add_candidate(store, row, score, "vector_seed")

    queries = [
        # Seed note's event -> neighboring events in the claim timeline.
        (f"""
        MATCH (seed:Chunk) WHERE seed.chunk_id IN $seed_ids
        MATCH (seed)<-[:HAS_CHUNK]-(:Note)<-[:EVIDENCED_BY]-(se:ClaimEvent)
        MATCH (se)-[:NEXT_EVENT*1..2]-(e:ClaimEvent)-[:EVIDENCED_BY]->(n:Note)-[:HAS_CHUNK]->(ch:Chunk)
        WHERE toString(toInteger(n.claim_id)) = $claim_id
        RETURN DISTINCT {_META}
        """, SEED_EVENT_NEIGHBOR_SCORE, "seed_timeline_neighbor"),
        # Both sides of corrections/duplicates touching a seed note.
        (f"""
        MATCH (seed:Chunk) WHERE seed.chunk_id IN $seed_ids
        MATCH (seed)<-[:HAS_CHUNK]-(:Note)-[:CORRECTS|DUPLICATES]-(n:Note)-[:HAS_CHUNK]->(ch:Chunk)
        WHERE toString(toInteger(n.claim_id)) = $claim_id
        OPTIONAL MATCH (e:ClaimEvent)-[:EVIDENCED_BY]->(n)
        RETURN DISTINCT {_META}
        """, SEED_CORRECTION_SCORE, "seed_correction_link"),
        # Adjacent notes (immediate chronological context).
        (f"""
        MATCH (seed:Chunk) WHERE seed.chunk_id IN $seed_ids
        MATCH (seed)<-[:HAS_CHUNK]-(:Note)-[:NEXT_NOTE]-(n:Note)-[:HAS_CHUNK]->(ch:Chunk)
        WHERE toString(toInteger(n.claim_id)) = $claim_id
        OPTIONAL MATCH (e:ClaimEvent)-[:EVIDENCED_BY]->(n)
        RETURN DISTINCT {_META}
        """, SEED_NEAR_NOTE_SCORE, "seed_adjacent_note"),
    ]
    for query, score, reason in queries:
        for row in session.run(query, seed_ids=seed_ids, claim_id=claim_id):
            _add_candidate(store, dict(row), score, reason)


def _merge_stores(primary: Dict[str, dict], extra: Dict[str, dict]) -> Dict[str, dict]:
    """Merge candidate stores: keep max structural score and union of reasons."""
    out = {k: dict(v, graph_reasons=list(v["graph_reasons"])) for k, v in primary.items()}
    for cid, item in extra.items():
        if cid not in out:
            out[cid] = dict(item, graph_reasons=list(item["graph_reasons"]))
            continue
        cur = out[cid]
        cur["structural_score"] = max(cur["structural_score"], item["structural_score"])
        for r in item["graph_reasons"]:
            if r not in cur["graph_reasons"]:
                cur["graph_reasons"].append(r)
        for key in ["note_id", "note_date", "event_type", "event_date", "restrictions", "work_status"]:
            if not cur.get(key) and item.get(key):
                cur[key] = item[key]
    return out


def retrieve_fused(question: str, claim_id: str, seed_k=5, top_k=5):
    claim_id = normalize_claim_id(claim_id)

    # (A) vector seeds -> graph expansion
    seeds = semantic_rank(question, claim_id, top_k=seed_k)
    seed_ids = [x["chunk_id"] for x in seeds]
    seed_store: Dict[str, dict] = {}
    driver = _driver()
    try:
        with driver.session(database=DATABASE) as session:
            seed_expansion_candidates(session, seed_ids, claim_id, seed_store)
    finally:
        driver.close()
    # Seeds must survive even if the graph returned nothing for them.
    for s in seeds:
        _add_candidate(seed_store, s, SEED_SCORE, "vector_seed")

    # (B) planner -> intent-specific graph traversal (GraphRAG's paths)
    analysis = analyze_question(question)
    planner_store = graph_candidates(question, claim_id, analysis)

    store = _merge_stores(planner_store, seed_store)
    seed_set = set(seed_ids)
    # Cap: always keep seeds, then highest structural scores.
    if len(store) > MAX_CANDIDATES + len(seed_set):
        keep = sorted(
            (v for k, v in store.items() if k not in seed_set),
            key=lambda x: x["structural_score"], reverse=True,
        )[:MAX_CANDIDATES]
        store = {**{k: store[k] for k in seed_set if k in store}, **{x["chunk_id"]: x for x in keep}}

    bonus = {cid: SEED_BONUS for cid in seed_set}
    selected = rank_and_select(
        question, claim_id, analysis, store, top_k=top_k,
        extra_bonus=bonus, retrieval_method="hybrid_fused_vector_graph",
    )

    planner_ids, seed_path_ids = set(planner_store), set(seed_store)
    for row in selected:
        cid = row["chunk_id"]
        sources = []
        if cid in seed_set:
            sources.append("seed")
        if cid in seed_path_ids and cid not in seed_set:
            sources.append("seed_graph")
        if cid in planner_ids:
            sources.append("planner_graph")
        row["source"] = "+".join(sources) or "-"
        row["seed_count"] = len(seed_ids)
        row["planner_candidate_count"] = len(planner_store)
        row["seed_candidate_count"] = len(seed_store)
    return selected


# ---------------------------------------------------------------------------
# Original vector-seeded-only hybrid (kept for comparison: mode="seeded").
# ---------------------------------------------------------------------------
def graph_candidate_ids(seed_chunk_ids, claim_id):
    claim_id = normalize_claim_id(claim_id)
    query = """
    MATCH (seed:Chunk)
    WHERE seed.chunk_id IN $seed_ids
    MATCH (seed)<-[:HAS_CHUNK]-(n:Note)

    OPTIONAL MATCH (n)-[:NEXT_NOTE]-(nearNote:Note)
    WHERE toString(toInteger(nearNote.claim_id)) = $claim_id
    OPTIONAL MATCH (nearNote)-[:HAS_CHUNK]->(nearChunk:Chunk)

    OPTIONAL MATCH (e:ClaimEvent)-[:EVIDENCED_BY]->(n)
    OPTIONAL MATCH (e)-[:NEXT_EVENT*1..2]-(e2:ClaimEvent)
    OPTIONAL MATCH (e2)-[:EVIDENCED_BY]->(eventNote:Note)
    WHERE toString(toInteger(eventNote.claim_id)) = $claim_id
    OPTIONAL MATCH (eventNote)-[:HAS_CHUNK]->(eventChunk:Chunk)

    OPTIONAL MATCH (corr:Note)-[:CORRECTS|DUPLICATES]-(n)
    WHERE toString(toInteger(corr.claim_id)) = $claim_id
    OPTIONAL MATCH (corr)-[:HAS_CHUNK]->(corrChunk:Chunk)

    RETURN collect(DISTINCT nearChunk.chunk_id) +
           collect(DISTINCT eventChunk.chunk_id) +
           collect(DISTINCT corrChunk.chunk_id) AS candidate_ids
    """
    driver = _driver()
    try:
        with driver.session(database=DATABASE) as session:
            row = session.run(query, seed_ids=list(seed_chunk_ids), claim_id=claim_id).single()
    finally:
        driver.close()
    ids = [x for x in (row["candidate_ids"] or []) if x]
    return list(dict.fromkeys(map(str, ids)))


def retrieve_seeded(question: str, claim_id: str, seed_k=5, top_k=5):
    seeds = semantic_rank(question, claim_id, top_k=seed_k)
    seed_ids = [x["chunk_id"] for x in seeds]
    graph_ids = graph_candidate_ids(seed_ids, claim_id)
    candidates = list(dict.fromkeys(seed_ids + graph_ids))

    reranked = semantic_rank(
        question, claim_id,
        top_k=min(max(top_k, 30), len(candidates)),
        candidate_ids=candidates,
    )
    seed_set, graph_set = set(seed_ids), set(graph_ids)
    for row in reranked:
        if row["chunk_id"] in seed_set:
            row["graph_bonus"], row["source"] = 0.04, "seed"
        elif row["chunk_id"] in graph_set:
            row["graph_bonus"], row["source"] = 0.02, "seed_graph"
        else:
            row["graph_bonus"], row["source"] = 0.0, "-"
        row["final_score"] = row["semantic_score"] + row["graph_bonus"]
        row["retrieval_method"] = "hybrid_vector_seeded_graph"
        row["seed_count"] = len(seed_ids)
        row["candidate_count"] = len(candidates)

    reranked.sort(key=lambda x: x["final_score"], reverse=True)
    for rank, row in enumerate(reranked[:top_k], start=1):
        row["rank"] = rank
    return reranked[:top_k]


def retrieve(question: str, claim_id: str, seed_k=5, top_k=5, mode=None):
    mode = (mode or HYBRID_MODE).lower()
    if mode == "seeded":
        return retrieve_seeded(question, claim_id, seed_k=seed_k, top_k=top_k)
    if mode == "fused":
        return retrieve_fused(question, claim_id, seed_k=seed_k, top_k=top_k)
    raise ValueError("hybrid mode must be 'fused' or 'seeded'")


if __name__ == "__main__":
    q = "How did the claimant's work restrictions change over time?"
    for row in retrieve(q, "6977160", seed_k=5, top_k=5):
        print(
            row["rank"], row["note_id"], f"final={row['final_score']:.4f}",
            row["source"], row.get("graph_reasons", []),
        )
        print(row["text"][:300].replace("\n", " "), "\n")
