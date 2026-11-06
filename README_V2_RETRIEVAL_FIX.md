# GraphRAG V2 – Retrieval-Focused Fix

This version keeps Qwen3 14B through Ollama for schema-constrained query planning, Neo4j graph-first retrieval, BGE-M3 reranking, and the existing 512-token chunking.

## Changes based on the first 18-question dev run

- Uses the relationship types actually loaded in Neo4j and skips absent edges such as `CONFLICTS_WITH` or `HAS_BODY_PART`.
- Weights `EVIDENCED_BY` primary evidence higher than restated/copied evidence.
- Adds structural weight for explicit work restrictions and work-status values.
- Adds date-aware scoring for questions mentioning months such as March or cutoffs such as `by March 11`.
- Fixes timeline selection so it no longer forces weak earliest/latest notes; it selects the strongest distinct transition states first.
- Improves entity resolution by extracting quoted name variants and retrieving claim-linked notes containing those variants.
- Uses a graph-scoped body-part fallback when the optional BodyPart relationship is not loaded.
- Adds a provenance selector that prioritizes date-relevant event evidence, restrictions, and work-status details.

## Environment

```env
GRAPHRAG_USE_LLM_ANALYZER=1
GRAPHRAG_PLANNER_BACKEND=ollama
GRAPHRAG_PLANNER_MODEL=qwen3:14b
GRAPHRAG_OLLAMA_URL=http://localhost:11434/api/chat
GRAPHRAG_SEMANTIC_WEIGHT=0.60
GRAPHRAG_MAX_CANDIDATES=120
```

## Run

```bash
source venv/bin/activate
python3 test_planner.py
python3 -m src.evaluation.run_graphrag_dev_evaluation
```

Use only the dev split while tuning.

## First Qwen3 GraphRAG dev result

- Hit@5: 0.556
- Precision@5: 0.185
- Recall@5: 0.226
- MRR: 0.319

Weak categories targeted by this V2:
- Timeline Recall@5: 0.133
- Multi-note Recall@5: 0.167
- Provenance Recall@5: 0.083
- Entity resolution Recall@5: 0.222

Conflict was already strong:
- Conflict Hit@5: 1.000
- Conflict MRR: 0.750
