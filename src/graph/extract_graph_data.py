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
    "tylenol", "ibuprofen", "naproxen", "flexeril", "nsaid", "nsaids",
    "acetaminophen"
]

# These events are intentionally conservative. The goal is to create an event when
# the note records something that happened, not merely because the note mentions
# the topic in copied history or a status summary.
EVENT_RULES = [
    ("injury_reported_to_employer", "intake", [
        r"\breported\b.{0,50}\b(?:employer|supervisor)\b",
        r"\b(?:employer|supervisor)\b.{0,50}\breported\b",
    ]),
    ("employer_reported_to_carrier", "intake", [
        r"\bemployer\b.{0,50}\breported\b.{0,50}\bcarrier\b",
        r"\bc-2f\b",
    ]),
    ("first_report_received", "intake", [
        r"\bfirst report\b.{0,40}\b(?:received|reviewed)\b",
        r"\bclaim assigned\b",
    ]),
    ("prior_claims_check", "intake", [
        r"\bprior claims?\b",
        r"\bprior claim search\b",
    ]),
    ("claimant_statement_taken", "investigation", [
        r"\bclaimant statement\b",
        r"\bstatement from\b.{0,40}\bclaimant\b",
    ]),
    ("supervisor_statement_taken", "investigation", [
        r"\bsupervisor statement\b",
        r"\bstatement\b.{0,40}\bsupervisor\b",
    ]),
    ("compensability_decision", "investigation", [
        r"\bcompensab(?:ility|le)\b.{0,80}\b(?:accepted|denied|disputed)\b",
        r"\b(?:accepted|denied|disputed)\b.{0,80}\bcompensab",
        r"\bc-7\b",
    ]),
    ("imaging_ordered", "medical", [
        r"\b(?:mri|x-?ray|imaging)\b.{0,50}\b(?:ordered|requested)\b",
        r"\b(?:ordered|requested)\b.{0,50}\b(?:mri|x-?ray|imaging)\b",
    ]),
    ("imaging_result", "medical", [
        r"\b(?:mri|x-?ray|imaging)\b.{0,50}\b(?:result|showed|revealed|demonstrated)\b",
        r"\b(?:result|showed|revealed|demonstrated)\b.{0,50}\b(?:mri|x-?ray|imaging)\b",
    ]),
    ("nurse_case_review", "medical", [
        r"\bnurse case\b",
        r"\bncm\b",
        r"\bbarrier to\b.{0,40}\breturn to work\b",
    ]),
    ("appointment_scheduled", "medical", [
        r"\b(?:next appt|next appointment|follow[- ]?up)\b.{0,80}\b(?:\d{1,2}[/-]\d{1,2}|\d{1,2}/\d{1,2}/\d{2,4}|january|february|march|april|may|june|july|august|september|october|november|december)\b",
        r"\b(?:scheduled|set)\b.{0,40}\b(?:appointment|follow[- ]?up)\b",
    ]),
    ("missed_appointment", "medical", [
        r"\bno[- ]?show\b",
        r"\bmissed appointment\b",
    ]),
    ("permanency_evaluation", "medical", [
        r"\bmmi\b",
        r"\bpermanency\b",
    ]),
    ("authorization_request", "authorization_and_billing", [
        r"\brequest(?:ing|ed)?\b.{0,60}\bauth(?:orization)?\b",
        r"\brequest(?:ing|ed)?\b.{0,60}\b(?:pt|mri|therapy)\b",
        r"\bmg-2\b",
    ]),
    ("authorization_decision", "authorization_and_billing", [
        r"\bauthorization\b.{0,50}\b(?:approved|denied)\b",
        r"\b(?:approved|denied)\b.{0,50}\bauthorization\b",
        r"\bauth(?:orization)?\s*#",
    ]),
    ("bill_submitted", "authorization_and_billing", [
        r"\b(?:bill|billing)\b.{0,50}\b(?:sent|submitted)\b",
        r"\bsubmitted\b.{0,50}\bbill\b",
    ]),
    ("bill_review", "authorization_and_billing", [
        r"\bbill review\b",
        r"\bdenied\b.{0,50}\bno auth\b",
        r"\bpended\b.{0,50}\brecords\b",
    ]),
    ("pharmacy_review", "authorization_and_billing", [
        r"\bpharmacy review\b",
        r"\brx check\b",
        r"\bprescription\b.{0,50}\b(?:reviewed|approved|denied|filled)\b",
    ]),
    ("mileage_reimbursement_request", "authorization_and_billing", [
        r"\bmileage\b",
        r"\bc-257\b",
    ]),
    ("wage_information", "money", [
        r"\bweekly wage\b",
        r"\bearned\b.{0,40}\ba week\b",
        r"\bpayroll\b",
    ]),
    ("benefit_payment", "money", [
        r"\bpaid\s*\$",
        r"\bweekly rate\b",
        r"\bpaid through\b",
        r"\bpaid thru\b",
    ]),
    ("reserve_review", "money", [
        r"\breserve review\b",
        r"\breserves?\b.{0,50}\b(?:reviewed|increased|decreased|set)\b",
    ]),
    ("paid_to_date_statement", "money", [
        r"\bpaid to date\b",
    ]),
    ("light_duty_offer", "return_to_work", [
        r"\b(?:offer|offered|can offer)\b.{0,50}\b(?:light|modified) duty\b",
    ]),
    ("attendance_report", "return_to_work", [
        r"\bmissed\s+\d+\s+days\b",
        r"\battendance report\b",
        r"\bcalled out\b",
    ]),
    ("ime_scheduled", "legal", [
        r"\bime\b.{0,50}\bsched(?:uled|ule)?\b",
        r"\bindependent medical examination\b.{0,50}\bsched(?:uled|ule)?\b",
    ]),
    ("ime_report", "legal", [
        r"\bime report\b",
        r"\bindependent medical examination\b.{0,50}\breport\b",
    ]),
    ("hearing_scheduled", "legal", [
        r"\bhearing\b.{0,50}\bsched(?:uled|ule)?\b",
        r"\bnext hearing\b",
        r"\bconciliation\b.{0,50}\bsched(?:uled|ule)?\b",
    ]),
    ("hearing_held", "legal", [
        r"\bhearing held\b",
        r"\bhearing\b.{0,50}\badjourn(?:ed|ment)?\b",
    ]),
    ("board_determination", "legal", [
        r"\bboard determination\b",
        r"\badmin(?:istrative)? determination\b",
    ]),
    ("attorney_request", "legal", [
        r"\battorney\b.{0,50}\brequest",
        r"\bcounsel\b.{0,50}\brequest",
        r"\basking for a hearing\b",
    ]),
    ("settlement_discussion", "legal", [
        r"\bsection 32\b",
        r"\bsettlement\b",
    ]),
    ("contact_attempt", "communication", [
        r"\bleft voicemail\b",
        r"\blvm\b",
        r"\bvm full\b",
        r"\bno answer\b",
        r"\btried\b.{0,40}\bagain\b",
    ]),
    ("worker_message", "communication", [
        r"\bportal msg\b",
        r"\bclaimant message\b",
        r"\bworker message\b",
    ]),
    ("supervisor_direction", "communication", [
        r"\bsupervisor\b.{0,60}\b(?:directed|asked|requested|need)\b",
        r"\bsupervisor direction\b",
    ]),
    ("status_report_sent", "communication", [
        r"\bstatus report\b",
    ]),
    ("file_review", "communication", [
        r"\bfile review\b",
        r"\bdiary review\b",
        r"\bdiary check\b",
    ]),
    ("form_activity", "communication", [
        r"\bc-3\b", r"\bc-2f\b", r"\bc-4\.2\b", r"\bc-7\b",
        r"\bc-257\b", r"\bmg-2\b", r"\brfa-1\b",
    ]),
    ("pending_item", "communication", [
        r"\bstill waiting\b",
        r"\bpending\b.{0,60}\b(?:records|authorization|report|response|appointment|hearing|decision)\b",
    ]),
    ("claim_closed", "closure", [
        r"\bclosing note\b",
        r"\bclaim closed\b",
        r"\bclose file\b",
    ]),
    ("reopen_request", "closure", [
        r"\breopen(?:ed|ing| request)?\b",
        r"\bflare[- ]?up\b.{0,50}\breopen\b",
    ]),
    ("contact", "communication", [
        r"\bspoke with\b",
        r"\bcalled claimant\b",
        r"\bemail from\b",
        r"\breceived email\b",
    ]),
]

# Events where one occurrence per claim is normally enough for this prototype.
# This prevents copied history from repeatedly generating the same foundational event.
SINGLETON_EVENT_TYPES = {
    "injury_occurred",
    "first_report_received",
}

# Restrict concept relationships to events where the concept is actually relevant.
TREATMENT_EVENT_TYPES = {
    "medical_visit",
    "therapy_visit",
    "authorization_request",
    "authorization_decision",
    "nurse_case_review",
    "imaging_ordered",
    "imaging_result",
}

MEDICATION_EVENT_TYPES = {
    "medical_visit",
    "pharmacy_review",
    "authorization_request",
    "authorization_decision",
}

CORRECTION_CUES = [
    r"\bcorrection\b",
    r"\bcorrected\b",
    r"\bpreviously reported\b.{0,80}\b(?:incorrect|wrong)\b",
    r"\bshould read\b",
    r"\bamended\b",
    r"\bclarification\b",
    r"\bnot\b.{0,40}\bbut\b",
]

CORRECTION_TOPICS = {
    "date_of_injury": [
        r"\bdoi\b",
        r"\bdate of injury\b",
        r"\bincident date\b",
        r"\baccident date\b",
    ],
    "work_status": [
        r"\bwork status\b",
        r"\bmodified duty\b",
        r"\blight duty\b",
        r"\bfull duty\b",
        r"\bregular duty\b",
        r"\brestriction",
    ],
    "claimant_name": [
        r"\bclaimant name\b",
        r"\bworker name\b",
    ],
    "employer": [
        r"\bemployer\b",
    ],
    "injury_detail": [
        r"\bbody part\b",
        r"\binjury nature\b",
        r"\bcause of injury\b",
    ],
}


def clean(value):
    if pd.isna(value):
        return ""
    return str(value).strip()


def normalize_claim_id(value):
    text = clean(value)
    if text.endswith(".0"):
        text = text[:-2]
    return text


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


def add_rel(
    rels,
    start_label,
    start_key,
    start_value,
    rel_type,
    end_label,
    end_key,
    end_value,
    source_type,
    source_id,
    method,
    scope_claim_id,
    props=None,
):
    if not start_value or not end_value:
        return

    p = {
        "source_type": source_type,
        "source_id": source_id,
        "method": method,
        "review_status": (
            "approved"
            if method in {"structured_field", "header_field", "computed"}
            else "unreviewed"
        ),
        "schema_version": SCHEMA_VERSION,
        "scope_claim_id": scope_claim_id,
    }
    if props:
        p.update(props)

    rels.append(
        {
            "start_label": start_label,
            "start_key": start_key,
            "start_value": str(start_value),
            "type": rel_type,
            "end_label": end_label,
            "end_key": end_key,
            "end_value": str(end_value),
            "properties_json": json.dumps(p, ensure_ascii=False),
        }
    )


def author_target(row):
    role = clean(row.get("author_role")).lower()
    name = clean(row.get("author"))
    claim_id = normalize_claim_id(row.get("claim_id"))

    if not name:
        return None

    if any(
        x in role
        for x in [
            "doctor",
            "physician",
            "provider",
            "therapist",
            "pt",
            "clinician",
            "ime",
        ]
    ):
        key = make_id("CLIN", claim_id, role, name)
        return "Clinician", "clinician_id", key, {
            "clinician_id": key,
            "name": name,
            "clinician_type": role,
            "aliases": [name],
        }

    if any(x in role for x in ["employer", "hr", "payroll"]):
        key = make_id("ERC", claim_id, role, name)
        return "EmployerContact", "contact_id", key, {
            "contact_id": key,
            "name": name,
            "contact_role": role,
            "aliases": [name],
        }

    key = make_id("STAFF", claim_id, role, name)
    return "ClaimsStaff", "staff_id", key, {
        "staff_id": key,
        "name": name,
        "primary_role": role,
        "aliases": [name],
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
    for pattern in [
        r"pain(?: score)?\s*[:=-]?\s*(\d{1,2})\s*/\s*10",
        r"pain\s+(\d{1,2})\s*/\s*10",
    ]:
        m = re.search(pattern, text, flags=re.I)
        if m:
            value = int(m.group(1))
            if 0 <= value <= 10:
                return value
    return None


def extract_amount(text):
    m = re.search(r"\$[\s]*([\d,]+(?:\.\d{1,2})?)", text)
    return float(m.group(1).replace(",", "")) if m else None


def extract_work_status(text):
    t = text.lower()

    # Do not treat future/expected full-duty language as current full duty.
    if re.search(
        r"\b(?:released|returned|working|resumed)\b.{0,35}\b(?:full|regular) duty\b",
        t,
    ):
        return "full_duty"
    if re.search(r"\bworking\b.{0,20}\bmodified duty\b", t) or "remains on modified duty" in t:
        return "modified_duty"
    if re.search(r"\bworking\b.{0,20}\blight duty\b", t) or "remains on light duty" in t:
        return "light_duty"
    if "off work" in t or "out of work" in t:
        return "off_work"
    return ""


def has_correction_cue(text):
    return any(re.search(pattern, text, flags=re.I) for pattern in CORRECTION_CUES)


def correction_topics(text):
    topics = []
    for topic, patterns in CORRECTION_TOPICS.items():
        if any(re.search(pattern, text, flags=re.I) for pattern in patterns):
            topics.append(topic)
    return topics


def is_injury_occurrence(text):
    t = text.lower()

    occurrence_patterns = [
        r"\b(?:injury|accident|incident)\b.{0,70}\b(?:occurred|happened|took place)\b",

        r"\b(?:injured|hurt)\b.{0,80}\b(?:while|when|at work|on the job)\b",

        r"\bdate of injury\s*(?:is|was|:|-)",

        r"\bdoi\s*(?:is|was|:|-)\s*\w+",

        r"\b(?:was|were)\b.{0,50}\b(?:struck|hit|fell|slipped|tripped|injured)\b",

        r"\b(?:while|when)\b.{0,100}\b(?:fell|slipped|tripped|was struck|was hit|injured)\b",
    ]

    return any(
        re.search(pattern, t, flags=re.I)
        for pattern in occurrence_patterns
    )


def is_medical_visit(text):
    t = text.lower()

    # Require visit/exam language instead of matching every mention of "Dr.".
    visit_patterns = [
        r"\b(?:seen|evaluated|examined|treated) by\b.{0,60}\b(?:dr\.?|doctor|physician|provider)\b",
        r"\b(?:office|medical|provider|doctor|physician) visit\b",
        r"\bfollow[- ]?up visit\b",
        r"\b(?:saw|visited)\b.{0,40}\b(?:dr\.?|doctor|physician|provider)\b",
    ]

    future_only = bool(
        re.search(
            r"\b(?:next|scheduled|upcoming|future)\b.{0,50}\b(?:appointment|visit|appt)\b",
            t,
        )
    )

    return any(re.search(pattern, t, flags=re.I) for pattern in visit_patterns) and not future_only


def is_therapy_visit(text):
    t = text.lower()

    visit_patterns = [
        r"\b(?:pt|physical therapy|occupational therapy|therapy) visit\b",
        r"\b(?:attended|completed|went to|seen for)\b.{0,40}\b(?:pt|physical therapy|occupational therapy|therapy)\b",
        r"\b(?:pt|physical therapy|occupational therapy|therapy) session\b",
    ]

    request_only = bool(
        re.search(
            r"\b(?:request|requested|requesting|authorize|authorization|scheduled|plan|recommended)\b.{0,60}\b(?:pt|physical therapy|occupational therapy|therapy)\b",
            t,
        )
    )

    return any(re.search(pattern, t, flags=re.I) for pattern in visit_patterns) and not request_only


def is_work_status_update(text):
    t = text.lower()

    status_patterns = [
        r"\bwork status\s*[:=-]",
        r"\b(?:working|remains on|placed on|released to)\b.{0,35}\b(?:modified|light|full|regular) duty\b",
        r"\b(?:off work|out of work)\b",
        r"\brestrictions?\s*(?:are|include|per|:)\b",
        r"\bno lifting\b",
        r"\bno repeated bending\b",
        r"\bno overhead\b",
    ]

    return any(re.search(pattern, t, flags=re.I) for pattern in status_patterns)


def is_return_to_full_duty(text):
    t = text.lower()

    actual_patterns = [
        r"\breleased to\b.{0,30}\b(?:full|regular) duty\b",
        r"\breturned to\b.{0,30}\b(?:full|regular) duty\b",
        r"\breturn to\b.{0,30}\b(?:full|regular) duty\b.{0,30}\beffective\b",
        r"\b(?:full|regular) duty\b.{0,30}\brelease(?:d)?\b",
        r"\b(?:full|regular) duty\b.{0,30}\beffective\b",
        r"\bcleared for\b.{0,30}\b(?:full|regular) duty\b",
    ]

    future_patterns = [
        r"\b(?:expected|anticipated|planned|possible|target|projected)\b.{0,60}\b(?:full|regular) duty\b",
        r"\b(?:full|regular) duty\b.{0,60}\b(?:expected|anticipated|planned|possible|target|projected)\b",
        r"\bfull duty release expected\b",
        r"\bmay return to\b.{0,30}\b(?:full|regular) duty\b",
    ]

    if any(re.search(p, t, flags=re.I) for p in future_patterns):
        return False

    return any(
        re.search(p, t, flags=re.I)
        for p in actual_patterns
    )


def match_events(text):
    matched = []

    # High-risk event types use stricter semantic guards.
    if is_injury_occurrence(text):
        matched.append(("injury_occurred", "intake"))

    if is_medical_visit(text):
        matched.append(("medical_visit", "medical"))

    if is_therapy_visit(text):
        matched.append(("therapy_visit", "medical"))

    if is_work_status_update(text):
        matched.append(("work_status_update", "return_to_work"))

    if is_return_to_full_duty(text):
        matched.append(("return_to_full_duty", "return_to_work"))

    # Remaining lower-risk event rules.
    t = text.lower()
    for event_type, category, patterns in EVENT_RULES:
        if any(re.search(pattern, t, flags=re.I) for pattern in patterns):
            matched.append((event_type, category))

    # Preserve order but remove duplicate event types from the same note.
    deduped = []
    seen = set()
    for event_type, category in matched:
        if event_type not in seen:
            deduped.append((event_type, category))
            seen.add(event_type)

    return deduped


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    notes = pd.read_csv(NOTES_FILE)
    chunks = pd.read_csv(CHUNKS_FILE)

    notes["claim_id"] = notes["claim_id"].apply(normalize_claim_id)
    chunks["claim_id"] = chunks["claim_id"].apply(normalize_claim_id)

    nodes = {}
    rels = []
    note_order = defaultdict(list)
    event_order = defaultdict(list)
    singleton_events_seen = defaultdict(set)

    # ------------------------------------------------------------------
    # Claim-level structured entities
    # ------------------------------------------------------------------
    for claim_id, group in notes.groupby("claim_id"):
        first = group.iloc[0]
        claimant = clean(first.get("claimant"))
        employer = clean(first.get("employer"))
        carrier = clean(first.get("carrier"))
        county = clean(first.get("county"))
        status = clean(first.get("claim_status"))

        add_node(
            nodes,
            "Claim",
            "claim_id",
            claim_id,
            {
                "claim_id": claim_id,
                "claim_status_source": status,
                "claimant_name": claimant,
                "first_note_date": clean(group["note_date"].min()),
                "last_note_date": clean(group["note_date"].max()),
                "note_count": int(len(group)),
            },
        )

        claimant_id = f"CLMT-{claim_id}"
        add_node(
            nodes,
            "Claimant",
            "claimant_id",
            claimant_id,
            {
                "claimant_id": claimant_id,
                "name": claimant,
                "aliases": [claimant] if claimant else [],
            },
        )
        add_rel(
            rels,
            "Claim",
            "claim_id",
            claim_id,
            "FILED_BY",
            "Claimant",
            "claimant_id",
            claimant_id,
            "claim_record",
            claim_id,
            "structured_field",
            claim_id,
        )

        if employer:
            employer_id = f"EMP-{slug(employer)}"
            add_node(
                nodes,
                "Employer",
                "employer_id",
                employer_id,
                {
                    "employer_id": employer_id,
                    "name": employer,
                    "aliases": [employer],
                },
            )
            add_rel(
                rels,
                "Claim",
                "claim_id",
                claim_id,
                "HAS_EMPLOYER",
                "Employer",
                "employer_id",
                employer_id,
                "claim_record",
                claim_id,
                "structured_field",
                claim_id,
            )

        if carrier:
            carrier_id = f"CAR-{slug(carrier)}"
            add_node(
                nodes,
                "Carrier",
                "carrier_id",
                carrier_id,
                {
                    "carrier_id": carrier_id,
                    "name": carrier,
                    "aliases": [carrier],
                },
            )
            add_rel(
                rels,
                "Claim",
                "claim_id",
                claim_id,
                "INSURED_BY",
                "Carrier",
                "carrier_id",
                carrier_id,
                "claim_record",
                claim_id,
                "structured_field",
                claim_id,
            )

        if county:
            add_node(
                nodes,
                "County",
                "county_name",
                county,
                {"county_name": county},
            )
            add_rel(
                rels,
                "Claim",
                "claim_id",
                claim_id,
                "OCCURRED_IN_COUNTY",
                "County",
                "county_name",
                county,
                "claim_record",
                claim_id,
                "structured_field",
                claim_id,
            )

    # ------------------------------------------------------------------
    # Note-level entities and ClaimEvents
    # ------------------------------------------------------------------
    for _, row in notes.iterrows():
        claim_id = normalize_claim_id(row["claim_id"])
        note_id = clean(row["note_id"])
        raw_text = clean(row.get("raw_text"))
        normalized = clean(row.get("normalized_text")) or raw_text

        add_node(
            nodes,
            "Note",
            "note_id",
            note_id,
            {
                "note_id": note_id,
                "claim_id": claim_id,
                "note_date": clean(row.get("note_date")),
                "note_type": clean(row.get("event_type")),
                "author_name": clean(row.get("author")),
                "author_role": clean(row.get("author_role")),
                "text": raw_text,
                "word_count": len(raw_text.split()),
                "has_copied_history": bool(
                    re.search(r"\b(history|prior note|copied)\b", raw_text, flags=re.I)
                ),
                "has_pasted_email": bool(
                    re.search(r"\b(from:|subject:|sent:)\b", raw_text, flags=re.I)
                ),
                "looks_truncated": len(raw_text) > 0
                and not re.search(r"[.!?\"']\s*$", raw_text),
            },
        )

        add_rel(
            rels,
            "Claim",
            "claim_id",
            claim_id,
            "HAS_NOTE",
            "Note",
            "note_id",
            note_id,
            "note_header",
            note_id,
            "header_field",
            claim_id,
        )

        note_order[claim_id].append(
            (
                clean(row.get("note_date")),
                int(row.get("note_sequence", 0))
                if clean(row.get("note_sequence"))
                else 0,
                note_id,
            )
        )

        target = author_target(row)
        if target:
            label, key_name, key_value, props = target
            add_node(nodes, label, key_name, key_value, props)
            add_rel(
                rels,
                "Note",
                "note_id",
                note_id,
                "WRITTEN_BY",
                label,
                key_name,
                key_value,
                "note_header",
                note_id,
                "header_field",
                claim_id,
            )

            if label == "ClaimsStaff":
                rel_type = "HANDLED_BY"
            elif label == "Clinician":
                rel_type = "SEEN_BY"
            else:
                rel_type = "HAS_EMPLOYER_CONTACT"

            add_rel(
                rels,
                "Claim",
                "claim_id",
                claim_id,
                rel_type,
                label,
                key_name,
                key_value,
                "note_header",
                note_id,
                "header_field",
                claim_id,
            )

        for part in BODY_PARTS:
            if re.search(rf"\b{re.escape(part)}\b", normalized, flags=re.I):
                bp_id = f"BP-specific-{slug(part)}"
                add_node(
                    nodes,
                    "BodyPart",
                    "body_part_id",
                    bp_id,
                    {
                        "body_part_id": bp_id,
                        "name": part,
                        "granularity": "specific",
                    },
                )

        for treatment in TREATMENTS:
            if re.search(rf"\b{re.escape(treatment)}\b", normalized, flags=re.I):
                treatment_id = slug(treatment)
                add_node(
                    nodes,
                    "Treatment",
                    "treatment_id",
                    treatment_id,
                    {"treatment_id": treatment_id, "name": treatment},
                )

        for medication in MEDICATIONS:
            if re.search(rf"\b{re.escape(medication)}\b", normalized, flags=re.I):
                medication_id = slug(medication)
                add_node(
                    nodes,
                    "Medication",
                    "medication_id",
                    medication_id,
                    {"medication_id": medication_id, "name": medication},
                )

        events = match_events(normalized)

        # Important: unmatched notes are allowed to have zero ClaimEvents.
        # We no longer force every unmatched note into a generic file_review event.
        for idx, (event_type, event_category) in enumerate(events, start=1):
            if (
                event_type in SINGLETON_EVENT_TYPES
                and event_type in singleton_events_seen[claim_id]
            ):
                continue

            if event_type in SINGLETON_EVENT_TYPES:
                singleton_events_seen[claim_id].add(event_type)

            event_id = make_id("EV", claim_id, note_id, event_type, idx)
            event_order[claim_id].append(
                (
                    clean(row.get("note_date")),
                    int(row.get("note_sequence", 0))
                    if clean(row.get("note_sequence"))
                    else 0,
                    idx,
                    event_id,
                )
            )

            add_node(
                nodes,
                "ClaimEvent",
                "event_id",
                event_id,
                {
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
                    "has_conflicting_values": has_correction_cue(normalized),
                },
            )

            add_rel(
                rels,
                "Claim",
                "claim_id",
                claim_id,
                "HAS_EVENT",
                "ClaimEvent",
                "event_id",
                event_id,
                "note_text",
                note_id,
                "rule_v2",
                claim_id,
            )

            add_rel(
                rels,
                "ClaimEvent",
                "event_id",
                event_id,
                "EVIDENCED_BY",
                "Note",
                "note_id",
                note_id,
                "note_text",
                note_id,
                "rule_v2",
                claim_id,
                {"evidence_kind": "primary"},
            )

            if event_type in TREATMENT_EVENT_TYPES:
                for treatment in TREATMENTS:
                    if re.search(
                        rf"\b{re.escape(treatment)}\b", normalized, flags=re.I
                    ):
                        treatment_id = slug(treatment)
                        add_rel(
                            rels,
                            "ClaimEvent",
                            "event_id",
                            event_id,
                            "INCLUDES_TREATMENT",
                            "Treatment",
                            "treatment_id",
                            treatment_id,
                            "note_text",
                            note_id,
                            "alias_match",
                            claim_id,
                        )

            if event_type in MEDICATION_EVENT_TYPES:
                for medication in MEDICATIONS:
                    if re.search(
                        rf"\b{re.escape(medication)}\b", normalized, flags=re.I
                    ):
                        medication_id = slug(medication)
                        add_rel(
                            rels,
                            "ClaimEvent",
                            "event_id",
                            event_id,
                            "RECORDS_MEDICATION",
                            "Medication",
                            "medication_id",
                            medication_id,
                            "note_text",
                            note_id,
                            "alias_match",
                            claim_id,
                        )

    # ------------------------------------------------------------------
    # Chunk nodes
    # ------------------------------------------------------------------
    for _, row in chunks.iterrows():
        chunk_id = clean(row["chunk_id"])
        note_id = clean(row["note_id"])
        claim_id = normalize_claim_id(row["claim_id"])

        add_node(
            nodes,
            "Chunk",
            "chunk_id",
            chunk_id,
            {
                "chunk_id": chunk_id,
                "parent_id": clean(row["parent_id"]),
                "parent_kind": clean(row["parent_kind"]),
                "position": int(row["position"]),
                "text": clean(row["text"]),
                "char_start": int(row["char_start"]),
                "char_end": int(row["char_end"]),
                "word_count": int(row["word_count"]),
                "token_count": int(row["token_count"])
                if "token_count" in row and clean(row.get("token_count"))
                else None,
                "claim_id": claim_id,
                "note_id": note_id,
            },
        )

        add_rel(
            rels,
            "Note",
            "note_id",
            note_id,
            "HAS_CHUNK",
            "Chunk",
            "chunk_id",
            chunk_id,
            "derived",
            chunk_id,
            "computed",
            claim_id,
        )

    # ------------------------------------------------------------------
    # Chronology
    # ------------------------------------------------------------------
    for claim_id, items in note_order.items():
        items = sorted(items, key=lambda x: (x[0], x[1]))
        for earlier, later in zip(items, items[1:]):
            add_rel(
                rels,
                "Note",
                "note_id",
                earlier[2],
                "NEXT_NOTE",
                "Note",
                "note_id",
                later[2],
                "derived",
                earlier[2],
                "computed",
                claim_id,
            )

    for claim_id, items in event_order.items():
        items = sorted(items, key=lambda x: (x[0], x[1], x[2]))
        for earlier, later in zip(items, items[1:]):
            add_rel(
                rels,
                "ClaimEvent",
                "event_id",
                earlier[3],
                "NEXT_EVENT",
                "ClaimEvent",
                "event_id",
                later[3],
                "derived",
                earlier[3],
                "computed",
                claim_id,
            )

    for note_id, group in chunks.groupby("note_id"):
        group = group.sort_values("position")
        ids = group["chunk_id"].astype(str).tolist()
        claim_id = normalize_claim_id(group.iloc[0]["claim_id"])

        for earlier, later in zip(ids, ids[1:]):
            add_rel(
                rels,
                "Chunk",
                "chunk_id",
                earlier,
                "NEXT_CHUNK",
                "Chunk",
                "chunk_id",
                later,
                "derived",
                earlier,
                "computed",
                claim_id,
            )

    # ------------------------------------------------------------------
    # Exact duplicate notes
    # ------------------------------------------------------------------
    temp = notes.copy()
    temp["_norm_dup"] = (
        temp["normalized_text"]
        .fillna("")
        .str.lower()
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )

    for claim_id, group in temp.groupby("claim_id"):
        for _, duplicate_group in group[group["_norm_dup"] != ""].groupby("_norm_dup"):
            if len(duplicate_group) > 1:
                duplicate_group = duplicate_group.sort_values(
                    ["note_date", "note_sequence"]
                )
                ids = duplicate_group["note_id"].astype(str).tolist()

                for earlier, later in zip(ids, ids[1:]):
                    add_rel(
                        rels,
                        "Note",
                        "note_id",
                        later,
                        "DUPLICATES",
                        "Note",
                        "note_id",
                        earlier,
                        "derived",
                        later,
                        "computed",
                        claim_id,
                    )

    # ------------------------------------------------------------------
    # Conservative correction links
    # ------------------------------------------------------------------
    # A CORRECTS edge is created only when the later note explicitly contains
    # correction language AND both notes discuss the same identifiable topic.
    # We deliberately do not create a generic correction edge to the immediately
    # previous note because that can produce false relationships.
    for claim_id, group in notes.groupby("claim_id"):
        ordered = group.copy().sort_values(["note_date", "note_sequence"])
        previous_rows = []

        for _, row in ordered.iterrows():
            note_id = clean(row["note_id"])
            text = clean(row.get("normalized_text")) or clean(row.get("raw_text"))

            if has_correction_cue(text):
                topics = correction_topics(text)

                for topic in topics:
                    topic_patterns = CORRECTION_TOPICS[topic]
                    target_note_id = None

                    for previous in reversed(previous_rows):
                        previous_text = (
                            clean(previous.get("normalized_text"))
                            or clean(previous.get("raw_text"))
                        )

                        if any(
                            re.search(pattern, previous_text, flags=re.I)
                            for pattern in topic_patterns
                        ):
                            target_note_id = clean(previous.get("note_id"))
                            break

                    if target_note_id:
                        add_rel(
                            rels,
                            "Note",
                            "note_id",
                            note_id,
                            "CORRECTS",
                            "Note",
                            "note_id",
                            target_note_id,
                            "note_text",
                            note_id,
                            "rule_v2_correction",
                            claim_id,
                            {"correction_topic": topic},
                        )

            previous_rows.append(row)

    nodes_df = pd.DataFrame(nodes.values())
    rels_df = pd.DataFrame(rels)

    nodes_df.to_csv(OUT_DIR / "nodes.csv", index=False)
    rels_df.to_csv(OUT_DIR / "relationships.csv", index=False)

    print("\nNode counts:")
    print(nodes_df["label"].value_counts().sort_index())

    print("\nRelationship counts:")
    print(rels_df["type"].value_counts().sort_index())

    print("\nEvent counts:")
    event_nodes = nodes_df[nodes_df["label"] == "ClaimEvent"]
    if len(event_nodes):
        print(event_nodes["event_type"].value_counts().sort_values(ascending=False))
    else:
        print("No ClaimEvent nodes created")


if __name__ == "__main__":
    main()
