# V2 development retrieval comparison

18 development questions per method, top_k=5. GraphRAG used Ollama Qwen3 14B for all 18 questions.

Baseline and hybrid were scored against the same reference note IDs using the team's existing metric function.

```
          hit_at_5  precision_at_5  recall_at_5    mrr
method                                                
baseline     0.611           0.200        0.319  0.369
graphrag     0.611           0.219        0.237  0.472
hybrid       0.611           0.200        0.319  0.369
```

Limitations:
- Retrieval evaluation only; final answers were not generated in this run.
- Development results are not a holdout evaluation.
- precision_at_5 divides by unique returned notes, sometimes fewer than five.
- Timing is not directly comparable: GraphRAG planning occurs before its retrieval timer, and first-use model loading can affect timings.
- C03/P03 reference-note alignment needs review: the graph returned correction pair SYN-6977182-094/096, while the reference lists other IDs. Scores retain the supplied references unchanged.

Reproduce baseline/hybrid comparison from the repository root:

    python -m testing.compare_v2
