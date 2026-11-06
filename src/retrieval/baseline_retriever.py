from src.retrieval.common import semantic_rank

def retrieve(question: str, claim_id: str, top_k=5):
    return semantic_rank(question, claim_id, top_k=top_k)

if __name__ == "__main__":
    q = "How did the claimant's work restrictions change over time?"
    for row in retrieve(q, "6977160"):
        print(row["rank"], row["note_id"], row["semantic_score"])
        print(row["text"][:300], "\n")
