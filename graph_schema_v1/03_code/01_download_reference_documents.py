"""
01_download_reference_documents.py

Downloads the public NY Workers' Compensation Board documents listed in
02_reference_data/06_reference_documents_manifest.csv into data/reference_docs/.
The graph builder then splits them into Chunk nodes (HAS_CHUNK) so GraphRAG and hybrid RAG can retrieve them.

Run on a computer with internet access, from graph_schema_v1/:
    python 03_code/01_download_reference_documents.py
Options:
    --skip-internal-only   do not download the Medical Treatment Guideline PDFs

LICENSING: rows marked redistribution = internal_reference_only (the Medical Treatment Guidelines)
are for internal reference. data/ is in .gitignore, so they are never committed. Do not upload them
to a public repository.
"""
import argparse, csv, os, sys, time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "reference_docs"))
    ap.add_argument("--skip-internal-only", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    rows = list(csv.DictReader(open(os.path.join(ROOT, "02_reference_data", "06_reference_documents_manifest.csv"))))
    ok, failed = 0, []
    for r in rows:
        if a.skip_internal_only and r["redistribution"] != "public":
            continue
        dest = os.path.join(a.out, r["local_file"])
        if os.path.exists(dest) and os.path.getsize(dest) > 1000:
            print(f"have  {r['doc_id']} {r['local_file']}"); ok += 1; continue
        try:
            req = urllib.request.Request(r["url"], headers={"User-Agent": "Mozilla/5.0 (UIC IDS 560 capstone, research use)"})
            with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as f:
                f.write(resp.read())
            print(f"saved {r['doc_id']} {r['local_file']} ({os.path.getsize(dest):,} bytes)"); ok += 1
            time.sleep(1)
        except Exception as e:
            failed.append((r["doc_id"], r["url"], str(e)[:120]))
            print(f"FAILED {r['doc_id']} {r['url']}: {e}")
    print(f"\n{ok} documents ready in {a.out}; {len(failed)} failed.")
    if failed:
        print("Download the failed ones in a browser and save them under the local_file name in the manifest.")
        sys.exit(1)


if __name__ == "__main__":
    main()
