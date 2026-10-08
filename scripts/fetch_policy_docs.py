"""
Download the public NYS Workers' Compensation Board (WCB) documents used in the GraphRAG corpus,
verify each PDF is text-extractable, and (re)write data/policy_docs/{sources.md,metadata.csv,metadata.json}
plus plain-text copies in data/policy_docs_text/ for ingestion.

Run from the repo root:
    pip install pypdf requests
    python scripts/fetch_policy_docs.py                  # core docs only
    python scripts/fetch_policy_docs.py --include-extras # + extra body-part guidelines & fact sheets
    python scripts/fetch_policy_docs.py --no-download    # only regenerate sources.md / metadata from the list below
    python scripts/fetch_policy_docs.py --from-dir ~/Downloads --include-extras
        # use PDFs you already downloaded (matched by original WCB file name, e.g. KneeInjuryMTG2021.pdf);
        # copies them into data/policy_docs/ under the canonical names and skips any that are missing

All URLs were taken from the WCB Publications page (https://www.wcb.ny.gov/content/main/TheBoard/publications.jsp).
"""
import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

DEST = Path("data/policy_docs")
TEXT_DEST = Path("data/policy_docs_text")
PUBLICATIONS_PAGE = "https://www.wcb.ny.gov/content/main/TheBoard/publications.jsp"
BASE = "https://www.wcb.ny.gov/content/main"
MTG = f"{BASE}/hcpp/MedicalTreatmentGuidelines"
MTG_EDITION = "2021 edition, effective for dates of treatment on or after May 2, 2022"

# (filename, title, document_type, injury_category, audience, edition_note, url, extra=bool)
DOCS = [
    ("claimant_guide.pdf", "Claimant Quick Start Guide (Claimant Information Packet)", "claimant_guide",
     "general", "injured workers", "WCB-Claimant-QuickGuide-v1 (1-21)", f"{BASE}/TheBoard/ClaimantInformationPacket.pdf", False),
    ("employer_reporting.pdf", "Your Responsibilities as an Employer - Reporting Injury and Illness", "employer_guidance",
     "general", "employers", "EMP-TimelyReporting-fs-1-v1 2/17", f"{BASE}/TheBoard/EMP-TimelyReporting.pdf", False),
    ("back_guideline.pdf", "New York Mid and Low Back Injury Medical Treatment Guidelines", "medical_treatment_guideline",
     "back", "health care providers / claims staff", MTG_EDITION, f"{MTG}/MidandLowBackInjuryMTG2021.pdf", False),
    ("knee_guideline.pdf", "New York Knee Injury Medical Treatment Guidelines", "medical_treatment_guideline",
     "knee", "health care providers / claims staff", MTG_EDITION, f"{MTG}/KneeInjuryMTG2021.pdf", False),
    ("shoulder_guideline.pdf", "New York Shoulder Injury Medical Treatment Guidelines", "medical_treatment_guideline",
     "shoulder", "health care providers / claims staff", MTG_EDITION, f"{MTG}/ShoulderInjuryMTG2021.pdf", False),
    # ---- extras: cover other body parts that appear in the synthetic claim notes ----
    ("neck_guideline.pdf", "New York Neck Injury Medical Treatment Guidelines", "medical_treatment_guideline",
     "neck", "health care providers / claims staff", MTG_EDITION, f"{MTG}/NeckInjuryMTG2021.pdf", True),
    ("hand_wrist_forearm_guideline.pdf", "New York Hand, Wrist and Forearm Injuries (including Carpal Tunnel Syndrome)",
     "medical_treatment_guideline", "hand/wrist/forearm", "health care providers / claims staff", MTG_EDITION,
     f"{MTG}/HandWristForarmMTG2021.pdf", True),
    ("elbow_guideline.pdf", "New York Elbow Injuries", "medical_treatment_guideline", "elbow",
     "health care providers / claims staff", MTG_EDITION, f"{MTG}/ElbowMTG2021.pdf", True),
    ("ankle_foot_guideline.pdf", "New York Ankle and Foot Disorders", "medical_treatment_guideline", "ankle/foot",
     "health care providers / claims staff", MTG_EDITION, f"{MTG}/Ankle_FootMTG2021.pdf", True),
    ("hip_groin_guideline.pdf", "New York Hip and Groin Disorders", "medical_treatment_guideline", "hip/groin",
     "health care providers / claims staff", MTG_EDITION, f"{MTG}/Hip_GroinMTG2021.pdf", True),
    ("traumatic_brain_injury_guideline.pdf", "New York Traumatic Brain Injury Medical Treatment Guidelines",
     "medical_treatment_guideline", "head/brain (concussion)", "health care providers / claims staff", MTG_EDITION,
     f"{MTG}/TraumaticBrainInjuryMTG2021.pdf", True),
    ("eye_disorders_guideline.pdf", "New York Eye Disorders Medical Treatment Guidelines", "medical_treatment_guideline",
     "eye", "health care providers / claims staff", MTG_EDITION, f"{MTG}/EyeDisordersMTG2021.pdf", True),
    ("file_claim_fact_sheet.pdf", "What to Expect When You File a Claim - Your Workers' Compensation Benefits",
     "claimant_fact_sheet", "general", "injured workers", "WCB fact sheet", f"{BASE}/TheBoard/file-claim-fact-sheet.pdf", True),
    ("lost_wage_benefits_fact_sheet.pdf", "Lost Wage Benefits", "claimant_fact_sheet", "general", "injured workers",
     "WCB fact sheet", f"{BASE}/TheBoard/indemnity-fact-sheet.pdf", True),
]
FIELDS = ["file", "title", "document_type", "injury_category", "audience", "edition_note", "publisher",
          "source_url", "pages", "text_chars", "text_extractable", "sha256"]


def fetch(url):
    if url.startswith("file://"):  # used only for local testing
        from urllib.request import urlopen
        return urlopen(url).read()
    import requests
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (class project; GraphRAG corpus builder)"}, timeout=120)
    r.raise_for_status()
    return r.content


def extract(path):
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    pages = [(p.extract_text() or "") for p in reader.pages]
    return len(pages), pages


def write_sources(rows):
    lines = [
        "# Public NYS Workers' Compensation policy documents",
        "",
        "Real, public documents published by the New York State Workers' Compensation Board (WCB). "
        "They complement the **synthetic** claim notes in `data/synthetic_notes/`.",
        "",
        f"Source index: <{PUBLICATIONS_PAGE}>",
        "",
        "| Local file | Title | Type | Injury category | Source link |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| `{r['file']}` | {r['title']} | {r['document_type']} | {r['injury_category']} | <{r['source_url']}> |")
    lines += [
        "",
        "## Notes",
        "- Medical Treatment Guidelines (MTGs) are the 2021 editions, effective for dates of treatment on or after May 2, 2022.",
        "- Full metadata (audience, edition, page count, extractable-text check, SHA-256) is in `metadata.csv` / `metadata.json`.",
        "- Plain-text copies for ingestion are in `data/policy_docs_text/`.",
        "- Regenerate or re-verify everything with `python scripts/fetch_policy_docs.py`.",
        "- WCB publications are public documents; MTGs include ACOEM/ReedGroup material used by the Board with permission — "
        "cite the source link when quoting.",
        "",
    ]
    (DEST / "sources.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--include-extras", action="store_true")
    ap.add_argument("--no-download", action="store_true")
    ap.add_argument("--from-dir", help="folder of already-downloaded PDFs (original WCB file names)")
    ap.add_argument("--min-chars-per-page", type=int, default=200, help="below this avg, flag as probably scanned")
    a = ap.parse_args()

    DEST.mkdir(parents=True, exist_ok=True)
    TEXT_DEST.mkdir(parents=True, exist_ok=True)
    rows, failures = [], []
    for fn, title, dtype, cat, aud, ed, url, extra in DOCS:
        if extra and not a.include_extras:
            continue
        row = dict(file=fn, title=title, document_type=dtype, injury_category=cat, audience=aud, edition_note=ed,
                   publisher="NYS Workers' Compensation Board", source_url=url,
                   pages="", text_chars="", text_extractable="", sha256="")
        if a.from_dir:
            src = Path(a.from_dir).expanduser() / Path(url).name
            if not src.exists():
                print(f"SKIP {fn}: {src.name} not found in {a.from_dir}")
                continue
        if not a.no_download:
            path = DEST / fn
            try:
                data = src.read_bytes() if a.from_dir else fetch(url)
                if not data.startswith(b"%PDF"):
                    raise ValueError("response is not a PDF")
                path.write_bytes(data)
                n, pages = extract(path)
                chars = sum(len(p) for p in pages)
                ok = n > 0 and chars / n >= a.min_chars_per_page
                (TEXT_DEST / (Path(fn).stem + ".txt")).write_text(
                    "\n\n".join(f"[page {i + 1}]\n{t}" for i, t in enumerate(pages)), encoding="utf-8")
                row.update(pages=n, text_chars=chars, text_extractable="yes" if ok else "NO - needs OCR",
                           sha256=hashlib.sha256(data).hexdigest())
                print(f"{'OK  ' if ok else 'WARN'} {fn}: {n} pages, {chars:,} chars")
                if not ok:
                    failures.append(fn)
            except Exception as e:
                print(f"FAIL {fn}: {e}")
                failures.append(fn)
                row["text_extractable"] = f"FAILED: {e}"
        rows.append(row)

    with open(DEST / "metadata.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    (DEST / "metadata.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    write_sources(rows)
    print(f"\nWrote sources.md, metadata.csv, metadata.json for {len(rows)} documents.")
    if failures:
        print("Needs attention:", ", ".join(failures))
        sys.exit(1)


if __name__ == "__main__":
    main()
