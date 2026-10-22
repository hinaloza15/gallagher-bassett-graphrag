#!/usr/bin/env bash
# Runs the whole pipeline in order. From graph_schema_v1/:   bash 03_code/run_all.sh
set -e
python 03_code/01_download_reference_documents.py || echo "Some reference documents did not download; the graph is built without their text."
python 03_code/02_build_graph_from_claim_notes.py --notes data/claim_notes/GB_15claims_Pack_Notes.csv --out 05_outputs
python 03_code/00_make_schema_tables_and_diagram.py
python 03_code/03_run_schema_test_questions.py
echo "Done. Start with 05_outputs/01_graph_build_report.md"
