import json
import time
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

load_dotenv(".env", override=True)

from src.retrieval.baseline_retriever import retrieve as baseline
from src.retrieval.hybrid_retriever import retrieve as hybrid
from src.evaluation.run_graphrag_dev_evaluation import (
    parse_set, retrieval_metrics,
)

folder = Path("testing/results/v2_20261106_122918")
graph = pd.read_csv(folder / "graphrag_dev_results.csv", dtype={"claim_id": str})
assert len(graph) == 18
assert graph["planner"].eq("rules_plus_ollama:qwen3:14b").all()

rows = []
evidence_file = folder / "baseline_hybrid_evidence.jsonl"

with evidence_file.open("w") as output:
    for method, retrieve in [("baseline", baseline), ("hybrid", hybrid)]:
        for _, question in graph.iterrows():
            print(f"{method}: {question['question_id']}", flush=True)
            start = time.perf_counter()
            evidence = retrieve(
                question["question"], question["claim_id"], top_k=5
            )
            seconds = time.perf_counter() - start
            metrics = retrieval_metrics(
                evidence, parse_set(question["gold_note_ids"])
            )
            rows.append({
                "method": method,
                "question_id": question["question_id"],
                "claim_id": question["claim_id"],
                "question": question["question"],
                "category": question["category"],
                "gold_note_ids": question["gold_note_ids"],
                "retrieved_note_ids": "|".join(str(x["note_id"]) for x in evidence),
                "retrieval_seconds": seconds,
                **metrics,
            })
            output.write(json.dumps({
                "method": method,
                "question_id": question["question_id"],
                "evidence": evidence,
            }, default=str) + "\n")
            output.flush()

other = pd.DataFrame(rows)
other.to_csv(folder / "baseline_hybrid_dev_results.csv", index=False)

graph["method"] = "graphrag"
combined = pd.concat([graph, other], ignore_index=True)
combined.to_csv(folder / "all_methods_dev_results.csv", index=False)

metrics = ["hit_at_5", "precision_at_5", "recall_at_5", "mrr"]
summary = combined.groupby("method")[metrics].mean()
summary.to_csv(folder / "comparison_summary.csv")

report = (
    "# V2 development retrieval comparison\n\n"
    "18 development questions per method, top_k=5. "
    "GraphRAG used Ollama Qwen3 14B for all 18 questions.\n\n"
    "Baseline and hybrid were scored against the same reference note IDs "
    "using the team's existing metric function.\n\n"
    "```\n" + summary.round(3).to_string() + "\n```\n\n"
    "Limitations:\n"
    "- Retrieval evaluation only; final answers were not generated in this run.\n"
    "- Development results are not a holdout evaluation.\n"
    "- precision_at_5 divides by unique returned notes, sometimes fewer than five.\n"
    "- Timing is not directly comparable: GraphRAG planning occurs before its "
    "retrieval timer, and first-use model loading can affect timings.\n"
    "- C03/P03 reference-note alignment needs review: the graph returned "
    "correction pair SYN-6977182-094/096, while the reference lists other IDs. "
    "Scores retain the supplied references unchanged.\n\n"
    "Reproduce baseline/hybrid comparison from the repository root:\n\n"
    "    python -m testing.compare_v2\n"
)
(folder / "README.md").write_text(report)

print("\nCOMPARISON")
print(summary.round(3).to_string())
print(f"\nSaved to: {folder.resolve()}")
