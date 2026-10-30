from src.retrieval.baseline_retriever import retrieve as baseline_retrieve
from src.retrieval.graph_retriever import retrieve as graph_retrieve
from src.retrieval.common import semantic_rank

def retrieve(question: str, claim_id: str, top_k=5):
    direct = baseline_retrieve(question, claim_id, top_k=10)
    graph = graph_retrieve(question, claim_id, seed_k=2, top_k=10)

    rrf = {}
    for source_name, rows in [("direct", direct), ("graph", graph)]:
        for rank, row in enumerate(rows, start=1):
            cid = row["chunk_id"]
            if cid not in rrf:
                rrf[cid] = {
                    "chunk_id": cid,
                    "note_id": row["note_id"],
                    "claim_id": row["claim_id"],
                    "text": row["text"],
                    "rrf_score": 0.0,
                    "sources": set(),
                }
            rrf[cid]["rrf_score"] += 1.0 / (60 + rank)
            rrf[cid]["sources"].add(source_name)

    ordered_ids = [x["chunk_id"] for x in sorted(rrf.values(), key=lambda x: x["rrf_score"], reverse=True)]
    semantic = semantic_rank(question, claim_id, top_k=min(30, len(ordered_ids)), candidate_ids=ordered_ids)
    semantic_by_id = {x["chunk_id"]: x["semantic_score"] for x in semantic}

    rows = []
    for cid in ordered_ids:
        row = rrf[cid]
        row["sources"] = sorted(row["sources"])
        row["semantic_score"] = semantic_by_id.get(cid, 0.0)
        row["final_score"] = row["semantic_score"] + 5.0 * row["rrf_score"]
        rows.append(row)

    rows.sort(key=lambda x: x["final_score"], reverse=True)

    for rank, row in enumerate(rows[:top_k], start=1):
        row["rank"] = rank

    return rows[:top_k]
