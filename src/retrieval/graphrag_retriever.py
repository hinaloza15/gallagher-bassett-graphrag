"""
Graph-first GraphRAG retriever.

Architecture:
question -> schema intent -> Neo4j candidate notes/chunks -> BGE-M3 reranking

There is intentionally NO global vector search before Neo4j. This separates the
GraphRAG experiment from the vector-seeded Hybrid architecture.
"""
import os
from typing import Dict, Iterable, List, Set
from dotenv import load_dotenv
from neo4j import GraphDatabase

from src.retrieval.common import normalize_claim_id, semantic_rank
from src.retrieval.question_analyzer import analyze_question

load_dotenv()

URI = os.getenv("NEO4J_URI")
USER = os.getenv("NEO4J_USER", "neo4j")
PASSWORD = os.getenv("NEO4J_PASSWORD")
DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")


def _driver():
    if not URI or not PASSWORD:
        raise RuntimeError("Set NEO4J_URI, NEO4J_USER and NEO4J_PASSWORD in .env")
    return GraphDatabase.driver(URI, auth=(USER, PASSWORD))


def _run_chunk_query(session, query: str, **params) -> Set[str]:
    return {
        str(row["chunk_id"])
        for row in session.run(query, **params)
        if row.get("chunk_id")
    }


def graph_candidate_ids(claim_id: str, analysis: Dict[str, List[str]]) -> List[str]:
    """Collect candidate chunks by traversing schema-aware graph paths first."""
    claim_id = normalize_claim_id(claim_id)
    event_types = analysis.get("event_types", [])
    entities = set(analysis.get("entities", []))
    relationships = set(analysis.get("relationships", []))

    candidate_ids: Set[str] = set()
    driver = _driver()

    with driver.session(database=DATABASE) as session:
        # 1) Event-oriented questions: Claim -> HAS_EVENT -> Event -> evidence Note -> Chunk.
        # If event types were recognized, this is the strongest graph-first narrowing.
        if event_types:
            event_query = """
            MATCH (c:Claim {claim_id: $claim_id})-[:HAS_EVENT]->(e:ClaimEvent)
            WHERE e.event_type IN $event_types
            MATCH (e)-[:EVIDENCED_BY]->(n:Note)-[:HAS_CHUNK]->(ch:Chunk)
            RETURN DISTINCT ch.chunk_id AS chunk_id
            """
            candidate_ids |= _run_chunk_query(
                session,
                event_query,
                claim_id=claim_id,
                event_types=event_types,
            )

            # Timeline questions expand only through the explicit event chronology.
            if "NEXT_EVENT" in relationships:
                timeline_query = """
                MATCH (c:Claim {claim_id: $claim_id})-[:HAS_EVENT]->(e:ClaimEvent)
                WHERE e.event_type IN $event_types
                OPTIONAL MATCH (e)-[:NEXT_EVENT*1..2]-(related:ClaimEvent)
                WITH collect(DISTINCT e) + collect(DISTINCT related) AS events
                UNWIND events AS ev
                WITH DISTINCT ev
                WHERE ev IS NOT NULL
                MATCH (ev)-[:EVIDENCED_BY]->(n:Note)-[:HAS_CHUNK]->(ch:Chunk)
                RETURN DISTINCT ch.chunk_id AS chunk_id
                """
                candidate_ids |= _run_chunk_query(
                    session,
                    timeline_query,
                    claim_id=claim_id,
                    event_types=event_types,
                )

        # 2) Medication-oriented graph path.
        if "Medication" in entities or "RECORDS_MEDICATION" in relationships:
            medication_query = """
            MATCH (c:Claim {claim_id: $claim_id})-[:HAS_EVENT]->(e:ClaimEvent)
                  -[:RECORDS_MEDICATION]->(:Medication)
            MATCH (e)-[:EVIDENCED_BY]->(n:Note)-[:HAS_CHUNK]->(ch:Chunk)
            RETURN DISTINCT ch.chunk_id AS chunk_id
            """
            candidate_ids |= _run_chunk_query(session, medication_query, claim_id=claim_id)

        # 3) Treatment-oriented graph path.
        if "Treatment" in entities or "INCLUDES_TREATMENT" in relationships:
            treatment_query = """
            MATCH (c:Claim {claim_id: $claim_id})-[:HAS_EVENT]->(e:ClaimEvent)
                  -[:INCLUDES_TREATMENT]->(:Treatment)
            MATCH (e)-[:EVIDENCED_BY]->(n:Note)-[:HAS_CHUNK]->(ch:Chunk)
            RETURN DISTINCT ch.chunk_id AS chunk_id
            """
            candidate_ids |= _run_chunk_query(session, treatment_query, claim_id=claim_id)

        # 4) Claims-staff / author questions.
        if "ClaimsStaff" in entities or "WRITTEN_BY" in relationships:
            staff_query = """
            MATCH (c:Claim {claim_id: $claim_id})-[:HAS_NOTE]->(n:Note)
                  -[:WRITTEN_BY]->(:ClaimsStaff)
            MATCH (n)-[:HAS_CHUNK]->(ch:Chunk)
            RETURN DISTINCT ch.chunk_id AS chunk_id
            """
            candidate_ids |= _run_chunk_query(session, staff_query, claim_id=claim_id)

        # 5) Clinician/provider questions.
        if "Clinician" in entities or "SEEN_BY" in relationships:
            clinician_query = """
            MATCH (c:Claim {claim_id: $claim_id})-[:HAS_NOTE]->(n:Note)
                  -[:WRITTEN_BY]->(:Clinician)
            MATCH (n)-[:HAS_CHUNK]->(ch:Chunk)
            RETURN DISTINCT ch.chunk_id AS chunk_id
            """
            candidate_ids |= _run_chunk_query(session, clinician_query, claim_id=claim_id)

        # 6) Evidence/provenance question. Stay claim-scoped, but use the graph to
        # traverse Claim -> Note -> Chunk instead of starting with vector search.
        if "Note" in entities or "EVIDENCED_BY" in relationships:
            evidence_query = """
            MATCH (:Claim {claim_id: $claim_id})-[:HAS_NOTE]->(n:Note)-[:HAS_CHUNK]->(ch:Chunk)
            RETURN DISTINCT ch.chunk_id AS chunk_id
            """
            candidate_ids |= _run_chunk_query(session, evidence_query, claim_id=claim_id)

        # 7) Location/county questions. County is structured graph metadata; use
        # its existence to validate the graph path, then rank the claim's note
        # evidence for the textual support.
        if "County" in entities or "OCCURRED_IN_COUNTY" in relationships:
            location_query = """
            MATCH (c:Claim {claim_id: $claim_id})-[:OCCURRED_IN_COUNTY]->(:County)
            MATCH (c)-[:HAS_NOTE]->(n:Note)-[:HAS_CHUNK]->(ch:Chunk)
            RETURN DISTINCT ch.chunk_id AS chunk_id
            """
            candidate_ids |= _run_chunk_query(session, location_query, claim_id=claim_id)

        # 8) Body-part questions currently do not have a dedicated BodyPart edge
        # in the prototype graph. Use injury events as the graph anchor rather than
        # silently doing global vector retrieval.
        if "BodyPart" in entities:
            body_part_query = """
            MATCH (c:Claim {claim_id: $claim_id})-[:HAS_EVENT]->(e:ClaimEvent)
            WHERE e.event_type IN ['injury_occurred', 'medical_visit', 'imaging_result']
            MATCH (e)-[:EVIDENCED_BY]->(n:Note)-[:HAS_CHUNK]->(ch:Chunk)
            RETURN DISTINCT ch.chunk_id AS chunk_id
            """
            candidate_ids |= _run_chunk_query(session, body_part_query, claim_id=claim_id)

        # Conservative graph-first fallback: if the analyzer did not recognize a
        # specific concept, traverse the claim's graph to its evidence chunks.
        # This avoids silently converting GraphRAG into baseline vector search.
        if not candidate_ids:
            fallback_query = """
            MATCH (:Claim {claim_id: $claim_id})-[:HAS_NOTE]->(:Note)-[:HAS_CHUNK]->(ch:Chunk)
            RETURN DISTINCT ch.chunk_id AS chunk_id
            """
            candidate_ids |= _run_chunk_query(session, fallback_query, claim_id=claim_id)

    driver.close()
    return sorted(candidate_ids)


def retrieve(question: str, claim_id: str, top_k=5):
    analysis = analyze_question(question)
    candidate_ids = graph_candidate_ids(claim_id, analysis)

    # Rerank only graph-selected candidates with the same BGE-M3 model used by
    # the baseline. This isolates the retrieval architecture as the experiment.
    ranked = semantic_rank(
        question,
        claim_id,
        top_k=min(top_k, len(candidate_ids)),
        candidate_ids=candidate_ids,
    )

    for row in ranked:
        row["retrieval_method"] = "graphrag_graph_first"
        row["detected_entities"] = analysis["entities"]
        row["detected_event_types"] = analysis["event_types"]
        row["detected_relationships"] = analysis["relationships"]
        row["candidate_count"] = len(candidate_ids)

    return ranked


if __name__ == "__main__":
    q = "How did the claimant's work restrictions change over time?"
    claim = "6977160"

    analysis = analyze_question(q)
    print("Question analysis:", analysis)
    print()

    rows = retrieve(q, claim, top_k=5)
    for row in rows:
        print(
            row["rank"],
            row["note_id"],
            f"score={row['semantic_score']:.4f}",
            f"candidates={row['candidate_count']}",
        )
        print(row["text"][:400], "\n")
