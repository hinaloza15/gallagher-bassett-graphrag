"""
Run GraphRAG on DEVELOPMENT questions only.

Use this while tuning. Do not use final/holdout questions until the retrieval
logic is frozen.
"""
from pathlib import Path
import time
import pandas as pd

from src.retrieval.graphrag_retriever import retrieve
from src.retrieval.question_analyzer import analyze_question

QUESTIONS_FILE = Path("evaluation/questions.csv")
OUT_FILE = Path("evaluation/results/graphrag_dev_results.csv")


def parse_set(value):
    if pd.isna(value) or not str(value).strip():
        return set()
    return {x.strip() for x in str(value).split("|") if x.strip()}


def retrieval_metrics(retrieved, gold_note_ids):
    note_ids = [str(x["note_id"]) for x in retrieved]
    unique_ids = list(dict.fromkeys(note_ids))
    hits = set(unique_ids) & gold_note_ids

    if not gold_note_ids:
        return {"hit_at_5": None, "precision_at_5": None, "recall_at_5": None, "mrr": None}

    rr = 0.0
    for rank, note_id in enumerate(unique_ids, 1):
        if note_id in gold_note_ids:
            rr = 1.0 / rank
            break

    return {
        "hit_at_5": int(bool(hits)),
        "precision_at_5": len(hits) / max(1, len(unique_ids)),
        "recall_at_5": len(hits) / len(gold_note_ids),
        "mrr": rr,
    }


def overlap_metrics(pred, gold):
    pred, gold = set(pred), set(gold)
    if not gold:
        return {"precision": None, "recall": None, "f1": None}
    tp = len(pred & gold)
    p = tp / len(pred) if pred else 0.0
    r = tp / len(gold) if gold else 0.0
    f1 = (2*p*r/(p+r)) if p+r else 0.0
    return {"precision": p, "recall": r, "f1": f1}


def main():
    questions = pd.read_csv(QUESTIONS_FILE, dtype={"claim_id": str})
    if "split" in questions.columns:
        questions = questions[questions["split"].astype(str).str.lower().eq("dev")].copy()

    rows = []
    for _, q in questions.iterrows():
        qid = str(q["question_id"])
        claim_id = str(q["claim_id"])
        question = str(q["question"])
        print(f"\n{qid} | {claim_id} | {question}")

        plan = analyze_question(question)
        t0 = time.perf_counter()
        evidence = retrieve(question, claim_id, top_k=5)
        seconds = time.perf_counter() - t0

        gold_notes = parse_set(q.get("gold_note_ids"))
        metrics = retrieval_metrics(evidence, gold_notes)

        gold_entities = parse_set(q.get("gold_entities"))
        gold_rels = parse_set(q.get("gold_relationships"))
        gold_events = parse_set(q.get("gold_event_types"))

        em = overlap_metrics(plan.get("entities", []), gold_entities)
        rm = overlap_metrics(plan.get("relationships", []), gold_rels)
        tm = overlap_metrics(plan.get("event_types", []), gold_events)

        rows.append({
            "question_id": qid,
            "claim_id": claim_id,
            "category": q.get("category", ""),
            "question": question,
            "retrieved_note_ids": "|".join(str(x["note_id"]) for x in evidence),
            "gold_note_ids": "|".join(sorted(gold_notes)),
            "hit_at_5": metrics["hit_at_5"],
            "precision_at_5": metrics["precision_at_5"],
            "recall_at_5": metrics["recall_at_5"],
            "mrr": metrics["mrr"],
            "retrieval_seconds": seconds,
            "candidate_count": evidence[0].get("candidate_count", 0) if evidence else 0,
            "planner": plan.get("planner", ""),
            "detected_intents": "|".join(plan.get("intents", [])),
            "detected_entities": "|".join(plan.get("entities", [])),
            "detected_relationships": "|".join(plan.get("relationships", [])),
            "detected_event_types": "|".join(plan.get("event_types", [])),
            "entity_recall": em["recall"],
            "relationship_recall": rm["recall"],
            "event_type_recall": tm["recall"],
            "top1_graph_reasons": "|".join(evidence[0].get("graph_reasons", [])) if evidence else "",
        })

        print("  plan:", plan)
        print("  top5:", [x["note_id"] for x in evidence])
        print("  metrics:", metrics)

    out = pd.DataFrame(rows)
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_FILE, index=False)

    print("\n=== DEV SUMMARY ===")
    print(out.groupby("category")[["hit_at_5","precision_at_5","recall_at_5","mrr"]].mean().round(3))
    print("\nOVERALL")
    print(out[["hit_at_5","precision_at_5","recall_at_5","mrr"]].mean().round(3))
    print(f"\nSaved: {OUT_FILE}")


if __name__ == "__main__":
    main()
