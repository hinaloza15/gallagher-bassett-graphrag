"""
Hybrid RAG end-to-end QA test: retrieve with the hybrid retriever, generate an
answer, and save everything for manual scoring.

Usage (from the repo root):
    python -m src.evaluation.run_hybrid_qa                     # all questions in questions.csv
    python -m src.evaluation.run_hybrid_qa --ids Q03 Q05       # selected questions
    python -m src.evaluation.run_hybrid_qa --question "Who is Maya Patel?" --claim 6977140
    python -m src.evaluation.run_hybrid_qa --no-generate       # retrieval only (fast)
    python -m src.evaluation.run_hybrid_qa --split dev         # dev questions only (use while tuning)
    python -m src.evaluation.run_hybrid_qa --mode seeded       # original vector-seeded hybrid

Default mode is "fused": BGE-M3 seeds + seed graph expansion + Qwen-planned
GraphRAG traversal, fused and passed through GraphRAG's coverage-aware Top-K.
"""
import argparse
import re
import time
from pathlib import Path

import pandas as pd

from src.retrieval.hybrid_retriever import retrieve as hybrid_retrieve
from src.evaluation.run_evaluation import parse_gold, retrieval_metrics

QUESTIONS_FILE = Path("evaluation/questions.csv")
OUT_FILE = Path("evaluation/results/hybrid_qa.csv")


def citation_check(answer: str, n_evidence: int):
    """Which [E#] tags the answer cites, and whether any point to nonexistent evidence."""
    cited = sorted({int(x) for x in re.findall(r"\[E(\d+)\]", answer)})
    invalid = [c for c in cited if c < 1 or c > n_evidence]
    return cited, invalid


def run_one(qid, claim_id, question, gold, seed_k, top_k, generate, mode):
    print("=" * 80)
    print(f"{qid} | claim {claim_id}\nQ: {question}\n")

    t0 = time.perf_counter()
    evidence = hybrid_retrieve(question, claim_id, seed_k=seed_k, top_k=top_k, mode=mode)
    retrieval_s = time.perf_counter() - t0

    if evidence and evidence[0].get("detected_intents") is not None:
        print(f"plan: intents={evidence[0].get('detected_intents')} "
              f"events={evidence[0].get('detected_event_types')} planner={evidence[0].get('planner')}")
    for i, r in enumerate(evidence, start=1):
        reasons = ",".join(r.get("graph_reasons", []))
        print(f"[E{i}] {r['note_id']}  final={r['final_score']:.4f}  ({r.get('source', '-')})  {reasons}")
        print(f"     {r['text'][:160].replace(chr(10), ' ')}")
    if evidence:
        print(f"\ncandidates={evidence[0]['candidate_count']}  retrieval={retrieval_s:.2f}s")

    answer, gen_s = "", 0.0
    if generate and evidence:
        from src.generation.answer_generator import generate_answer
        t1 = time.perf_counter()
        answer = generate_answer(question, claim_id, evidence)
        gen_s = time.perf_counter() - t1
        print(f"\nANSWER ({gen_s:.1f}s):\n{answer}\n")

    cited, invalid = citation_check(answer, len(evidence))
    if generate:
        print(f"cited={cited}  invalid_citations={invalid}")

    return {
        "question_id": qid,
        "claim_id": claim_id,
        "question": question,
        "retrieved_note_ids": "|".join(r["note_id"] for r in evidence),
        "hybrid_mode": mode,
        "graph_sources": "|".join(r.get("source", "-") for r in evidence),
        "top1_graph_reasons": "|".join(evidence[0].get("graph_reasons", [])) if evidence else "",
        "planner": evidence[0].get("planner", "") if evidence else "",
        "detected_intents": "|".join(evidence[0].get("detected_intents", [])) if evidence else "",
        "candidate_count": evidence[0]["candidate_count"] if evidence else 0,
        "retrieval_seconds": retrieval_s,
        "generation_seconds": gen_s,
        "answer": answer,
        "cited_evidence": "|".join(f"E{c}" for c in cited),
        "invalid_citations": "|".join(f"E{c}" for c in invalid),
        "has_citations": bool(cited),
        **retrieval_metrics(evidence, gold),
        # Manual scoring columns (same rubric as run_evaluation.py)
        "answer_correctness_0_2": "",
        "evidence_relevance_0_2": "",
        "citation_correctness_0_2": "",
        "conflict_handling_0_2": "",
        "entity_resolution_0_2": "",
        "claim_scope_pass_fail": "",
        "review_notes": "",
    }


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ids", nargs="*", help="question_ids from questions.csv to run")
    p.add_argument("--question", help="ad-hoc question (requires --claim)")
    p.add_argument("--claim", help="claim id for --question")
    p.add_argument("--seed-k", type=int, default=5)
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--mode", choices=["fused", "seeded"], default=None,
                   help="hybrid mode (default: HYBRID_MODE env var, else fused)")
    p.add_argument("--split", help="only run questions from this split (e.g. dev)")
    p.add_argument("--no-generate", action="store_true", help="retrieval only")
    p.add_argument("--out", type=Path, default=OUT_FILE)
    args = p.parse_args()

    generate = not args.no_generate
    from src.retrieval.hybrid_retriever import HYBRID_MODE
    mode = args.mode or HYBRID_MODE
    rows = []

    if args.question:
        if not args.claim:
            p.error("--question requires --claim")
        rows.append(run_one("ADHOC", args.claim, args.question, set(),
                            args.seed_k, args.top_k, generate, mode))
    else:
        qs = pd.read_csv(QUESTIONS_FILE, dtype=str)
        if args.ids:
            qs = qs[qs["question_id"].isin(args.ids)]
        if args.split and "split" in qs.columns:
            qs = qs[qs["split"].str.lower().eq(args.split.lower())]
        for _, q in qs.iterrows():
            row = run_one(q["question_id"], q["claim_id"], q["question"],
                          parse_gold(q.get("gold_note_ids")),
                          args.seed_k, args.top_k, generate, mode)
            for col in ("split", "category", "difficulty", "gold_answer"):
                row[col] = q.get(col, "")
            rows.append(row)

    if rows and "difficulty" in rows[0]:
        df = pd.DataFrame(rows)
        metric_cols = ["hit_at_5", "precision_at_5", "recall_at_5", "mrr"]
        scored = df.dropna(subset=["hit_at_5"])
        if not scored.empty:
            print("\nRetrieval metrics by difficulty:")
            print(scored.groupby("difficulty")[metric_cols].mean().round(3).to_string())
            print("\nRetrieval metrics by category:")
            print(scored.groupby("category")[metric_cols].mean().round(3).to_string())
            print("\nOverall:")
            print(scored[metric_cols].mean().round(3).to_string())

    args.out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(args.out, index=False)
    print(f"\nSaved: {args.out}")


if __name__ == "__main__":
    main()
