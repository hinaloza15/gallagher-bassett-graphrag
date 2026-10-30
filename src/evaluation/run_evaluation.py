from pathlib import Path
import time
import pandas as pd

from src.retrieval.baseline_retriever import retrieve as baseline_retrieve
from src.retrieval.graph_retriever import retrieve as graph_retrieve
from src.retrieval.hybrid_retriever import retrieve as hybrid_retrieve
from src.generation.answer_generator import generate_answer

QUESTIONS_FILE = Path("evaluation/questions.csv")
OUT_FILE = Path("evaluation/results/model_comparison.csv")

RETRIEVERS = {
    "baseline": baseline_retrieve,
    "graphrag": graph_retrieve,
    "hybrid": hybrid_retrieve,
}

def parse_gold(value):
    if pd.isna(value) or not str(value).strip():
        return set()
    return {x.strip() for x in str(value).split("|") if x.strip()}

def retrieval_metrics(retrieved, gold_note_ids):
    retrieved_note_ids = [str(x["note_id"]) for x in retrieved]
    retrieved_set = set(retrieved_note_ids)

    if not gold_note_ids:
        return {"hit_at_5": None, "precision_at_5": None, "recall_at_5": None, "mrr": None}

    hits = retrieved_set & gold_note_ids
    hit_at_5 = int(bool(hits))
    precision = len(hits) / max(1, len(retrieved_set))
    recall = len(hits) / len(gold_note_ids)

    rr = 0.0
    for rank, note_id in enumerate(retrieved_note_ids, start=1):
        if note_id in gold_note_ids:
            rr = 1.0 / rank
            break

    return {"hit_at_5": hit_at_5, "precision_at_5": precision, "recall_at_5": recall, "mrr": rr}

def main(generate=True):
    questions = pd.read_csv(QUESTIONS_FILE)
    rows = []

    for _, q in questions.iterrows():
        question_id = str(q["question_id"])
        claim_id = str(q["claim_id"])
        question = str(q["question"])
        category = str(q["category"])
        gold = parse_gold(q.get("gold_note_ids"))

        for approach, retriever in RETRIEVERS.items():
            print(f"\n{question_id} | {approach}")

            t0 = time.perf_counter()
            evidence = retriever(question, claim_id, top_k=5)
            retrieval_seconds = time.perf_counter() - t0

            answer = ""
            generation_seconds = 0.0

            if generate:
                t1 = time.perf_counter()
                answer = generate_answer(question, claim_id, evidence)
                generation_seconds = time.perf_counter() - t1

            metrics = retrieval_metrics(evidence, gold)

            rows.append({
                "question_id": question_id,
                "claim_id": claim_id,
                "category": category,
                "question": question,
                "approach": approach,
                "retrieved_note_ids": "|".join(x["note_id"] for x in evidence),
                "retrieved_chunk_ids": "|".join(x["chunk_id"] for x in evidence),
                "retrieval_seconds": retrieval_seconds,
                "generation_seconds": generation_seconds,
                "total_seconds": retrieval_seconds + generation_seconds,
                "answer": answer,
                **metrics,
                "answer_correctness_0_2": "",
                "evidence_relevance_0_2": "",
                "citation_correctness_0_2": "",
                "conflict_handling_0_2": "",
                "entity_resolution_0_2": "",
                "claim_scope_pass_fail": "",
                "review_notes": "",
            })

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(OUT_FILE, index=False)
    print(f"\nSaved: {OUT_FILE}")

if __name__ == "__main__":
    main(generate=True)
