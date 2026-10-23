import re
from pathlib import Path

import fitz
import pandas as pd


PDF_FOLDER = Path("data/claims")
OUTPUT_FILE = Path("data/processed/notes.csv")


NOTE_PATTERN = re.compile(
    r"(?m)^(\d{4}-\d{2}-\d{2})\s+"
    r"(.+?)\s+"
    r"\(([^)]+)\)\s+"
    r"(SYN-(\d+)-(\d+))\s*$"
)


def extract_pdf_text(path):

    doc = fitz.open(path)

    pages = []

    for page in doc:

        pages.append(
            page.get_text("text")
        )

    return "\n".join(pages)


def parse_claim_header(text):

    claim_match = re.search(
        r"Claim\s+(\d+)\s+-\s+Claim Notes",
        text
    )

    if not claim_match:
        raise ValueError("Claim ID not found")

    claim_id = claim_match.group(1)

    header = text[:2500].replace("\n", " ")

    metadata = re.search(
        r"Claimant:\s*(.*?)\s*\|\s*"
        r"Employer:\s*(.*?)\s*\|\s*"
        r"Carrier:\s*(.*?)\s*\|\s*"
        r"County:\s*(.*?)\s*\|\s*"
        r"Status:\s*(.*?)\s*\|\s*"
        r"(\d+)\s+notes",
        header
    )

    if not metadata:

        raise ValueError(
            f"Could not parse header for {claim_id}"
        )

    claimant, employer, carrier, county, status, total_notes = (
        metadata.groups()
    )

    return {
        "claim_id": claim_id,
        "claimant": claimant.strip(),
        "employer": employer.strip(),
        "carrier": carrier.strip(),
        "county": county.strip(),
        "claim_status": status.strip(),
        "expected_notes": int(total_notes)
    }


def parse_pdf(path):

    text = extract_pdf_text(path)

    metadata = parse_claim_header(text)

    matches = list(
        NOTE_PATTERN.finditer(text)
    )

    notes = []

    for i, match in enumerate(matches):

        start = match.end()

        if i + 1 < len(matches):

            end = matches[i + 1].start()

        else:

            end = len(text)

        note_text = (
            text[start:end]
            .strip()
        )

        notes.append({
            **metadata,

            "pdf_file": path.name,

            "note_date": match.group(1),

            "author": match.group(2).strip(),

            "author_role": match.group(3).strip(),

            "note_id": match.group(4),

            "note_sequence": int(
                match.group(6)
            ),

            "raw_text": note_text
        })

    return metadata, notes


def main():

    all_notes = []

    validation = []

    pdf_files = sorted(
        PDF_FOLDER.glob("*.pdf")
    )

    print(
        f"Found {len(pdf_files)} PDFs"
    )

    for pdf in pdf_files:

        metadata, notes = parse_pdf(pdf)

        all_notes.extend(notes)

        validation.append({
            "claim_id":
                metadata["claim_id"],

            "expected":
                metadata["expected_notes"],

            "parsed":
                len(notes),

            "correct":
                metadata["expected_notes"]
                ==
                len(notes)
        })

    df = pd.DataFrame(all_notes)

    check_df = pd.DataFrame(validation)

    print(check_df)

    print(
        "\nClaims:",
        df["claim_id"].nunique()
    )

    print(
        "Notes:",
        len(df)
    )

    print(
        "Duplicate note IDs:",
        df["note_id"].duplicated().sum()
    )

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    df.to_csv(
        OUTPUT_FILE,
        index=False
    )

    print(
        "\nSaved:",
        OUTPUT_FILE
    )


if __name__ == "__main__":

    main()