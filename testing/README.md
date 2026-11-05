# Baseline, GraphRAG, and Hybrid Testing

Date: November 5, 2026
Environment: Apple M1, Python 3.12.10, Neo4j AuraDB
Source branch: graphrag-neo4j
Source commit: 34bdd547b4382b04fbe1a54a88cd6ec595dd3428

## Completed setup

- Installed dependencies and verified imports.
- Connected to Neo4j AuraDB.
- Reused 1,513 processed notes. PDF parsing was not tested because no PDFs were available.
- Created 1,544 chunks: maximum 512 tokens, overlap 64 tokens.
- Generated 1,024-dimensional BGE-M3 embeddings using Apple GPU acceleration.
- Loaded and checked 15 claims, 1,513 notes, 1,544 chunks, 2,099 events,
  and 3 correction relationships.
- Validation reported 523 notes without extracted events.

## Testing performed

Ran six questions separately through baseline, GraphRAG, and hybrid
retrieval, followed by the repository's answer generator.

1. How did work restrictions change over time?
2. What are the latest work restrictions?
3. What is the corrected injury date?
4. Who is Maya Patel, and what roles does that name have?
5. What treatments were documented?
6. What is the claimant's favorite food?

These were AI-assisted diagnostic questions added for testing.
They were not supplied in the setup instructions.

Settings: top_k=5 and max_new_tokens=350.
All 18 attempts generated answers without execution errors.

## Initial findings

Findings below are based on an AI-assisted review of saved answers and
retrieved evidence. Human sign-off remains pending.

| Test | Finding |
| --- | --- |
| Timeline | All methods reversed the earlier 10-lb and later 20-lb restrictions. |
| Latest restrictions | All answered 20 lbs despite retrieving later evidence stating full duty with no restrictions. |
| Corrected injury date | All returned December 16. GraphRAG missed the explicit correction note, so correction handling remains unproven. |
| Identity | Answers did not clearly distinguish claimant and staff identities. |
| Treatment | Answers mainly summarized authorization and payment requests. |
| Missing information | All correctly stated that favorite food was unspecified. |

Additional observations:
- Hybrid returned identical evidence and answers to baseline for all six questions.
- None of the answers used the requested bracketed [E1] citation format.
- Successful execution does not establish answer accuracy.
- This small test does not establish an accuracy advantage for GraphRAG.
- Timings include first-use model loading and are not controlled benchmarks.
- No aggregate accuracy, precision, or recall score was calculated.

## Reproduce

From the repository root, with dependencies installed, .env configured,
embeddings available, and the Neo4j graph populated:

    python -m testing.run_comparison

## Saved results

Directory: testing/results/20261105_153453/

- results.jsonl: answers, retrieved evidence, timings, and errors.
- review.csv: review worksheet; individual review fields remain unfilled.
- run_metadata.json: source commit, environment, and test settings.

## Follow-up work

Review temporal ordering, latest-status selection, correction traversal,
identity handling, treatment retrieval, and citation compliance.
After fixes, rerun these cases and expand the evaluation with verified
reference answers.
