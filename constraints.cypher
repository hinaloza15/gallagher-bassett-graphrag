// Neo4j constraints and indexes for schema v0.1.0 (Neo4j 5.x).
// Generated from schema/graph_schema_v0.yaml. Run once on an empty database, then load out/load_demo_graph.cypher.
// Uniqueness constraints work in Community Edition. Property-existence (NOT NULL) constraints need Enterprise,
// so required properties are enforced by src/build_demo_graph.py validation instead.
// Not yet executed against a Neo4j server.

CREATE CONSTRAINT claim_key IF NOT EXISTS FOR (n:Claim) REQUIRE n.claim_id IS UNIQUE;
CREATE CONSTRAINT claimant_key IF NOT EXISTS FOR (n:Claimant) REQUIRE n.claimant_id IS UNIQUE;
CREATE CONSTRAINT employer_key IF NOT EXISTS FOR (n:Employer) REQUIRE n.employer_id IS UNIQUE;
CREATE CONSTRAINT adjuster_key IF NOT EXISTS FOR (n:Adjuster) REQUIRE n.adjuster_id IS UNIQUE;
CREATE CONSTRAINT provider_key IF NOT EXISTS FOR (n:Provider) REQUIRE n.provider_id IS UNIQUE;
CREATE CONSTRAINT carrier_key IF NOT EXISTS FOR (n:Carrier) REQUIRE n.carrier_id IS UNIQUE;
CREATE CONSTRAINT injury_key IF NOT EXISTS FOR (n:Injury) REQUIRE n.wcio_nature_code IS UNIQUE;
CREATE CONSTRAINT bodypart_key IF NOT EXISTS FOR (n:BodyPart) REQUIRE n.wcio_body_code IS UNIQUE;
CREATE CONSTRAINT injurycause_key IF NOT EXISTS FOR (n:InjuryCause) REQUIRE n.wcio_cause_code IS UNIQUE;
CREATE CONSTRAINT county_key IF NOT EXISTS FOR (n:County) REQUIRE n.name IS UNIQUE;
CREATE CONSTRAINT location_key IF NOT EXISTS FOR (n:Location) REQUIRE n.location_id IS UNIQUE;
CREATE CONSTRAINT industry_key IF NOT EXISTS FOR (n:Industry) REQUIRE n.naics2 IS UNIQUE;
CREATE CONSTRAINT document_key IF NOT EXISTS FOR (n:Document) REQUIRE n.doc_id IS UNIQUE;
CREATE CONSTRAINT chunk_key IF NOT EXISTS FOR (n:Chunk) REQUIRE n.chunk_id IS UNIQUE;
CREATE CONSTRAINT processstep_key IF NOT EXISTS FOR (n:ProcessStep) REQUIRE n.step_id IS UNIQUE;
CREATE CONSTRAINT form_key IF NOT EXISTS FOR (n:Form) REQUIRE n.form_code IS UNIQUE;
CREATE CONSTRAINT role_key IF NOT EXISTS FOR (n:Role) REQUIRE n.role_name IS UNIQUE;
CREATE CONSTRAINT claimevent_key IF NOT EXISTS FOR (n:ClaimEvent) REQUIRE n.event_id IS UNIQUE;

// Keyword search over chunk text (the BM25-style arm of hybrid retrieval)
CREATE FULLTEXT INDEX chunk_text IF NOT EXISTS FOR (c:Chunk) ON EACH [c.text];

// Vector search over chunk embeddings. 768 dimensions = multi-qa-mpnet-base-dot-v1 (JTA proposal).
// Change vector.dimensions if the team picks a different embedding model.
CREATE VECTOR INDEX chunk_embedding IF NOT EXISTS FOR (c:Chunk) ON c.embedding
OPTIONS {indexConfig: {`vector.dimensions`: 768, `vector.similarity_function`: 'cosine'}};

// Lookup indexes for common filters
CREATE INDEX document_type IF NOT EXISTS FOR (d:Document) ON (d.doc_type);
CREATE INDEX claim_status IF NOT EXISTS FOR (c:Claim) ON (c.current_status);
