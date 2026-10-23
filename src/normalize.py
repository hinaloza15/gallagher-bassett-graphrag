import re
import pandas as pd


INPUT_FILE = (
    "data/processed/notes.csv"
)

OUTPUT_FILE = (
    "data/processed/notes_normalized.csv"
)


ABBREVIATIONS = {

    r"\bclmt\b":
        "claimant",

    r"\bcx\b":
        "claimant",

    r"\bIW\b":
        "injured worker",

    r"\bEE\b":
        "employee",

    r"\bER\b":
        "employer",

    r"\bPT\b":
        "physical therapy",

    r"\bRTW\b":
        "return to work",

    r"\bf/u\b":
        "follow up",

    r"\bIME\b":
        "independent medical examination",

    r"\bNCM\b":
        "nurse case manager",

    r"\bLVM\b":
        "left voicemail",

    r"\btx\b":
        "treatment",

    r"\brestr\b":
        "restrictions"
}


def normalize_text(text):

    text = str(text)

    output = text

    for pattern, replacement in (
        ABBREVIATIONS.items()
    ):

        output = re.sub(
            pattern,
            replacement,
            output,
            flags=re.IGNORECASE
        )

    output = re.sub(
        r"\s+",
        " ",
        output
    )

    return output.strip()


def main():

    df = pd.read_csv(
        INPUT_FILE
    )

    df["normalized_text"] = (
        df["raw_text"]
        .apply(normalize_text)
    )

    # Same chunking for all approaches.
    # One claim note = one chunk.

    df["chunk_text"] = (

        "Date: "
        + df["note_date"].astype(str)

        + ". Author role: "
        + df["author_role"].astype(str)

        + ". "
        + df["normalized_text"]
    )

    df.to_csv(
        OUTPUT_FILE,
        index=False
    )

    print(
        "Saved normalized notes:",
        len(df)
    )


if __name__ == "__main__":

    main()