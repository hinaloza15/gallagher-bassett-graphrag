# Improved GraphRAG – Fast Replacement

This package changes only the GraphRAG retrieval layer. It does **not** rebuild the graph, embeddings, chunks, or BGE-M3 index.

## What changed

1. **LLM-assisted question planning**
   - Reuses the existing local `Qwen/Qwen2.5-1.5B-Instruct`.
   - Qwen is constrained to allowed graph intents, entities, relationships, and event types.
   - Deterministic rules are merged with the LLM output so the pipeline still works if Qwen fails.

2. **Intent-specific Neo4j retrieval**
   - Timeline questions use `ClaimEvent -> NEXT_EVENT -> EVIDENCED_BY -> Note`.
   - Conflict questions retrieve both sides of explicit `CORRECTS` pairs.
   - Provenance questions prefer `EVIDENCED_BY`.
   - Treatment/medication/provider/entity-resolution questions use their graph paths.

3. **Graph-aware reranking**
   - Final ranking combines BGE-M3 semantic relevance and graph structural relevance.
   - Default: 60% semantic / 40% graph. Tune only on the `dev` split.

4. **Coverage-aware Top 5**
   - Timeline: prefers distinct status/restriction transitions and chronological coverage.
   - Multi-note: ensures multiple detected event types receive evidence.
   - Conflict: forces both sides of a correction pair into consideration.
   - Results are deduplicated at the note level.

## Replace these files

Copy:
- `src/retrieval/question_analyzer.py`
- `src/retrieval/graphrag_retriever.py`

into the same paths in your GitHub project.

Also copy:
- `src/evaluation/run_graphrag_dev_evaluation.py`
- `evaluation/questions.csv`

## Environment

Your existing `.env` remains the same. Optional settings:

```env
GRAPHRAG_USE_LLM_ANALYZER=1
GRAPHRAG_SEMANTIC_WEIGHT=0.60
GRAPHRAG_MAX_CANDIDATES=120
```

No OpenAI API key is needed. This uses the same local Qwen model already used by answer generation.

## Run

From the repository root:

```bash
source venv/bin/activate
python3 -m src.evaluation.run_graphrag_dev_evaluation
```

This intentionally runs only the 18 `dev` questions.

The results are saved to:

```text
evaluation/results/graphrag_dev_results.csv
```

## If Qwen makes the run too slow

You can temporarily compare the deterministic fallback with:

```bash
GRAPHRAG_USE_LLM_ANALYZER=0 python3 -m src.evaluation.run_graphrag_dev_evaluation
```

For the final GraphRAG result, use the LLM analyzer (`=1`).

## Presentation explanation

> We use a schema-constrained LLM query planner to translate natural-language questions into graph concepts such as claim events, relationships, and evidence types. The LLM cannot invent graph labels or directly generate the answer. Neo4j then performs graph-first evidence retrieval using intent-specific paths. BGE-M3 reranks only the graph-selected evidence, and a coverage-aware selector preserves timeline transitions, multi-part evidence, and both sides of explicit corrections.

This makes the roles clear:
- **Qwen:** understands the query.
- **Neo4j:** reasons over connected claim evidence.
- **BGE-M3:** ranks relevance within graph-selected evidence.
- **Qwen answer generator:** produces the final cited answer only after retrieval.
