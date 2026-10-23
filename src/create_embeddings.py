import pickle

import pandas as pd
import torch

from sentence_transformers import SentenceTransformer

from config import EMBEDDING_MODEL


INPUT_FILE = "data/processed/notes_events.csv"
OUTPUT_FILE = "data/processed/notes_embeddings.pkl"


def get_device():

    if torch.cuda.is_available():
        return "cuda"

    elif torch.backends.mps.is_available():
        return "mps"

    else:
        return "cpu"


def main():

    # -----------------------------
    # 1. Load processed notes
    # -----------------------------

    df = pd.read_csv(INPUT_FILE)

    print(f"Loaded {len(df)} notes")


    # -----------------------------
    # 2. Choose device
    # -----------------------------

    device = get_device()

    print(f"Using device: {device}")


    # -----------------------------
    # 3. Load embedding model
    # -----------------------------

    print(f"Loading embedding model: {EMBEDDING_MODEL}")

    model = SentenceTransformer(
        EMBEDDING_MODEL,
        device=device
    )


    # -----------------------------
    # 4. Create embeddings
    # -----------------------------

    texts = df["chunk_text"].fillna("").tolist()

    print("Creating embeddings...")

    embeddings = model.encode(

        texts,

        batch_size=8,

        normalize_embeddings=True,

        show_progress_bar=True
    )


    # -----------------------------
    # 5. Store embeddings
    # -----------------------------

    df["embedding"] = [
        embedding.tolist()
        for embedding in embeddings
    ]


    # -----------------------------
    # 6. Validation
    # -----------------------------

    print("\nEmbedding creation complete")

    print(
        "Embedding matrix shape:",
        embeddings.shape
    )

    print(
        "Number of notes:",
        len(df)
    )

    print(
        "Embedding dimension:",
        len(df.iloc[0]["embedding"])
    )


    # -----------------------------
    # 7. Save file
    # -----------------------------

    with open(
        OUTPUT_FILE,
        "wb"
    ) as file:

        pickle.dump(
            df,
            file
        )


    print(
        f"\nSaved embeddings to: {OUTPUT_FILE}"
    )


if __name__ == "__main__":

    main()