# Gallagher Bassett GraphRAG Prototype

## Project Overview

This prototype is part of the Gallagher Bassett capstone project focused on exploring how Retrieval-Augmented Generation (RAG) and knowledge graphs can improve question answering over workers' compensation claim data.

The current GraphRAG prototype uses 15 synthetic claim-note PDFs as the initial working corpus.

The main goal is to compare three retrieval approaches using the same data and model setup:

- Baseline RAG
- GraphRAG
- Hybrid RAG

The main difference between the three systems will be how they retrieve evidence before sending it to the language model.

---

## Current Scope

For the first GraphRAG prototype, the system is using only claim-note PDFs.

Policy and guideline documents will be added after the claim-only pipeline is working and validated.

Current input:

```text
15 claim-note PDFs
~1,500 individual claim notes