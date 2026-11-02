from functools import lru_cache
from pathlib import Path
import pickle
import numpy as np
import pandas as pd
import torch
from sentence_transformers import SentenceTransformer
from src.config import EMBEDDING_MODEL

EMBEDDINGS_FILE = Path("data/processed/chunk_embeddings.pkl")


def normalize_claim_id(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text


def get_device():
    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


@lru_cache(maxsize=1)
def load_index():
    with open(EMBEDDINGS_FILE, "rb") as f:
        df = pickle.load(f)

    df = df.reset_index(drop=True).copy()
    df["claim_id"] = df["claim_id"].apply(normalize_claim_id)
    matrix = np.vstack(df["embedding"].apply(np.asarray).to_numpy()).astype("float32")
    return df, matrix


@lru_cache(maxsize=1)
def load_model():
    return SentenceTransformer(EMBEDDING_MODEL, device=get_device())


def embed_question(question: str):
    return load_model().encode([question], normalize_embeddings=True)[0].astype("float32")


def semantic_rank(question: str, claim_id: str, top_k=5, candidate_ids=None):
    """Rank chunks by normalized dense-vector dot product (= cosine similarity)."""
    df, matrix = load_index()
    q = embed_question(question)
    claim_id = normalize_claim_id(claim_id)

    mask = df["claim_id"].eq(claim_id)

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
            "claim_id": normalize_claim_id(row["claim_id"]),
            "text": str(row["text"]),
            "semantic_score": float(scores[pos]),
        })

    return out
