import csv
import json
import os
import platform
import subprocess
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(".env", override=True)
os.environ["NEO4J_USER"] = (
    os.getenv("NEO4J_USERNAME") or os.environ["NEO4J_USER"]
)

from src.retrieval.baseline_retriever import retrieve as baseline
from src.retrieval.graphrag_retriever import retrieve as graphrag
from src.retrieval.hybrid_retriever import retrieve as hybrid
from src.generation.answer_generator import generate_answer

output = Path("testing/results") / time.strftime("%Y%m%d_%H%M%S")
output.mkdir(parents=True, exist_ok=True)

questions = [
    ("Q1", "6977160", "How did the claimant's work restrictions change over time?"),
    ("Q2", "6977160", "What are the claimant's latest work restrictions?"),
    ("Q3", "6977178", "What is the corrected date of injury?"),
    ("Q4", "6977140", "Who is Maya Patel, and what roles does that name have in this claim?"),
    ("Q5", "6977160", "What treatments were documented for this claimant?"),
    ("Q6", "6977160", "What is the claimant's favorite food?"),
]

methods = {
    "baseline": baseline,
    "graphrag": graphrag,
    "hybrid": hybrid,
}

metadata = {
    "commit": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True
    ).strip(),
    "python": platform.python_version(),
    "architecture": platform.machine(),
    "top_k": 5,
    "max_new_tokens": 350,
    "notes": "Repository defaults. Timings include first-use model loading.",
}
(output / "run_metadata.json").write_text(
    json.dumps(metadata, indent=2), encoding="utf-8"
)

results = []

for question_id, claim_id, question in questions:
    for method, retrieve in methods.items():
        print(f"\n{question_id} | {method} | {question}", flush=True)
        record = {
            "question_id": question_id,
            "claim_id": claim_id,
            "question": question,
            "method": method,
            "status": "started",
            "answer": "",
            "evidence": [],
            "error": "",
        }
        try:
            start = time.perf_counter()
            evidence = retrieve(question, claim_id, top_k=5)
            record["retrieval_seconds"] = round(time.perf_counter() - start, 2)
            record["evidence"] = evidence

            if not evidence:
                raise RuntimeError("No evidence retrieved")

            start = time.perf_counter()
            answer = generate_answer(question, claim_id, evidence)
            record["generation_seconds"] = round(time.perf_counter() - start, 2)
            record["answer"] = answer
            record["status"] = (
                "generated_pending_review" if answer.strip() else "empty_answer"
            )
            print(answer, flush=True)
        except Exception as exc:
            record["status"] = "error"
            record["error"] = str(exc)
            print(f"ERROR: {exc}", flush=True)

        results.append(record)
        with (output / "results.jsonl").open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, default=str) + "\n")

with (output / "review.csv").open("w", newline="", encoding="utf-8") as file:
    fields = [
        "question_id", "claim_id", "method", "question", "status",
        "answer", "note_ids", "correctness", "citation_support",
        "completeness", "review_notes",
    ]
    writer = csv.DictWriter(file, fieldnames=fields)
    writer.writeheader()
    for record in results:
        row = {key: record.get(key, "") for key in fields}
        row["note_ids"] = "; ".join(
            str(item["note_id"]) for item in record["evidence"]
        )
        writer.writerow(row)

generated = sum(r["status"] == "generated_pending_review" for r in results)
print(f"\nGenerated answers: {generated}/{len(results)}")
print("Correctness: pending manual review")
print(f"Results saved to: {output.resolve()}")
