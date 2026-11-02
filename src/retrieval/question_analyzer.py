"""
Deterministic question-to-schema mapper for the prototype GraphRAG retriever.

The sponsor asked that GraphRAG start from the schema/graph rather than from a
full-corpus vector search. This module identifies the graph concepts implied by
an incoming question. These outputs can later be compared to manually labelled
"gold" entities/relationships as part of retrieval evaluation.
"""
import re
from typing import Dict, List


ENTITY_RULES = {
    "ClaimEvent": [
        r"\bwhen\b", r"\btimeline\b", r"\bhistory\b", r"\bchange(?:d|s)?\b",
        r"\bstatus\b", r"\boccur(?:red)?\b", r"\bhappen(?:ed)?\b",
    ],
    "BodyPart": [
        r"\bbody part\b", r"\bwhat .* injured\b", r"\binjured (?:area|part)\b",
    ],
    "Treatment": [
        r"\btreatment\b", r"\btherapy\b", r"\bphysical therapy\b", r"\bPT\b",
    ],
    "Medication": [
        r"\bmedication\b", r"\bmedicine\b", r"\bprescri(?:be|bed|ption)\b",
    ],
    "Clinician": [
        r"\bdoctor\b", r"\bphysician\b", r"\bprovider\b", r"\bclinician\b",
        r"\bIME examiner\b",
    ],
    "ClaimsStaff": [
        r"\badjuster\b", r"\bexaminer\b", r"\bclaims staff\b",
    ],
    "Employer": [r"\bemployer\b", r"\bcompany\b"],
    "Carrier": [r"\bcarrier\b", r"\binsurer\b", r"\binsurance company\b"],
    "County": [r"\bcounty\b", r"\bwhere .* (?:accident|incident|injury)\b"],
    "Claimant": [r"\bclaimant\b", r"\bworker\b", r"\binjured worker\b"],
    "Note": [r"\bwhich note", r"\bnotes? support\b", r"\bevidence\b"],
}

EVENT_RULES = {
    "injury_occurred": [
        r"\bdate of injury\b", r"\bwhen .* (?:incident|accident|injury)\b",
        r"\b(?:incident|accident) happen(?:ed)?\b",
    ],
    "injury_reported_to_employer": [
        r"\bwhen .* reported .* employer\b", r"\breported to .* employer\b",
    ],
    "first_report_received": [r"\bfirst report\b", r"\bclaim reported\b"],
    "compensability_decision": [
        r"\bcompensab", r"\baccepted\b", r"\bdenied\b", r"\bdisputed\b",
    ],
    "medical_visit": [
        r"\bmedical visit\b", r"\bdoctor visit\b", r"\bprovider visit\b",
        r"\bseen by\b",
    ],
    "therapy_visit": [r"\btherapy\b", r"\bphysical therapy\b", r"\bPT visit\b"],
    "imaging_ordered": [r"\bMRI .* order", r"\bX[- ]?ray .* order", r"\bimaging .* order"],
    "imaging_result": [r"\bMRI .* result", r"\bX[- ]?ray .* result", r"\bimaging .* result"],
    "authorization_request": [r"\bauthorization request\b", r"\bauth request\b"],
    "authorization_decision": [r"\bauthorization .* approved\b", r"\bauth .* denied\b"],
    "benefit_payment": [r"\bbenefit payment\b", r"\bweekly rate\b", r"\bpaid through\b"],
    "wage_information": [r"\bwage\b", r"\bweekly wage\b", r"\bpayroll\b"],
    "work_status_update": [
        r"\bwork status\b", r"\brestriction", r"\bmodified duty\b",
        r"\blight duty\b", r"\boff work\b", r"\bover time\b.*work",
    ],
    "return_to_full_duty": [
        r"\bfull duty\b", r"\bregular duty\b", r"\breturn(?:ed)? to (?:full|regular) duty\b",
    ],
    "light_duty_offer": [r"\blight duty offer\b", r"\bmodified duty offer\b"],
    "ime_scheduled": [r"\bIME .* sched", r"\bindependent medical examination .* sched"],
    "ime_report": [r"\bIME report\b", r"\bindependent medical examination .* report"],
    "hearing_scheduled": [r"\bhearing .* sched", r"\bnext hearing\b"],
    "hearing_held": [r"\bhearing held\b", r"\bhearing outcome\b"],
    "settlement_discussion": [r"\bsettlement\b", r"\bsection 32\b"],
    "claim_closed": [r"\bclaim closed\b", r"\bclose(?:d)? file\b"],
    "reopen_request": [r"\breopen\b"],
}

RELATIONSHIP_RULES = {
    "NEXT_EVENT": [r"\btimeline\b", r"\bover time\b", r"\bprogress", r"\bchange(?:d|s)?\b"],
    "EVIDENCED_BY": [r"\bwhich note", r"\bevidence\b", r"\bsupport(?:s|ed)?\b"],
    "CORRECTS": [r"\bcorrect(?:ed|ion)?\b", r"\brevised\b"],
    "CONFLICTS_WITH": [r"\bconflict", r"\binconsisten", r"\bdifferent (?:date|value)\b"],
    "RECORDS_MEDICATION": [r"\bmedication\b", r"\bmedicine\b", r"\bprescri"],
    "INCLUDES_TREATMENT": [r"\btreatment\b", r"\btherapy\b"],
    "WRITTEN_BY": [r"\bwho wrote\b", r"\bauthor\b", r"\badjuster\b"],
    "SEEN_BY": [r"\bseen by\b", r"\bdoctor\b", r"\bphysician\b", r"\bprovider\b"],
    "OCCURRED_IN_COUNTY": [r"\bcounty\b", r"\bwhere .* (?:incident|accident|injury)\b"],
}


def _match(question: str, rules: Dict[str, List[str]]) -> List[str]:
    matches = []
    for label, patterns in rules.items():
        if any(re.search(pattern, question, flags=re.IGNORECASE) for pattern in patterns):
            matches.append(label)
    return matches


def analyze_question(question: str) -> Dict[str, List[str]]:
    entities = _match(question, ENTITY_RULES)
    event_types = _match(question, EVENT_RULES)
    relationships = _match(question, RELATIONSHIP_RULES)

    # Safe fallbacks: GraphRAG should always enter through a graph concept.
    if event_types and "ClaimEvent" not in entities:
        entities.append("ClaimEvent")
    if "Medication" in entities and "RECORDS_MEDICATION" not in relationships:
        relationships.append("RECORDS_MEDICATION")
    if "Treatment" in entities and "INCLUDES_TREATMENT" not in relationships:
        relationships.append("INCLUDES_TREATMENT")

    return {
        "entities": entities,
        "event_types": event_types,
        "relationships": relationships,
    }


if __name__ == "__main__":
    examples = [
        "How did the claimant's work restrictions change over time?",
        "When did the accident happen?",
        "Which notes support the claimant's current work restrictions?",
        "What medication was prescribed?",
    ]

    for q in examples:
        print("\nQUESTION:", q)
        print(analyze_question(q))
