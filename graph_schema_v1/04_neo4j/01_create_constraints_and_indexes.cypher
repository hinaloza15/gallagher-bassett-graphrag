// 01_create_constraints_and_indexes.cypher
// Run ONCE on an empty Neo4j 5 database, BEFORE 02_load_graph_generated.cypher.
// Creates one uniqueness constraint per node label (on the key in 01_graph_schema_definition_v1.yaml),
// full-text indexes for keyword search and name/alias lookup, and range indexes used by the test queries.

// ---- uniqueness constraints (one per node label)
CREATE CONSTRAINT claim_id IF NOT EXISTS FOR (n:Claim) REQUIRE n.claim_id IS UNIQUE;
CREATE CONSTRAINT claimant_id IF NOT EXISTS FOR (n:Claimant) REQUIRE n.claimant_id IS UNIQUE;
CREATE CONSTRAINT employer_id IF NOT EXISTS FOR (n:Employer) REQUIRE n.employer_id IS UNIQUE;
CREATE CONSTRAINT carrier_id IF NOT EXISTS FOR (n:Carrier) REQUIRE n.carrier_id IS UNIQUE;
CREATE CONSTRAINT county_name IF NOT EXISTS FOR (n:County) REQUIRE n.county_name IS UNIQUE;
CREATE CONSTRAINT location_id IF NOT EXISTS FOR (n:IncidentLocation) REQUIRE n.location_id IS UNIQUE;
CREATE CONSTRAINT nature_id IF NOT EXISTS FOR (n:InjuryNature) REQUIRE n.nature_id IS UNIQUE;
CREATE CONSTRAINT body_part_id IF NOT EXISTS FOR (n:BodyPart) REQUIRE n.body_part_id IS UNIQUE;
CREATE CONSTRAINT cause_id IF NOT EXISTS FOR (n:InjuryCause) REQUIRE n.cause_id IS UNIQUE;
CREATE CONSTRAINT staff_id IF NOT EXISTS FOR (n:ClaimsStaff) REQUIRE n.staff_id IS UNIQUE;
CREATE CONSTRAINT contact_id IF NOT EXISTS FOR (n:EmployerContact) REQUIRE n.contact_id IS UNIQUE;
CREATE CONSTRAINT facility_id IF NOT EXISTS FOR (n:HealthcareFacility) REQUIRE n.facility_id IS UNIQUE;
CREATE CONSTRAINT clinician_id IF NOT EXISTS FOR (n:Clinician) REQUIRE n.clinician_id IS UNIQUE;
CREATE CONSTRAINT attorney_id IF NOT EXISTS FOR (n:Attorney) REQUIRE n.attorney_id IS UNIQUE;
CREATE CONSTRAINT diagnosis_id IF NOT EXISTS FOR (n:Diagnosis) REQUIRE n.diagnosis_id IS UNIQUE;
CREATE CONSTRAINT treatment_id IF NOT EXISTS FOR (n:Treatment) REQUIRE n.treatment_id IS UNIQUE;
CREATE CONSTRAINT medication_id IF NOT EXISTS FOR (n:Medication) REQUIRE n.medication_id IS UNIQUE;
CREATE CONSTRAINT note_id IF NOT EXISTS FOR (n:Note) REQUIRE n.note_id IS UNIQUE;
CREATE CONSTRAINT chunk_id IF NOT EXISTS FOR (n:Chunk) REQUIRE n.chunk_id IS UNIQUE;
CREATE CONSTRAINT doc_id IF NOT EXISTS FOR (n:Document) REQUIRE n.doc_id IS UNIQUE;
CREATE CONSTRAINT event_id IF NOT EXISTS FOR (n:ClaimEvent) REQUIRE n.event_id IS UNIQUE;
CREATE CONSTRAINT step_id IF NOT EXISTS FOR (n:ProcessStep) REQUIRE n.step_id IS UNIQUE;
CREATE CONSTRAINT form_code IF NOT EXISTS FOR (n:Form) REQUIRE n.form_code IS UNIQUE;
CREATE CONSTRAINT role_name IF NOT EXISTS FOR (n:Role) REQUIRE n.role_name IS UNIQUE;

// ---- range indexes used by the test questions
CREATE INDEX event_type_date IF NOT EXISTS FOR (n:ClaimEvent) ON (n.claim_id, n.event_type, n.event_date);
CREATE INDEX note_claim_date IF NOT EXISTS FOR (n:Note) ON (n.claim_id, n.note_date);

// ---- full-text indexes: keyword search over passages (the hybrid arm's BM25 side can use this too)
CREATE FULLTEXT INDEX chunk_text IF NOT EXISTS FOR (n:Chunk) ON EACH [n.text];
// name and alias lookup (finds 'SIF', 'Brooklyn Occ Medicine', 'DR Haddad', misspelled claimant names)
CREATE FULLTEXT INDEX entity_names IF NOT EXISTS
FOR (n:Claimant|Employer|Carrier|ClaimsStaff|EmployerContact|HealthcareFacility|Clinician|Attorney)
ON EACH [n.name, n.aliases];

// ---- vector index (fill Chunk.embedding with the team's embedding model, then uncomment;
//      set the dimension to the model's output size)
// CREATE VECTOR INDEX chunk_embedding IF NOT EXISTS FOR (n:Chunk) ON (n.embedding)
// OPTIONS {indexConfig: {`vector.dimensions`: 1536, `vector.similarity_function`: 'cosine'}};
