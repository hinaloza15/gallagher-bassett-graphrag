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
    ("EVIDENCED_BY", "MATCH ()-[r:EVIDENCED_BY]->() RETURN count(r) AS count"),
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

        print("\n=== SAMPLE 6977140 IDENTITIES ===")
        for row in session.run("""
            MATCH (c:Claim {claim_id:'6977140'})-[:FILED_BY]->(cl:Claimant)
            OPTIONAL MATCH (n:Note {claim_id:'6977140'})-[:WRITTEN_BY]->(p)
            WHERE p.name = cl.name
            RETURN cl.name AS claimant_name,
                   labels(cl) AS claimant_labels,
                   collect(DISTINCT labels(p)) AS same_name_author_labels
        """):
            print(dict(row))
    driver.close()

if __name__ == "__main__":
    main()
