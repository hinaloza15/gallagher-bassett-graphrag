from __future__ import annotations
from pathlib import Path
import hashlib
import json
import re
from collections import defaultdict
import pandas as pd

NOTES_FILE = Path("data/processed/notes_normalized.csv")
CHUNKS_FILE = Path("data/graph/chunks.csv")
OUT_DIR = Path("data/graph")

SCHEMA_VERSION = "1.0.0"

BODY_PARTS = [
    "low back", "lower back", "back", "neck", "shoulder", "arm", "forearm",
    "wrist", "hand", "hip", "knee", "ankle", "foot", "ear", "elbow"
]
TREATMENTS = [
    "physical therapy", "home exercise program", "ice", "splint",
    "occupational therapy", "therapy", "massage"
]
MEDICATIONS = [
    "tylenol", "ibuprofen", "naproxen", "flexeril", "nsaid", "nsaids", "acetaminophen"
]

EVENT_RULES = [
    ("injury_occurred", "intake", [r"\bdoi\b", r"date of injury", r"injur(?:y|ed).*work"]),
    ("injury_reported_to_employer", "intake", [r"reported .* employer", r"reported .* supervisor"]),
    ("employer_reported_to_carrier", "intake", [r"employer reported .* carrier", r"\bc-2f\b"]),
    ("first_report_received", "intake", [r"first report", r"claim assigned"]),
    ("prior_claims_check", "intake", [r"prior claims", r"prior claim search"]),
    ("claimant_statement_taken", "investigation", [r"claimant statement", r"statement from .*claimant"]),
    ("supervisor_statement_taken", "investigation", [r"supervisor statement", r"statement .* supervisor"]),
    ("compensability_decision", "investigation", [r"compensab", r"accept(?:ed|ing).*work", r"disput(?:e|ing)", r"\bc-7\b"]),
    ("medical_visit", "medical", [r"office note", r"treating provider", r"\bdr\.?\s", r"physician"]),
    ("therapy_visit", "medical", [r"\bpt visit\b", r"physical therapy", r"therapy visit"]),
    ("imaging_ordered", "medical", [r"\bmri\b.*order", r"\bx-?ray\b.*order", r"imaging.*order"]),
    ("imaging_result", "medical", [r"\bmri\b.*result", r"\bx-?ray\b.*result", r"imaging.*result"]),
    ("nurse_case_review", "medical", [r"nurse case", r"\bncm\b", r"barrier to .*return to work"]),
    ("appointment_scheduled", "medical", [r"next appt", r"next appointment", r"follow[- ]?up.*\d"]),
    ("missed_appointment", "medical", [r"no[- ]?show", r"missed appointment"]),
    ("permanency_evaluation", "medical", [r"\bmmi\b", r"permanency"]),
    ("authorization_request", "authorization_and_billing", [r"request(?:ing|ed).*auth", r"request(?:ing|ed).*(?:pt|mri|therapy)", r"\bmg-2\b"]),
    ("authorization_decision", "authorization_and_billing", [r"approved .*visit", r"authorization .*approved", r"auth(?:orization)?\s*#"]),
    ("bill_submitted", "authorization_and_billing", [r"bill(?:ing)? .*sent", r"submitted .*bill"]),
    ("bill_review", "authorization_and_billing", [r"bill review", r"denied .*no auth", r"pended .*records"]),
    ("pharmacy_review", "authorization_and_billing", [r"pharmacy", r"rx check", r"prescription"]),
    ("mileage_reimbursement_request", "authorization_and_billing", [r"mileage", r"\bc-257\b"]),
    ("wage_information", "money", [r"weekly wage", r"earned .* a week", r"payroll"]),
    ("benefit_payment", "money", [r"paid \$", r"weekly rate", r"paid through", r"paid thru"]),
    ("reserve_review", "money", [r"reserve"]),
    ("paid_to_date_statement", "money", [r"paid to date"]),
    ("work_status_update", "return_to_work", [r"work status", r"modified duty", r"light duty", r"off work", r"restriction"]),
    ("return_to_full_duty", "return_to_work", [r"full duty", r"regular duty"]),
    ("light_duty_offer", "return_to_work", [r"offer .*light duty", r"can offer .*modified duty"]),
    ("attendance_report", "return_to_work", [r"missed \d+ days", r"attendance", r"called out"]),
    ("ime_scheduled", "legal", [r"\bime\b.*sched", r"independent medical examination.*sched"]),
    ("ime_report", "legal", [r"\bime report\b", r"independent medical examination.*report"]),
    ("hearing_scheduled", "legal", [r"hearing .*sched", r"next hearing", r"conciliation .*sched"]),
    ("hearing_held", "legal", [r"hearing held", r"hearing .*adjourn"]),
    ("board_determination", "legal", [r"board determination", r"admin determination"]),
    ("attorney_request", "legal", [r"attorney.*request", r"counsel.*request", r"asking for a hearing"]),
    ("settlement_discussion", "legal", [r"section 32", r"settlement"]),
    ("contact_attempt", "communication", [r"left voicemail", r"\blvm\b", r"vm full", r"no answer", r"tried .* again"]),
    ("worker_message", "communication", [r"portal msg", r"claimant message", r"worker message"]),
    ("supervisor_direction", "communication", [r"supervisor.*need", r"supervisor direction"]),
    ("status_report_sent", "communication", [r"status report"]),
    ("file_review", "communication", [r"file review", r"diary review", r"diary check"]),
    ("form_activity", "communication", [r"\bc-3\b", r"\bc-2f\b", r"\bc-4\.2\b", r"\bc-7\b", r"\bc-257\b", r"\bmg-2\b", r"\brfa-1\b"]),
    ("pending_item", "communication", [r"still waiting", r"pending"]),
    ("claim_closed", "closure", [r"closing note", r"claim closed", r"close file"]),
    ("reopen_request", "closure", [r"reopen", r"flare[- ]?up"]),
    ("contact", "communication", [r"spoke with", r"called claimant", r"email from", r"received email"]),
]

def clean(value):
    if pd.isna(value):
        return ""
    return str(value).strip()

def slug(value):
    value = clean(value).lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value or "unknown"

def make_id(prefix, *parts):
    raw = "|".join(clean(x) for x in parts)
    return f"{prefix}-{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:10]}"

def add_node(nodes, label, key_name, key_value, props):
    if not key_value:
        return
    record = {"label": label, "key_name": key_name, "key_value": str(key_value)}
    record.update({k: v for k, v in props.items() if clean(v) != ""})
    nodes[(label, str(key_value))] = record

def add_rel(rels, start_label, start_key, start_value, rel_type,
            end_label, end_key, end_value, source_type, source_id,
            method, scope_claim_id, props=None):
    if not start_value or not end_value:
        return

    p = {
        "source_type": source_type,
        "source_id": source_id,
        "method": method,
        "review_status": "approved" if method in {"structured_field", "header_field", "computed"} else "unreviewed",
        "schema_version": SCHEMA_VERSION,
        "scope_claim_id": scope_claim_id,
    }
    if props:
        p.update(props)

    rels.append({
        "start_label": start_label,
        "start_key": start_key,
        "start_value": str(start_value),
        "type": rel_type,
        "end_label": end_label,
        "end_key": end_key,
        "end_value": str(end_value),
        "properties_json": json.dumps(p, ensure_ascii=False),
    })

def author_target(row):
    role = clean(row.get("author_role")).lower()
    name = clean(row.get("author"))
    claim_id = clean(row.get("claim_id"))

    if not name:
        return None

    if any(x in role for x in ["doctor", "physician", "provider", "therapist", "pt", "clinician", "ime"]):
        key = make_id("CLIN", claim_id, role, name)
        return "Clinician", "clinician_id", key, {
            "clinician_id": key, "name": name, "clinician_type": role, "aliases": [name]
        }

    if any(x in role for x in ["employer", "hr", "payroll"]):
        key = make_id("ERC", claim_id, role, name)
        return "EmployerContact", "contact_id", key, {
            "contact_id": key, "name": name, "contact_role": role, "aliases": [name]
        }

    key = make_id("STAFF", claim_id, role, name)
    return "ClaimsStaff", "staff_id", key, {
        "staff_id": key, "name": name, "primary_role": role, "aliases": [name]
    }

def extract_restrictions(text):
    candidates = []
    for pattern in [
        r"(no lifting[^.;\n]{0,100})",
        r"(no repeated bending[^.;\n]{0,100})",
        r"(no overhead[^.;\n]{0,100})",
        r"(restrictions?:[^.\n]{0,180})",
    ]:
        m = re.search(pattern, text, flags=re.I)
        if m:
            candidates.append(m.group(1).strip())
    return " | ".join(dict.fromkeys(candidates))

def extract_pain_score(text):
    for p in [r"pain(?: score)?\s*[:=-]?\s*(\d{1,2})\s*/\s*10", r"pain\s+(\d{1,2})\s*/\s*10"]:
        m = re.search(p, text, flags=re.I)
        if m:
            v = int(m.group(1))
            if 0 <= v <= 10:
                return v
    return None

def extract_amount(text):
    m = re.search(r"\$[\s]*([\d,]+(?:\.\d{1,2})?)", text)
    return float(m.group(1).replace(",", "")) if m else None

def extract_work_status(text):
    t = text.lower()
    if "full duty" in t or "regular duty" in t:
        return "full_duty"
    if "modified duty" in t:
        return "modified_duty"
    if "light duty" in t:
        return "light_duty"
    if "off work" in t or "out of work" in t:
        return "off_work"
    return ""

def match_events(text):
    t = text.lower()
    matched = []
    for event_type, category, patterns in EVENT_RULES:
        if any(re.search(p, t, flags=re.I) for p in patterns):
            matched.append((event_type, category))
    return matched

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    notes = pd.read_csv(NOTES_FILE)
    chunks = pd.read_csv(CHUNKS_FILE)

    nodes = {}
    rels = []
    note_order = defaultdict(list)

    for claim_id, group in notes.groupby(notes["claim_id"].astype(str)):
        first = group.iloc[0]
        claimant = clean(first.get("claimant"))
        employer = clean(first.get("employer"))
        carrier = clean(first.get("carrier"))
        county = clean(first.get("county"))
        status = clean(first.get("claim_status"))

        add_node(nodes, "Claim", "claim_id", claim_id, {
            "claim_id": claim_id,
            "claim_status_source": status,
            "claimant_name": claimant,
            "first_note_date": clean(group["note_date"].min()),
            "last_note_date": clean(group["note_date"].max()),
            "note_count": int(len(group)),
        })

        claimant_id = f"CLMT-{claim_id}"
        add_node(nodes, "Claimant", "claimant_id", claimant_id, {
            "claimant_id": claimant_id,
            "name": claimant,
            "aliases": [claimant] if claimant else [],
        })
        add_rel(rels, "Claim", "claim_id", claim_id, "FILED_BY",
                "Claimant", "claimant_id", claimant_id,
                "claim_record", claim_id, "structured_field", claim_id)

        if employer:
            employer_id = f"EMP-{slug(employer)}"
            add_node(nodes, "Employer", "employer_id", employer_id, {
                "employer_id": employer_id, "name": employer, "aliases": [employer]
            })
            add_rel(rels, "Claim", "claim_id", claim_id, "HAS_EMPLOYER",
                    "Employer", "employer_id", employer_id,
                    "claim_record", claim_id, "structured_field", claim_id)

        if carrier:
            carrier_id = f"CAR-{slug(carrier)}"
            add_node(nodes, "Carrier", "carrier_id", carrier_id, {
                "carrier_id": carrier_id, "name": carrier, "aliases": [carrier]
            })
            add_rel(rels, "Claim", "claim_id", claim_id, "INSURED_BY",
                    "Carrier", "carrier_id", carrier_id,
                    "claim_record", claim_id, "structured_field", claim_id)

        if county:
            add_node(nodes, "County", "county_name", county, {"county_name": county})
            add_rel(rels, "Claim", "claim_id", claim_id, "OCCURRED_IN_COUNTY",
                    "County", "county_name", county,
                    "claim_record", claim_id, "structured_field", claim_id)

    for _, row in notes.iterrows():
        claim_id = clean(row["claim_id"])
        note_id = clean(row["note_id"])
        raw_text = clean(row.get("raw_text"))
        normalized = clean(row.get("normalized_text")) or raw_text

        add_node(nodes, "Note", "note_id", note_id, {
            "note_id": note_id,
            "claim_id": claim_id,
            "note_date": clean(row.get("note_date")),
            "note_type": clean(row.get("event_type")),
            "author_name": clean(row.get("author")),
            "author_role": clean(row.get("author_role")),
            "text": raw_text,
            "word_count": len(raw_text.split()),
            "has_copied_history": bool(re.search(r"\b(history|prior note|copied)\b", raw_text, flags=re.I)),
            "has_pasted_email": bool(re.search(r"\b(from:|subject:|sent:)\b", raw_text, flags=re.I)),
            "looks_truncated": len(raw_text) > 0 and not re.search(r"[.!?\"']\s*$", raw_text),
        })

        add_rel(rels, "Claim", "claim_id", claim_id, "HAS_NOTE",
                "Note", "note_id", note_id,
                "note_header", note_id, "header_field", claim_id)

        note_order[claim_id].append((
            clean(row.get("note_date")),
            int(row.get("note_sequence", 0)) if clean(row.get("note_sequence")) else 0,
            note_id
        ))

        target = author_target(row)
        if target:
            label, key_name, key_value, props = target
            add_node(nodes, label, key_name, key_value, props)
            add_rel(rels, "Note", "note_id", note_id, "WRITTEN_BY",
                    label, key_name, key_value,
                    "note_header", note_id, "header_field", claim_id)

            if label == "ClaimsStaff":
                rel_type = "HANDLED_BY"
            elif label == "Clinician":
                rel_type = "SEEN_BY"
            else:
                rel_type = "HAS_EMPLOYER_CONTACT"

            add_rel(rels, "Claim", "claim_id", claim_id, rel_type,
                    label, key_name, key_value,
                    "note_header", note_id, "header_field", claim_id)

        for part in BODY_PARTS:
            if re.search(rf"\b{re.escape(part)}\b", normalized, flags=re.I):
                bp_id = f"BP-specific-{slug(part)}"
                add_node(nodes, "BodyPart", "body_part_id", bp_id, {
                    "body_part_id": bp_id, "name": part, "granularity": "specific"
                })

        for treatment in TREATMENTS:
            if re.search(rf"\b{re.escape(treatment)}\b", normalized, flags=re.I):
                tid = slug(treatment)
                add_node(nodes, "Treatment", "treatment_id", tid, {
                    "treatment_id": tid, "name": treatment
                })

        for med in MEDICATIONS:
            if re.search(rf"\b{re.escape(med)}\b", normalized, flags=re.I):
                mid = slug(med)
                add_node(nodes, "Medication", "medication_id", mid, {
                    "medication_id": mid, "name": med
                })

        events = match_events(normalized)
        if not events:
            events = [("file_review", "communication")]

        for idx, (event_type, event_category) in enumerate(events, start=1):
            event_id = make_id("EV", claim_id, note_id, event_type, idx)

            add_node(nodes, "ClaimEvent", "event_id", event_id, {
                "event_id": event_id,
                "claim_id": claim_id,
                "event_type": event_type,
                "event_category": event_category,
                "event_date": clean(row.get("note_date")),
                "date_basis": "note_date",
                "summary": normalized[:500],
                "attributes_json": "{}",
                "evidence_count": 1,
                "primary_evidence_count": 1,
                "support": "primary",
                "work_status": extract_work_status(normalized),
                "restrictions": extract_restrictions(normalized),
                "pain_score": extract_pain_score(normalized),
                "amount": extract_amount(normalized),
                "has_conflicting_values": False,
            })

            add_rel(rels, "Claim", "claim_id", claim_id, "HAS_EVENT",
                    "ClaimEvent", "event_id", event_id,
                    "note_text", note_id, "rule_v1", claim_id)

            add_rel(rels, "ClaimEvent", "event_id", event_id, "EVIDENCED_BY",
                    "Note", "note_id", note_id,
                    "note_text", note_id, "rule_v1", claim_id,
                    {"evidence_kind": "primary"})

            for treatment in TREATMENTS:
                if re.search(rf"\b{re.escape(treatment)}\b", normalized, flags=re.I):
                    tid = slug(treatment)
                    add_rel(rels, "ClaimEvent", "event_id", event_id, "INCLUDES_TREATMENT",
                            "Treatment", "treatment_id", tid,
                            "note_text", note_id, "alias_match", claim_id)

            for med in MEDICATIONS:
                if re.search(rf"\b{re.escape(med)}\b", normalized, flags=re.I):
                    mid = slug(med)
                    add_rel(rels, "ClaimEvent", "event_id", event_id, "RECORDS_MEDICATION",
                            "Medication", "medication_id", mid,
                            "note_text", note_id, "alias_match", claim_id)

    for _, row in chunks.iterrows():
        chunk_id = clean(row["chunk_id"])
        note_id = clean(row["note_id"])
        claim_id = clean(row["claim_id"])

        add_node(nodes, "Chunk", "chunk_id", chunk_id, {
            "chunk_id": chunk_id,
            "parent_id": clean(row["parent_id"]),
            "parent_kind": clean(row["parent_kind"]),
            "position": int(row["position"]),
            "text": clean(row["text"]),
            "char_start": int(row["char_start"]),
            "char_end": int(row["char_end"]),
            "word_count": int(row["word_count"]),
            "claim_id": claim_id,
            "note_id": note_id,
        })

        add_rel(rels, "Note", "note_id", note_id, "HAS_CHUNK",
                "Chunk", "chunk_id", chunk_id,
                "derived", chunk_id, "computed", claim_id)

    for claim_id, items in note_order.items():
        items = sorted(items, key=lambda x: (x[0], x[1]))
        for a, b in zip(items, items[1:]):
            add_rel(rels, "Note", "note_id", a[2], "NEXT_NOTE",
                    "Note", "note_id", b[2],
                    "derived", a[2], "computed", claim_id)

    for note_id, g in chunks.groupby("note_id"):
        g = g.sort_values("position")
        ids = g["chunk_id"].astype(str).tolist()
        claim_id = str(g.iloc[0]["claim_id"])
        for a, b in zip(ids, ids[1:]):
            add_rel(rels, "Chunk", "chunk_id", a, "NEXT_CHUNK",
                    "Chunk", "chunk_id", b,
                    "derived", a, "computed", claim_id)

    temp = notes.copy()
    temp["_norm_dup"] = temp["normalized_text"].fillna("").str.lower().str.replace(r"\s+", " ", regex=True).str.strip()
    for claim_id, group in temp.groupby(temp["claim_id"].astype(str)):
        for _, dup_group in group[group["_norm_dup"] != ""].groupby("_norm_dup"):
            if len(dup_group) > 1:
                dup_group = dup_group.sort_values(["note_date", "note_sequence"])
                ids = dup_group["note_id"].astype(str).tolist()
                for earlier, later in zip(ids, ids[1:]):
                    add_rel(rels, "Note", "note_id", later, "DUPLICATES",
                            "Note", "note_id", earlier,
                            "derived", later, "computed", claim_id)

    nodes_df = pd.DataFrame(nodes.values())
    rels_df = pd.DataFrame(rels)

    nodes_df.to_csv(OUT_DIR / "nodes.csv", index=False)
    rels_df.to_csv(OUT_DIR / "relationships.csv", index=False)

    print("\nNode counts:")
    print(nodes_df["label"].value_counts().sort_index())
    print("\nRelationship counts:")
    print(rels_df["type"].value_counts().sort_index())

if __name__ == "__main__":
    main()
