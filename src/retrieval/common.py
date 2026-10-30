from functools import lru_cache
from pathlib import Path
import pickle
import numpy as np
from sentence_transformers import SentenceTransformer
from src.config import EMBEDDING_MODEL

EMBEDDINGS_FILE = Path("data/processed/chunk_embeddings.pkl")

@lru_cache(maxsize=1)
def load_index():
    with open(EMBEDDINGS_FILE, "rb") as f:
        df = pickle.load(f)
    matrix = np.vstack(df["embedding"].apply(np.asarray).to_numpy()).astype("float32")
    return df.reset_index(drop=True), matrix

@lru_cache(maxsize=1)
def load_model():
    return SentenceTransformer(EMBEDDING_MODEL)

def embed_question(question: str):
    return load_model().encode([question], normalize_embeddings=True)[0].astype("float32")

def semantic_rank(question: str, claim_id: str, top_k=5, candidate_ids=None):
    df, matrix = load_index()
    q = embed_question(question)

    mask = df["claim_id"].astype(str).eq(str(claim_id))
    if candidate_ids is not None:
        candidate_ids = set(map(str, candidate_ids))
        mask &= df["chunk_id"].astype(str).isin(candidate_ids)

    idx = np.flatnonzero(mask.to_numpy())
    if len(idx) == 0:
        return []

    scores = matrix[idx] @ q
    order = np.argsort(-scores)[:top_k]

    out = []
    for rank, pos in enumerate(order, start=1):
        row_idx = idx[pos]
        row = df.iloc[row_idx]
        out.append({
            "rank": rank,
            "chunk_id": str(row["chunk_id"]),
            "note_id": str(row["note_id"]),
            "claim_id": str(row["claim_id"]),
            "text": str(row["text"]),
            "semantic_score": float(scores[pos]),
        })
    return out
