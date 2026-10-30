from pathlib import Path
import re
import pandas as pd

INPUT_FILE = Path("data/processed/notes_normalized.csv")
OUTPUT_FILE = Path("data/graph/chunks.csv")

MAX_WORDS = 220
OVERLAP_WORDS = 40

def word_spans(text: str):
    return [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]

def chunk_text(text: str, max_words=MAX_WORDS, overlap_words=OVERLAP_WORDS):
    text = "" if pd.isna(text) else str(text)
    spans = word_spans(text)
    if not spans:
        return [(0, 0, "")]
    if len(spans) <= max_words:
        return [(0, len(text), text)]

    chunks = []
    start_word = 0
    while start_word < len(spans):
        end_word = min(start_word + max_words, len(spans))
        char_start = spans[start_word][0]
        char_end = spans[end_word - 1][1]
        chunks.append((char_start, char_end, text[char_start:char_end]))
        if end_word == len(spans):
            break
        start_word = max(0, end_word - overlap_words)
    return chunks

def main():
    df = pd.read_csv(INPUT_FILE)
    text_col = "normalized_text" if "normalized_text" in df.columns else "raw_text"
    rows = []

    for _, row in df.iterrows():
        note_id = str(row["note_id"])
        claim_id = str(row["claim_id"])
        text = row.get(text_col, "")

        for position, (char_start, char_end, chunk) in enumerate(chunk_text(text), start=1):
            rows.append({
                "chunk_id": f"{note_id}-C{position:02d}",
                "parent_id": note_id,
                "parent_kind": "note",
                "claim_id": claim_id,
                "note_id": note_id,
                "position": position,
                "text": chunk,
                "char_start": char_start,
                "char_end": char_end,
                "word_count": len(chunk.split()),
            })

    out = pd.DataFrame(rows)
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUTPUT_FILE, index=False)

    print(f"Notes: {df['note_id'].nunique()}")
    print(f"Chunks created: {len(out)}")
    print(f"Saved: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
