# Improved GraphRAG with Qwen3 14B

This package replaces the GraphRAG query-planning and retrieval layer. It does **not** rebuild chunks, embeddings, graph extraction, or Neo4j.

## Architecture

Question → Qwen3 14B schema-constrained planner → Neo4j graph-first retrieval → graph-aware scoring + BGE-M3 reranking → coverage-aware Top 5.

Qwen3 14B is **not** used to answer the claim question during retrieval. It only maps natural language into allowed graph intents, entities, relationships, and event types.

## Why Qwen3 14B

Primary planner: `qwen3:14b` through Ollama. This is a quantized local version of Qwen3 14B and is roughly 23 GB. The full Hugging Face checkpoint is much larger, so Ollama is the practical Mac path.

If Qwen3 14B cannot run, `GRAPHRAG_PLANNER_BACKEND=auto` automatically falls back to the project's existing Transformers Qwen model, and deterministic rules remain as the last fallback.

## Files to copy into your project

- `src/retrieval/planner_client.py` (new)
- `src/retrieval/question_analyzer.py` (replace)
- `src/retrieval/graphrag_retriever.py` (replace)
- `src/evaluation/run_graphrag_dev_evaluation.py` (add/replace)
- `evaluation/questions.csv`

## Mac setup

### 1. Install Ollama

Install Ollama, then make sure the Ollama application/server is running.

### 2. Pull Qwen3 14B

```bash
ollama pull qwen3:14b
```

Or run:

```bash
bash setup_qwen36_mac.sh
```

### 3. Add GraphRAG settings to `.env`

Copy the GraphRAG lines from `.env.graphrag.example` into your existing `.env`. Keep your own Neo4j credentials.

Recommended settings:

```env
GRAPHRAG_USE_LLM_ANALYZER=1
GRAPHRAG_PLANNER_BACKEND=auto
GRAPHRAG_PLANNER_MODEL=qwen3:14b
GRAPHRAG_OLLAMA_URL=http://localhost:11434/api/chat
GRAPHRAG_SEMANTIC_WEIGHT=0.60
GRAPHRAG_MAX_CANDIDATES=120
```

### 4. Test the query planner

From the repository root with the virtual environment active:

```bash
python3 test_planner.py
```

The output should show planner names such as:

```text
rules_plus_ollama:qwen3:14b
```

### 5. Run ONLY the development evaluation

```bash
python3 -m src.evaluation.run_graphrag_dev_evaluation
```

The script runs only the 18 `dev` questions and writes:

```text
evaluation/results/graphrag_dev_results.csv
```

Do not tune using the final/holdout questions.

## What the improved retriever does

- Uses Qwen3 14B to recognize question intent and graph concepts.
- Uses `NEXT_EVENT` for timeline questions.
- Uses both sides of `CORRECTS` for conflict/correction questions.
- Uses `EVIDENCED_BY` for provenance questions.
- Uses treatment, medication, clinician, claims-staff, body-part and location graph paths where relevant.
- Combines graph structural relevance with BGE-M3 semantic relevance.
- Deduplicates at note level.
- Preserves distinct timeline transitions instead of returning repetitive notes.
- Gives multi-part questions evidence across multiple event types.

## Presentation explanation

> We use Qwen3 14B as a schema-constrained query planner. It translates a natural-language claims question into valid graph intents, entities, relationships, and event types, but it cannot invent graph schema elements and does not answer the question. Neo4j then performs graph-first evidence retrieval using intent-specific paths. BGE-M3 reranks only the graph-selected evidence, while coverage-aware selection preserves timeline transitions, correction pairs, and multi-note evidence.

Roles:
- **Qwen3 14B:** query understanding / schema planning.
- **Neo4j:** graph-first evidence retrieval.
- **BGE-M3:** semantic relevance ranking inside graph-selected candidates.
- **Final answer generator:** separate from retrieval evaluation.

## If the Mac cannot fit Qwen3 14B

The Ollama Qwen3 14B model is about 23 GB. If the computer does not have enough memory, leave `GRAPHRAG_PLANNER_BACKEND=auto`. The code will fall back to the existing smaller Qwen planner and then to deterministic rules rather than failing the entire evaluation.
