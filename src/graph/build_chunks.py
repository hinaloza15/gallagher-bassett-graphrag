from pathlib import Path
import pandas as pd
from transformers import AutoTokenizer
from src.config import EMBEDDING_MODEL

INPUT_FILE = Path("data/processed/notes_normalized.csv")
OUTPUT_FILE = Path("data/graph/chunks.csv")

# Sponsor feedback: use a machine-oriented token limit rather than a
# human-readability word limit. Notes that fit stay intact.
MAX_TOKENS = 512
OVERLAP_TOKENS = 64


def normalize_claim_id(value) -> str:
    """Normalize IDs such as 6977140.0 -> 6977140."""
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text


def build_tokenizer():
    return AutoTokenizer.from_pretrained(EMBEDDING_MODEL, use_fast=True)


def chunk_text(text: str, tokenizer, max_tokens=MAX_TOKENS, overlap_tokens=OVERLAP_TOKENS):
    """
    Split text using the BGE-M3 tokenizer.

    Returns dictionaries with exact character offsets so the chunk can always
    be traced back to the original normalized note text.
    """
    text = "" if pd.isna(text) else str(text).strip()
    if not text:
        return []

    encoded = tokenizer(
        text,
        add_special_tokens=False,
        return_offsets_mapping=True,
        truncation=False,
    )
    token_ids = encoded["input_ids"]
    offsets = encoded["offset_mapping"]

    if not token_ids:
        return []

    if len(token_ids) <= max_tokens:
        return [{
            "char_start": 0,
            "char_end": len(text),
            "text": text,
            "token_count": len(token_ids),
        }]

    chunks = []
    start_token = 0

    while start_token < len(token_ids):
        end_token = min(start_token + max_tokens, len(token_ids))

        char_start = offsets[start_token][0]
        char_end = offsets[end_token - 1][1]
        chunk = text[char_start:char_end].strip()

        chunks.append({
            "char_start": int(char_start),
            "char_end": int(char_end),
            "text": chunk,
            "token_count": int(end_token - start_token),
        })

        if end_token >= len(token_ids):
            break

        start_token = end_token - overlap_tokens

    return chunks


def main():
    df = pd.read_csv(INPUT_FILE)
    tokenizer = build_tokenizer()
    text_col = "normalized_text" if "normalized_text" in df.columns else "raw_text"

    rows = []
    notes_split = 0

    for _, row in df.iterrows():
        note_id = str(row["note_id"]).strip()
        claim_id = normalize_claim_id(row["claim_id"])
        text = row.get(text_col, "")
        note_chunks = chunk_text(text, tokenizer)

        if len(note_chunks) > 1:
            notes_split += 1

        for position, chunk in enumerate(note_chunks, start=1):
            rows.append({
                "chunk_id": f"{note_id}-C{position:02d}",
                "parent_id": note_id,
                "parent_kind": "note",
                "claim_id": claim_id,
                "note_id": note_id,
                "position": position,
                "text": chunk["text"],
                "char_start": chunk["char_start"],
                "char_end": chunk["char_end"],
                "word_count": len(chunk["text"].split()),
                "token_count": chunk["token_count"],
            })

    out = pd.DataFrame(rows)
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUTPUT_FILE, index=False)

    print(f"Notes: {df['note_id'].nunique()}")
    print(f"Chunks created: {len(out)}")
    print(f"Notes split into multiple chunks: {notes_split}")
    if not out.empty:
        print(f"Max chunk tokens: {out['token_count'].max()}")
        print(f"Average chunk tokens: {out['token_count'].mean():.1f}")
    print(f"Chunking: max={MAX_TOKENS} tokens, overlap={OVERLAP_TOKENS} tokens")
    print(f"Saved: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
