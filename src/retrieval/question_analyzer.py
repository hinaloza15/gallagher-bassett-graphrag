"""
Schema-constrained question analyzer for GraphRAG.

Design
------
1. High-recall deterministic rules provide a stable fallback.
2. Qwen3 14B (served locally through Ollama) classifies the
   question into ONLY allowed graph concepts. The project's smaller Qwen model
   remains an automatic fallback.
3. The two outputs are merged, then intent-specific implications are added.

The LLM never writes Cypher and cannot introduce arbitrary graph labels. It is
used only for query understanding.
"""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from typing import Dict, List, Set

# Only labels/relationships that exist in the CURRENT prototype graph are used.
ALLOWED_ENTITIES = [
    "Claim", "Claimant", "Employer", "Carrier", "County", "BodyPart",
    "ClaimsStaff", "Clinician", "Treatment", "Medication", "Note",
    "Chunk", "ClaimEvent",
]

ALLOWED_RELATIONSHIPS = [
    "FILED_BY", "HAS_EMPLOYER", "INSURED_BY", "OCCURRED_IN_COUNTY",
    "HANDLED_BY", "HAS_NOTE", "NEXT_NOTE", "WRITTEN_BY", "CORRECTS",
    "DUPLICATES", "HAS_CHUNK", "HAS_EVENT", "EVIDENCED_BY", "NEXT_EVENT",
    "INCLUDES_TREATMENT", "RECORDS_MEDICATION", "SEEN_BY",
]

# Event types observed in the 15-claim graph. Qwen may choose only these.
ALLOWED_EVENT_TYPES = [
    "work_status_update", "paid_to_date_statement", "form_activity",
    "appointment_scheduled", "return_to_full_duty", "contact", "bill_review",
    "authorization_request", "imaging_ordered", "mileage_reimbursement_request",
    "status_report_sent", "prior_claims_check", "ime_report", "therapy_visit",
    "file_review", "imaging_result", "reserve_review", "pending_item",
    "medical_visit", "hearing_held", "bill_submitted", "wage_information",
    "authorization_decision", "light_duty_offer", "pharmacy_review",
    "contact_attempt", "attendance_report", "hearing_scheduled",
    "employer_reported_to_carrier", "reopen_request", "injury_occurred",
    "claim_closed", "board_determination", "supervisor_statement_taken",
    "supervisor_direction", "nurse_case_review", "compensability_decision",
    "attorney_request", "benefit_payment", "worker_message",
    "injury_reported_to_employer", "claimant_statement_taken", "ime_scheduled",
    "permanency_evaluation", "settlement_discussion",
]

ALLOWED_INTENTS = [
    "factual", "timeline", "multi_note", "conflict", "entity_resolution",
    "provenance", "medical", "treatment", "legal",
]

# High-recall rules. These do not need to be perfect because the LLM augments them.
ENTITY_RULES = {
    "ClaimEvent": [r"\bwhen\b", r"\btimeline\b", r"\bhistory\b", r"\bchange", r"\bstatus\b", r"\boccur", r"\bhappen"],
    "BodyPart": [r"\bbody part\b", r"\binjur(?:y|ed).*\b(?:part|area|arm|leg|knee|back|hip|forearm|shoulder)\b", r"\bdiagnos"],
    "Treatment": [r"\btreatment\b", r"\btherapy\b", r"\bphysical therapy\b", r"\bPT\b"],
    "Medication": [r"\bmedication\b", r"\bmedicine\b", r"\bprescri", r"\btylenol\b", r"\bnaproxen\b", r"\bibuprofen\b"],
    "Clinician": [r"\bdoctor\b", r"\bphysician\b", r"\bprovider\b", r"\bclinician\b", r"\bDr\.?\s+[A-Z]"],
    "ClaimsStaff": [r"\badjuster\b", r"\bclaims staff\b", r"\bassistant\b", r"\bsupervisor\b"],
    "Employer": [r"\bemployer\b", r"\bcompany\b"],
    "Carrier": [r"\bcarrier\b", r"\binsurer\b", r"\binsurance company\b"],
    "County": [r"\bcounty\b"],
    "Claimant": [r"\bclaimant\b", r"\bworker\b", r"\binjured worker\b", r"\bclmt\b"],
    "Note": [r"\bwhich note", r"\bnotes?\b", r"\bevidence\b", r"\bsupport(?:s|ed|ing)?\b", r"\bsource\b"],
}

EVENT_RULES = {
    "injury_occurred": [r"\bdate of injury\b", r"\bDOI\b", r"\bwhen .*?(?:incident|accident|injury)", r"\bcorrect(?:ed|ion).*?(?:date|DOI)"],
    "medical_visit": [r"\bmedical\b", r"\bdoctor visit\b", r"\bprovider\b", r"\bdiagnos"],
    "therapy_visit": [r"\btherapy\b", r"\bphysical therapy\b", r"\bPT\b"],
    "imaging_ordered": [r"\bMRI .*order", r"\bx-?ray .*order", r"\bimaging .*order"],
    "imaging_result": [r"\bMRI\b", r"\bx-?ray\b", r"\bimaging result\b", r"\bscan\b"],
    "work_status_update": [r"\bwork status\b", r"\brestriction", r"\bmodified duty\b", r"\blight duty\b", r"\blifting\b", r"\bbending\b", r"\bkneeling\b"],
    "return_to_full_duty": [r"\bfull duty\b", r"\bregular duty\b", r"\breturn(?:ed)? to .*duty\b", r"\brelease(?:d)?\b.*\bno restrictions\b"],
    "ime_scheduled": [r"\bIME .*sched", r"\bindependent medical examination .*sched"],
    "ime_report": [r"\bIME\b", r"\bindependent medical examination\b", r"\bpeer review\b"],
    "hearing_scheduled": [r"\bnext hearing\b", r"\bhearing .*sched", r"\bhearing date\b"],
    "hearing_held": [r"\bhearing held\b", r"\bhearing outcome\b", r"\bjudge\b", r"\badjourn"],
    "compensability_decision": [r"\bcompensab", r"\baccepted\b", r"\bdenied\b", r"\bwork related\b"],
    "wage_information": [r"\bwage\b", r"\bweekly wage\b", r"\bpayroll\b"],
    "authorization_request": [r"\bauthorization\b", r"\bauth request\b"],
    "authorization_decision": [r"\bauthorization .*approved\b", r"\bauth .*denied\b"],
    "claim_closed": [r"\bclaim closed\b", r"\bclosed the case\b", r"\bclosing note\b"],
    "reopen_request": [r"\breopen\b"],
}

RELATIONSHIP_RULES = {
    "NEXT_EVENT": [r"\btimeline\b", r"\bover time\b", r"\bprogress", r"\bchange", r"\bdevelop", r"\bevolv", r"\bbefore\b.*\bafter\b"],
    "EVIDENCED_BY": [r"\bwhich note", r"\bevidence\b", r"\bsupport(?:s|ed|ing)?\b", r"\bsource\b", r"\bprove\b"],
    "CORRECTS": [r"\bcorrect(?:ed|ion)?\b", r"\brevised\b", r"\bwhich .* (?:correct|right)\b", r"\binstead of\b", r"\bnot .* but\b"],
    "RECORDS_MEDICATION": [r"\bmedication\b", r"\bmedicine\b", r"\bprescri", r"\btylenol\b", r"\bnaproxen\b", r"\bibuprofen\b"],
    "INCLUDES_TREATMENT": [r"\btreatment\b", r"\btherapy\b", r"\bPT\b"],
    "WRITTEN_BY": [r"\bwho wrote\b", r"\bauthor\b", r"\badjuster\b", r"\bsame person\b", r"\bsame entity\b"],
    "SEEN_BY": [r"\bseen by\b", r"\bdoctor\b", r"\bphysician\b", r"\bprovider\b"],
}


def _match(question: str, rules: Dict[str, List[str]]) -> List[str]:
    found = []
    for label, patterns in rules.items():
        if any(re.search(p, question, flags=re.IGNORECASE) for p in patterns):
            found.append(label)
    return found


def _heuristic_intents(question: str) -> List[str]:
    q = question.lower()
    intents: Set[str] = set()
    if any(x in q for x in ["correct", "conflict", "inconsisten", "which date", "which body part is correct", "rather than", "not "]):
        intents.add("conflict")
    if any(x in q for x in ["over time", "timeline", "progress", "change", "develop", "from ", "before", "after", "ultimately", "eventually"]):
        intents.add("timeline")
    if any(x in q for x in ["which notes", "what notes", "evidence", "support the conclusion", "support that", "provenance", "source"]):
        intents.add("provenance")
    if any(x in q for x in ["same claimant", "same person", "same entity", "refer to the same", "merged", "distinct", "different people", "misspelling", "spelling variation"]):
        intents.add("entity_resolution")
    # Multi-note means the question requires multiple distinct facts, not merely a long sentence.
    if (" and " in q and any(x in q for x in ["mri", "ime", "work status", "hearing", "treatment", "restrictions", "return", "diagnosis"])) or "how did" in q:
        intents.add("multi_note")
    if any(x in q for x in ["mri", "x-ray", "xray", "diagnosis", "medical", "doctor", "ime"]):
        intents.add("medical")
    if any(x in q for x in ["treatment", "therapy", "pt ", "medication"]):
        intents.add("treatment")
    if any(x in q for x in ["hearing", "judge", "board", "attorney", "legal"]):
        intents.add("legal")
    if not intents:
        intents.add("factual")
    return sorted(intents)


def _extract_json_object(text: str) -> dict:
    text = text.strip()
    # Strip markdown fences if the model ignored the instruction.
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    try:
        return json.loads(text[start:end + 1])
    except Exception:
        return {}


def _filter(values, allowed) -> List[str]:
    """Normalize possibly messy LLM output into a flat allowed string list.

    Qwen may occasionally return objects such as {"name": "ClaimEvent"}
    instead of plain strings. Accept common object shapes, ignore anything else,
    and never allow values outside the fixed schema.
    """
    allowed_set = set(allowed)
    out = []

    if values is None:
        return out
    if isinstance(values, (str, dict)):
        values = [values]

    for value in values:
        if isinstance(value, dict):
            candidate = None
            for key in ("name", "value", "label", "type", "entity", "relationship", "event_type", "intent"):
                v = value.get(key)
                if isinstance(v, str):
                    candidate = v
                    break
            value = candidate
        if not isinstance(value, str):
            continue
        value = value.strip()
        if value in allowed_set and value not in out:
            out.append(value)
    return out


@lru_cache(maxsize=256)
def _llm_analyze(question: str) -> Dict[str, List[str]]:
    """Use Qwen3 14B as a schema-constrained query planner."""
    use_llm = os.getenv("GRAPHRAG_USE_LLM_ANALYZER", "1").strip().lower() not in {"0", "false", "no"}
    if not use_llm:
        return {"intents": [], "entities": [], "event_types": [], "relationships": [], "planner_name": "disabled"}

    system = (
        "You are the query planner for a workers' compensation Neo4j GraphRAG system. "
        "Do NOT answer the claim question. Map it only to the supplied graph schema. "
        "Return one JSON object and nothing else. You may use ONLY allowed values. "
        "Choose all concepts required to retrieve complete evidence, not just the most obvious concept. "
        "For timeline/change questions include NEXT_EVENT and all relevant start/intermediate/end event types. "
        "For evidence/source questions include EVIDENCED_BY and Note. "
        "For corrections or conflicting facts include CORRECTS and the fact's event type. "
        "For multi-part questions include concepts for every sub-question. "
        "For entity resolution distinguish people by graph role; never merge people merely because names match."
    )
    user = f"""Question: {question}

Allowed intents:
{json.dumps(ALLOWED_INTENTS)}

Allowed entities:
{json.dumps(ALLOWED_ENTITIES)}

Allowed relationships:
{json.dumps(ALLOWED_RELATIONSHIPS)}

Allowed event types:
{json.dumps(ALLOWED_EVENT_TYPES)}

Return exactly this JSON shape:
{{"intents": [], "entities": [], "relationships": [], "event_types": []}}
"""

    try:
        from src.retrieval.planner_client import run_planner
        data, planner_name = run_planner(system, user)
        return {
            "intents": _filter(data.get("intents"), ALLOWED_INTENTS),
            "entities": _filter(data.get("entities"), ALLOWED_ENTITIES),
            "relationships": _filter(data.get("relationships"), ALLOWED_RELATIONSHIPS),
            "event_types": _filter(data.get("event_types"), ALLOWED_EVENT_TYPES),
            "planner_name": planner_name,
        }
    except Exception as exc:
        print(f"[GraphRAG] LLM analyzer unavailable; using deterministic analyzer: {exc}")
        return {"intents": [], "entities": [], "event_types": [], "relationships": [], "planner_name": "deterministic_fallback"}


def _merge_unique(*lists) -> List[str]:
    out = []
    for values in lists:
        for value in values or []:
            if value not in out:
                out.append(value)
    return out


@lru_cache(maxsize=256)
def analyze_question(question: str) -> Dict[str, List[str]]:
    """Return a high-recall, schema-constrained query plan."""
    heuristic = {
        "intents": _heuristic_intents(question),
        "entities": _match(question, ENTITY_RULES),
        "event_types": _match(question, EVENT_RULES),
        "relationships": _match(question, RELATIONSHIP_RULES),
    }
    llm = _llm_analyze(question)

    intents = _merge_unique(heuristic["intents"], llm["intents"])
    entities = _merge_unique(heuristic["entities"], llm["entities"])
    event_types = _merge_unique(heuristic["event_types"], llm["event_types"])
    relationships = _merge_unique(heuristic["relationships"], llm["relationships"])

    # Intent implications make the planner robust even when Qwen omits one field.
    if event_types and "ClaimEvent" not in entities:
        entities.append("ClaimEvent")

    if "timeline" in intents:
        for rel in ["NEXT_EVENT", "EVIDENCED_BY"]:
            if rel not in relationships:
                relationships.append(rel)
        if "ClaimEvent" not in entities:
            entities.append("ClaimEvent")

    if "provenance" in intents:
        for ent in ["Note", "ClaimEvent"]:
            if ent not in entities:
                entities.append(ent)
        if "EVIDENCED_BY" not in relationships:
            relationships.append("EVIDENCED_BY")

    if "conflict" in intents:
        for ent in ["Note", "ClaimEvent"]:
            if ent not in entities:
                entities.append(ent)
        for rel in ["CORRECTS", "EVIDENCED_BY"]:
            if rel not in relationships:
                relationships.append(rel)
        # DOI conflicts are extremely common in this corpus.
        q = question.lower()
        if any(x in q for x in ["date of injury", "doi", "injury date"]):
            if "injury_occurred" not in event_types:
                event_types.append("injury_occurred")

    if "entity_resolution" in intents:
        for ent in ["Claimant", "ClaimsStaff", "Clinician", "Note"]:
            if ent not in entities:
                entities.append(ent)
        for rel in ["FILED_BY", "WRITTEN_BY"]:
            if rel not in relationships:
                relationships.append(rel)

    if "Medication" in entities and "RECORDS_MEDICATION" not in relationships:
        relationships.append("RECORDS_MEDICATION")
    if "Treatment" in entities and "INCLUDES_TREATMENT" not in relationships:
        relationships.append("INCLUDES_TREATMENT")

    # Work-status history usually needs both the changing restrictions and the
    # terminal full-duty state for complete timeline coverage.
    ql = question.lower()
    if any(x in ql for x in ["work restriction", "work status", "modified duty", "full duty", "return to work"]):
        if "work_status_update" not in event_types:
            event_types.append("work_status_update")
        if any(x in ql for x in ["change", "progress", "over time", "ultimately", "full duty", "return"]):
            if "return_to_full_duty" not in event_types:
                event_types.append("return_to_full_duty")

    return {
        "intents": _filter(intents, ALLOWED_INTENTS),
        "entities": _filter(entities, ALLOWED_ENTITIES),
        "event_types": _filter(event_types, ALLOWED_EVENT_TYPES),
        "relationships": _filter(relationships, ALLOWED_RELATIONSHIPS),
        "planner": ("rules_plus_" + llm.get("planner_name", "qwen3:14b")) if llm["intents"] or llm["entities"] or llm["event_types"] or llm["relationships"] else "deterministic_fallback",
    }


if __name__ == "__main__":
    examples = [
        "How did the claimant's work restrictions change over time?",
        "The notes list December 15 and December 16 as the DOI. Which date is correct?",
        "Which notes support the claimant's current work restrictions?",
        "Do Juliann Bell and Julian Bell refer to the same claimant?",
        "What did Chloe's MRI show and how did her work restrictions change afterward?",
    ]
    for q in examples:
        print("\nQUESTION:", q)
        print(json.dumps(analyze_question(q), indent=2))
