"""
Vector-seeded graph retrieval (Hybrid).

Architecture:
question -> BGE-M3 seed chunks -> Neo4j expansion -> BGE-M3 reranking -> Top K

This is the architecture the sponsors identified as hybrid rather than pure
GraphRAG because vector search happens before graph traversal.
"""
import os
from dotenv import load_dotenv
from neo4j import GraphDatabase

from src.retrieval.common import normalize_claim_id, semantic_rank

load_dotenv()

URI = os.getenv("NEO4J_URI")
USER = os.getenv("NEO4J_USER", "neo4j")
PASSWORD = os.getenv("NEO4J_PASSWORD")
DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")


def graph_candidate_ids(seed_chunk_ids, claim_id):
    claim_id = normalize_claim_id(claim_id)
    driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))

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

    with driver.session(database=DATABASE) as session:
        row = session.run(
            query,
            seed_ids=list(seed_chunk_ids),
            claim_id=claim_id,
        ).single()

    driver.close()

    ids = [x for x in (row["candidate_ids"] or []) if x]
    return list(dict.fromkeys(map(str, ids)))


def retrieve(question: str, claim_id: str, seed_k=5, top_k=5):
    # Use more than two seeds so multi-part questions are less likely to lose
    # important evidence before graph expansion. This is now tunable/evaluable.
    seeds = semantic_rank(question, claim_id, top_k=seed_k)
    seed_ids = [x["chunk_id"] for x in seeds]

    graph_ids = graph_candidate_ids(seed_ids, claim_id)
    candidates = list(dict.fromkeys(seed_ids + graph_ids))

    reranked = semantic_rank(
        question,
        claim_id,
        top_k=min(max(top_k, 30), len(candidates)),
        candidate_ids=candidates,
    )

    seed_set = set(seed_ids)
    graph_set = set(graph_ids)

    for row in reranked:
        # Semantic relevance stays primary; graph provenance is a small bonus.
        if row["chunk_id"] in seed_set:
            graph_bonus = 0.04
        elif row["chunk_id"] in graph_set:
            graph_bonus = 0.02
        else:
            graph_bonus = 0.0

        row["graph_bonus"] = graph_bonus
        row["final_score"] = row["semantic_score"] + graph_bonus
        row["retrieval_method"] = "hybrid_vector_seeded_graph"
        row["seed_count"] = len(seed_ids)
        row["candidate_count"] = len(candidates)

    reranked.sort(key=lambda x: x["final_score"], reverse=True)

    for rank, row in enumerate(reranked[:top_k], start=1):
        row["rank"] = rank

    return reranked[:top_k]


if __name__ == "__main__":
    q = "How did the claimant's work restrictions change over time?"
    for row in retrieve(q, "6977160", seed_k=5, top_k=5):
        print(
            row["rank"],
            row["note_id"],
            f"final={row['final_score']:.4f}",
            f"candidates={row['candidate_count']}",
        )
        print(row["text"][:400], "\n")
