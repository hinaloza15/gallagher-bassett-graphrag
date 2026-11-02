import os
from collections import OrderedDict

from dotenv import load_dotenv
from neo4j import GraphDatabase


load_dotenv()

URI = os.getenv("NEO4J_URI")
USER = os.getenv("NEO4J_USER", "neo4j")
PASSWORD = os.getenv("NEO4J_PASSWORD")
DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")

CHECKS = OrderedDict([
    ("Claims", "MATCH (n:Claim) RETURN count(n) AS count"),
    ("Claimants", "MATCH (n:Claimant) RETURN count(n) AS count"),
    ("Notes", "MATCH (n:Note) RETURN count(n) AS count"),
    ("Chunks", "MATCH (n:Chunk) RETURN count(n) AS count"),
    ("ClaimEvents", "MATCH (n:ClaimEvent) RETURN count(n) AS count"),
    ("HAS_NOTE", "MATCH ()-[r:HAS_NOTE]->() RETURN count(r) AS count"),
    ("HAS_CHUNK", "MATCH ()-[r:HAS_CHUNK]->() RETURN count(r) AS count"),
    ("NEXT_NOTE", "MATCH ()-[r:NEXT_NOTE]->() RETURN count(r) AS count"),
    ("NEXT_EVENT", "MATCH ()-[r:NEXT_EVENT]->() RETURN count(r) AS count"),
    ("EVIDENCED_BY", "MATCH ()-[r:EVIDENCED_BY]->() RETURN count(r) AS count"),
    ("CORRECTS", "MATCH ()-[r:CORRECTS]->() RETURN count(r) AS count"),
    ("DUPLICATES", "MATCH ()-[r:DUPLICATES]->() RETURN count(r) AS count"),
])


def main():
    driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))

    with driver.session(database=DATABASE) as session:
        print("=== GRAPH COUNTS ===")
        for name, query in CHECKS.items():
            print(f"{name:16} {session.run(query).single()['count']}")

        print("\n=== NOTES PER CLAIM ===")
        for row in session.run("""
            MATCH (c:Claim)-[:HAS_NOTE]->(n:Note)
            RETURN c.claim_id AS claim_id, count(n) AS notes
            ORDER BY claim_id
        """):
            print(row["claim_id"], row["notes"])

        print("\n=== CLAIM-ID PROPERTY TYPES ===")
        for row in session.run("""
            MATCH (n:Note)
            RETURN valueType(n.claim_id) AS type, count(*) AS count
            ORDER BY count DESC
        """):
            print(dict(row))

        print("\n=== SAMPLE 6977140 IDENTITIES ===")
        for row in session.run("""
            MATCH (c:Claim {claim_id:'6977140'})-[:FILED_BY]->(cl:Claimant)
            OPTIONAL MATCH (n:Note)-[:WRITTEN_BY]->(p)
            WHERE n.claim_id = '6977140'
              AND p.name = cl.name
            RETURN cl.name AS claimant_name,
                   labels(cl) AS claimant_labels,
                   collect(DISTINCT labels(p)) AS same_name_author_labels
        """):
            print(dict(row))

        print("\n=== EVENT TYPES ===")
        for row in session.run("""
            MATCH (e:ClaimEvent)
            RETURN e.event_type AS event_type, count(*) AS count
            ORDER BY count DESC
        """):
            print(f"{row['event_type']:36} {row['count']}")

        print("\n=== EVENTS PER NOTE DISTRIBUTION ===")
        for row in session.run("""
            MATCH (e:ClaimEvent)-[:EVIDENCED_BY]->(n:Note)
            WITH n, count(e) AS event_count
            RETURN event_count, count(*) AS note_count
            ORDER BY event_count
        """):
            print(f"events_per_note={row['event_count']:2} notes={row['note_count']}")

        print("\n=== NOTES WITH ZERO EVENTS ===")
        row = session.run("""
            MATCH (n:Note)
            WHERE NOT EXISTS {
                MATCH (:ClaimEvent)-[:EVIDENCED_BY]->(n)
            }
            RETURN count(n) AS count
        """).single()
        print(row["count"])

        print("\n=== MAX EVENTS ON A SINGLE NOTE ===")
        row = session.run("""
            MATCH (e:ClaimEvent)-[:EVIDENCED_BY]->(n:Note)
            WITH n, count(e) AS event_count
            RETURN n.note_id AS note_id, n.claim_id AS claim_id, event_count
            ORDER BY event_count DESC
            LIMIT 1
        """).single()
        print(dict(row) if row else {})

        print("\n=== CORRECTION EDGES ===")
        rows = list(session.run("""
            MATCH (later:Note)-[r:CORRECTS]->(earlier:Note)
            RETURN later.claim_id AS claim_id,
                   later.note_id AS later_note,
                   earlier.note_id AS corrected_note,
                   r.correction_topic AS topic
            ORDER BY claim_id, later_note
            LIMIT 25
        """))

        if rows:
            for row in rows:
                print(dict(row))
        else:
            print("No CORRECTS relationships found")

    driver.close()


if __name__ == "__main__":
    main()
