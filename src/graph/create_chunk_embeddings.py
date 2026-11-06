from pathlib import Path
import pickle
import pandas as pd
import torch
from sentence_transformers import SentenceTransformer
from src.config import EMBEDDING_MODEL

INPUT_FILE = Path("data/graph/chunks.csv")
OUTPUT_FILE = Path("data/processed/chunk_embeddings.pkl")

def get_device():
    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"

def main():
    df = pd.read_csv(INPUT_FILE)
    device = get_device()

    print(f"Loaded {len(df)} chunks")
    print(f"Using device: {device}")
    print(f"Embedding model: {EMBEDDING_MODEL}")

    model = SentenceTransformer(EMBEDDING_MODEL, device=device)
    embeddings = model.encode(
        df["text"].fillna("").tolist(),
        batch_size=8,
        normalize_embeddings=True,
        show_progress_bar=True,
    )

    df["embedding"] = [x.tolist() for x in embeddings]

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "wb") as f:
        pickle.dump(df, f)

    print(f"Embedding shape: {embeddings.shape}")
    print(f"Saved: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
