"""
02_build_graph_from_claim_notes.py

Builds the GraphRAG knowledge graph (schema v1) from the claim-notes file and the reference seeds,
validates every node and relationship against 01_schema/01_graph_schema_definition_v1.yaml,
and writes the outputs listed in README section 5 to 05_outputs/.

Run from the repository folder (graph_schema_v1/):
    python 03_code/02_build_graph_from_claim_notes.py \
        --notes data/claim_notes/GB_15claims_Pack_Notes.csv \
        --out 05_outputs
Optional:
    --reference-docs data/reference_docs     folder made by 01_download_reference_documents.py
    --ny-claims data/Assembled_Workers__Compensation_Claims.csv   adds WCIO codes (not required)

Extraction here is RULE-BASED (regular expressions written for this note set). It is the reference
build that proves the schema can hold every fact in the notes. The team's LLM or System 1 extractor
should produce the same node labels and relationship types; compare its output with this one.
Every relationship extracted from note text is marked review_status='unreviewed'.

Do NOT give this script pack_notes_answer_key.csv. It is for the evaluation team only.
"""
import argparse, csv, datetime as dt, hashlib, json, os, re, sys
from collections import defaultdict, Counter

import pandas as pd
import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib_text_normalization import (parse_dates_in_text, first_date, normalize_name, name_variants,
                                    fuzzy_equal, slug, money_values, split_history_paragraph)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_VERSION = None
CHUNK_MAX_WORDS = 220

# ============================================================== graph store
NODES = {}             # (label, key) -> props
EDGES = {}             # dedupe key -> edge dict
LOG = defaultdict(list)


def nid(label, key):
    return f"{label}:{key}"


def add_node(label, key, **props):
    k = (label, str(key))
    cur = NODES.setdefault(k, {"_label": label, "_key": str(key)})
    for p, v in props.items():
        if v is None or (isinstance(v, float) and pd.isna(v)):
            continue
        if isinstance(v, (list, set, tuple)):
            cur[p] = sorted(set(cur.get(p, [])) | set(v))
        elif p not in cur or cur[p] in ("", None):
            cur[p] = v
    return k


def add_edge(rtype, frm, to, source_type, source_id, method, review_status, scope_claim_id="",
             dedupe_on=(), **props):
    """frm / to are (label, key) tuples. dedupe_on: property names that make the edge distinct."""
    dk = (rtype, frm, to) + tuple(str(props.get(p, "")) for p in dedupe_on)
    if dk in EDGES:
        e = EDGES[dk]
        e["source_ids"].add(str(source_id))
        return e
    e = dict(type=rtype, from_label=frm[0], from_key=frm[1], to_label=to[0], to_key=to[1],
             source_type=source_type, source_ids={str(source_id)}, method=method,
             review_status=review_status, schema_version=SCHEMA_VERSION,
             scope_claim_id=str(scope_claim_id), props=props)
    EDGES[dk] = e
    return e


# ============================================================== helpers
def vocab_id(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def to_date(s):
    return dt.date.fromisoformat(s) if isinstance(s, str) else s


def sentences_with(text, pattern, flags=re.I):
    for m in re.finditer(pattern, text, flags):
        yield m


def clean_space(s):
    return re.sub(r"\s+", " ", s or "").strip(" .,;:-")


def title_name(s):
    return " ".join(w if w.isupper() and len(w) <= 4 else w.capitalize() for w in s.split())


# ============================================================== registries built per claim
class ClaimContext:
    def __init__(self, claim_id):
        self.claim_id = claim_id
        self.alias = []            # (regex, (label,key), method)
        self.entities = {}         # (label,key) -> display name
        self.treating_facility = None
        self.treating_clinicians = set()
        self.pt_facilities = Counter()
        self.employer = None
        self.carrier = None
        self.claimant = None
        self.first_note_date = None

    def register(self, ent, names, method="alias_match", word_boundary=True):
        for n in names:
            n = n.strip()
            if len(n) < 2:
                continue
            pat = re.escape(n).replace(r"\ ", r"\s+")
            pat = r"(?<![A-Za-z])" + pat + r"(?![A-Za-z])" if word_boundary else pat
            self.alias.append((re.compile(pat, re.I if n.lower() != n.upper() and len(n) > 3 else 0), ent, method, n))

    def find(self, text):
        """Return list of (ent, start, end, matched_text, method) for entity mentions in text.
        If two different entities match exactly the same words (e.g. claimant and adjuster are both
        'Maya Patel' on claim 6977140) the mention is AMBIGUOUS: it is skipped and logged, never guessed."""
        hits = []
        for rx, ent, method, n in self.alias:
            for m in rx.finditer(text):
                hits.append((ent, m.start(), m.end(), m.group(0), method))
        same_span = defaultdict(set)
        for h in hits:
            same_span[(h[1], h[2])].add(h[0])
        hits.sort(key=lambda h: (h[1], -(h[2] - h[1])))
        out, last_end = [], -1
        for h in hits:
            if h[1] >= last_end:
                if len(same_span[(h[1], h[2])]) > 1:
                    AMBIGUOUS[(self.claim_id, h[3])] = sorted(f"{l}:{k}" for l, k in same_span[(h[1], h[2])])
                    last_end = h[2]
                    continue
                out.append(h); last_end = h[2]
        return out


AMBIGUOUS = {}
CLAIM_RECORD_DOI = {}
ALL_PERSON_WORDS = set()
PROPER_TOKENS = set()
UPPER_KEEP = {"IME", "MRI", "PT", "DOI", "LM", "VM", "EE", "IW", "ER", "RTW", "HEP", "ROM", "SIF", "NCM", "MMI", "OTC",
              "NSAIDS", "RTC", "MG", "RFA", "C", "LC", "RN", "TX", "DX", "SX", "II", "L4", "L5"}


def mostly_upper(t):
    letters = [c for c in t if c.isalpha()]
    return len(letters) > 15 and sum(c.isupper() for c in letters) / len(letters) > 0.8


def rule_text(t):
    """Notes typed in ALL CAPS are converted to normal case for the extraction rules only.
    Character positions do not change, so evidence quotes are still taken from the original text."""
    t = re.sub(r"\bDR\b(?= [A-Z])", "Dr", t)
    if not mostly_upper(t):
        return t
    chars = list(t.lower())
    for m in re.finditer(r"[A-Za-z]+", t):
        w = m.group(0)
        if w.upper() in UPPER_KEEP:
            chars[m.start():m.end()] = list(w.upper())
        elif w.lower() in PROPER_TOKENS or w.lower() == "dr":
            chars[m.start()] = w[0].upper()
    out = "".join(chars)
    return re.sub(r"(^|[.!?]\s+|\n)([a-z])", lambda x: x.group(1) + x.group(2).upper(), out)


def email_domain_of(name):
    return re.sub(r"[^a-z0-9]", "", name.lower().replace("&", "")) + ".example"


# ============================================================== event store
EVENTS = {}       # event_id -> dict
EVENT_KEYS = {}   # identity tuple -> event_id


def event_id_for(identity):
    h = hashlib.sha1(json.dumps(identity, default=str).encode()).hexdigest()[:10]
    return f"EV-{identity[0]}-{identity[1]}-{h}"


def record_event(ctx, etype, identity_extra, event_date, date_basis, note, evidence_kind, quote_span,
                 attrs=None, participants=(), forms=(), treatments=(), meds=(), diagnosis=None,
                 summary=None):
    """Create or extend an event. identity_extra = tuple that makes the event unique on the claim."""
    identity = (ctx.claim_id, etype) + tuple(identity_extra)
    eid = EVENT_KEYS.get(identity)
    if eid is None:
        eid = event_id_for(identity)
        EVENT_KEYS[identity] = eid
        EVENTS[eid] = dict(event_id=eid, claim_id=ctx.claim_id, event_type=etype, event_date=event_date,
                           date_basis=date_basis, attrs=defaultdict(list), evidence=[], participants=set(),
                           forms=set(), treatments=set(), meds=set(), diagnosis=diagnosis,
                           summary=summary or "", identity=identity)
    ev = EVENTS[eid]
    if (not ev["event_date"]) and event_date:
        ev["event_date"], ev["date_basis"] = event_date, date_basis
    for k, v in (attrs or {}).items():
        if v not in (None, "", []):
            ev["attrs"][k].append((v, note["note_id"]))
    s, e = quote_span
    ev["evidence"].append(dict(note_id=note["note_id"], kind=evidence_kind, start=s, end=e,
                               quote=note["text"][s:e][:300]))
    ev["participants"] |= set(participants)
    ev["forms"] |= set(forms)
    ev["treatments"] |= set(treatments)
    ev["meds"] |= set(meds)
    if diagnosis and not ev["diagnosis"]:
        ev["diagnosis"] = diagnosis
    if summary and not ev["summary"]:
        ev["summary"] = summary
    return eid


# ============================================================== main build
def main():
    global SCHEMA_VERSION
    ap = argparse.ArgumentParser()
    ap.add_argument("--notes", default=os.path.join(ROOT, "data/claim_notes/GB_15claims_Pack_Notes.csv"))
    ap.add_argument("--out", default=os.path.join(ROOT, "05_outputs"))
    ap.add_argument("--reference-docs", default=os.path.join(ROOT, "data/reference_docs"))
    ap.add_argument("--ny-claims", default=None)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    schema = yaml.safe_load(open(os.path.join(ROOT, "01_schema/01_graph_schema_definition_v1.yaml")))
    SCHEMA_VERSION = schema["schema_version"]
    etypes = pd.read_csv(os.path.join(ROOT, "01_schema/04_claim_event_types.csv"))
    ETYPE_CAT = dict(zip(etypes.event_type, etypes.event_category))
    ETYPE_STEPS = {r.event_type: [s.strip() for s in str(r.process_step_ids).split(";") if s.strip() and s.strip() != "nan"]
                   for r in etypes.itertuples()}

    if "answer_key" in os.path.basename(args.notes).lower():
        sys.exit("Refusing to read the evaluation answer key. Pass the notes file instead.")
    df = pd.read_csv(args.notes)
    df["Note Date"] = pd.to_datetime(df["Note Date"]).dt.date
    df["note_no"] = df["Note ID"].str.extract(r"-(\d+)$")[0].astype(int)
    df = df.sort_values(["Claim Identifier", "Note Date", "note_no"]).reset_index(drop=True)
    for c in ["Synthetic Note Text"]:
        df[c] = df[c].fillna("")

    ref = os.path.join(ROOT, "02_reference_data")
    facilities_seed = pd.read_csv(os.path.join(ref, "07_healthcare_facilities_seed.csv")).fillna("")
    treat_seed = pd.read_csv(os.path.join(ref, "08_treatments_and_medications_seed.csv")).fillna("")
    forms_seed = pd.read_csv(os.path.join(ref, "03_wcb_forms.csv")).fillna("")
    roles_seed = pd.read_csv(os.path.join(ref, "05_process_roles.csv")).fillna("")
    steps_seed = pd.read_csv(os.path.join(ref, "04_claims_process_steps.csv")).fillna("")
    docs_seed = pd.read_csv(os.path.join(ref, "06_reference_documents_manifest.csv")).fillna("")
    bp_map = pd.read_csv(os.path.join(ref, "02_body_part_to_treatment_guideline_map.csv")).fillna("")

    NY = {}
    if args.ny_claims and os.path.exists(args.ny_claims):
        ny = pd.read_csv(args.ny_claims, dtype=str)
        col = {re.sub(r"[^a-z0-9]", "", c.lower()): c for c in ny.columns}
        def pick(*names):
            for n in names:
                if re.sub(r"[^a-z0-9]", "", n.lower()) in col:
                    return col[re.sub(r"[^a-z0-9]", "", n.lower())]
            return None
        want = {"id": pick("Claim Identifier"), "nature": pick("WCIO Nature of Injury Code"), "body": pick("WCIO Part Of Body Code"),
                "cause": pick("WCIO Cause of Injury Code"), "acc": pick("Accident Date"), "ctype": pick("Carrier Type"),
                "itype": pick("Claim Injury Type"), "hp": pick("Highest Process"), "dist": pick("District Name"),
                "ind": pick("Industry Code"), "indd": pick("Industry Code Description")}
        ids = set(df["Claim Identifier"].astype(str))
        sub = ny[ny[want["id"]].astype(str).isin(ids)] if want["id"] else ny.iloc[0:0]
        NY = {str(r[want["id"]]): {k: (r[v] if v else None) for k, v in want.items()} for _, r in sub.iterrows()}
        LOG["info"].append(f"NY claims file: {len(NY)} of {len(ids)} claims found; missing columns: {[k for k, v in want.items() if not v]}")
    else:
        LOG["info"].append("NY claims file not given: wcio_code and *_record properties left empty (pass --ny-claims to fill them)")

    # ---------------------------------------------------------- L6 process knowledge (global)
    for r in roles_seed.itertuples():
        add_node("Role", r.role_name, role_name=r.role_name, description=r.description,
                 instance_labels=[s.strip() for s in r.instance_labels.split(";") if s.strip()])
    for r in docs_seed.itertuples():
        local = os.path.join(args.reference_docs, r.local_file)
        add_node("Document", r.doc_id, doc_id=r.doc_id, title=r.title, doc_type=r.doc_type, publisher=r.publisher,
                 url=r.url, local_file=r.local_file, redistribution=r.redistribution, downloaded=os.path.exists(local))
    for r in forms_seed.itertuples():
        add_node("Form", r.form_code, form_code=r.form_code, title=r.title, filed_by=r.filed_by_role, purpose=r.purpose)
        if r.described_in_doc_id:
            add_edge("DESCRIBED_IN", ("Form", r.form_code), ("Document", r.described_in_doc_id),
                     "reference_seed", f"03_wcb_forms.csv:{r.form_code}", "curated", "draft")
    for r in steps_seed.itertuples():
        add_node("ProcessStep", r.step_id, step_id=r.step_id, name=r.name, rule_text=r.rule_text_quote,
                 deadline_days=int(r.deadline_days) if str(r.deadline_days).strip() else None, deadline_text=r.deadline_text)
        add_edge("DESCRIBED_IN", ("ProcessStep", r.step_id), ("Document", r.source_doc_id), "reference_seed",
                 f"04_claims_process_steps.csv:{r.step_id}", "curated", "draft", quote=r.rule_text_quote,
                 quote_check_status=r.quote_check_status)
        add_edge("PERFORMED_BY", ("ProcessStep", r.step_id), ("Role", r.performed_by_role), "reference_seed",
                 f"04_claims_process_steps.csv:{r.step_id}", "curated", "draft")
        for fc in [f.strip() for f in str(r.form_codes).split(";") if f.strip()]:
            add_edge("USES_FORM", ("ProcessStep", r.step_id), ("Form", fc), "reference_seed",
                     f"04_claims_process_steps.csv:{r.step_id}", "curated", "draft")
        for nx in [f.strip() for f in str(r.precedes).split(";") if f.strip()]:
            add_edge("PRECEDES", ("ProcessStep", r.step_id), ("ProcessStep", nx), "reference_seed",
                     f"04_claims_process_steps.csv:{r.step_id}", "curated", "draft")
    for r in treat_seed.itertuples():
        lab = "Treatment" if r.kind == "treatment" else "Medication"
        add_node(lab, vocab_id(r.name), **({"treatment_id": vocab_id(r.name)} if lab == "Treatment" else {"medication_id": vocab_id(r.name)}), name=r.name)
    TREAT_RX = [(re.compile(r.patterns, re.I), ("Treatment" if r.kind == "treatment" else "Medication", vocab_id(r.name)))
                for r in treat_seed.itertuples()]
    FORM_RX = re.compile(r"\b(C-3|C-2F|C-4\.2|C-7|C-257|MG-2|RFA-1(?:LC)?)\b")

    # facility seeds (global; claim scope decides use)
    FAC_SEED = {}
    for r in facilities_seed.itertuples():
        fid = "FAC-" + slug(r.name)
        add_node("HealthcareFacility", fid, facility_id=fid, name=r.name, facility_type=r.facility_type,
                 aliases=[r.name] + [a.strip() for a in r.aliases.split(";") if a.strip()])
        FAC_SEED[fid] = [r.name] + [a.strip() for a in r.aliases.split(";") if a.strip()]

    # staff registry from headers (global)
    staff_roles = {"adjuster": "adjuster", "assistant": "assistant", "supervisor": "supervisor",
                   "nurse": "nurse_case_manager", "specialist": "specialist"}
    STAFF = {}
    for (name, role), g in df[df["Author Role"].isin(staff_roles)].groupby(["Note Author", "Author Role"]):
        sid = "STAFF-" + slug(name)
        first = re.sub(r"\s+RN$", "", name).split()[0]
        initials = "".join(w[0] for w in re.sub(r"\s+RN$", "", name).split()[:2]).upper()
        STAFF[sid] = dict(name=name, role=staff_roles[role], first=first, initials=initials)
        add_node("ClaimsStaff", sid, staff_id=sid, name=name, primary_role=staff_roles[role], initials=initials,
                 aliases=[name, re.sub(r"\s+RN$", "", name)])
    STAFF_BY_FIRST = defaultdict(list)
    for sid, s in STAFF.items():
        STAFF_BY_FIRST[s["first"].lower()].append(sid)
    STAFF_BY_INIT = {s["initials"]: sid for sid, s in STAFF.items()}

    # ---------------------------------------------------------- per claim
    claim_ctx = {}
    note_rows = {}
    for cid, g in df.groupby("Claim Identifier", sort=True):
        cid = str(cid)
        first = g.iloc[0]
        ctx = ClaimContext(cid)
        ctx.first_note_date = g["Note Date"].min()
        claim_ctx[cid] = ctx
        # consistency check of structured columns
        for col in ["Synthetic Claimant", "Synthetic Employer", "Synthetic Adjuster", "Synthetic Provider",
                    "Synthetic Location", "County (source)", "Carrier (source)", "Injury Nature (source)",
                    "Body Part (source)", "Cause (source)", "Claim Status (source)"]:
            if g[col].nunique() > 1:
                LOG["data_issue"].append(f"Claim {cid}: column '{col}' has {g[col].nunique()} different values")
        claim = add_node("Claim", cid, claim_id=cid, claim_status_source=first["Claim Status (source)"],
                         claimant_name=first["Synthetic Claimant"], first_note_date=str(g["Note Date"].min()),
                         last_note_date=str(g["Note Date"].max()), note_count=len(g))
        src = f"claim_record:{cid}"
        # claimant
        cname = first["Synthetic Claimant"]
        clmt = add_node("Claimant", f"CLMT-{cid}", claimant_id=f"CLMT-{cid}", name=cname, aliases=[cname])
        ctx.claimant = clmt
        add_edge("FILED_BY", claim, clmt, "claim_record", src, "structured_field", "approved", cid)
        # employer
        emp_id = "EMP-" + slug(first["Synthetic Employer"])
        emp = add_node("Employer", emp_id, employer_id=emp_id, name=first["Synthetic Employer"],
                       email_domain=email_domain_of(first["Synthetic Employer"]),
                       aliases=name_variants(first["Synthetic Employer"]))
        ctx.employer = emp
        add_edge("HAS_EMPLOYER", claim, emp, "claim_record", src, "structured_field", "approved", cid)
        # carrier
        car_name = first["Carrier (source)"]
        car_id = "CAR-" + slug(car_name)
        car_alias = {car_name, title_name(car_name.lower()).replace(",", ""), car_name.replace(", INC.", "").title()}
        if car_name == "STATE INSURANCE FUND":
            car_alias |= {"SIF", "State Ins Fund", "State Insurance Fund"}
        car_alias |= {a.replace(" Company", " Co").replace(" COMPANY", " CO") for a in list(car_alias)}
        car = add_node("Carrier", car_id, carrier_id=car_id, name=car_name, aliases=sorted(car_alias))
        ctx.carrier = car
        add_edge("INSURED_BY", claim, car, "claim_record", src, "structured_field", "approved", cid)
        if not re.search(r"INSURANCE|FUND|CASUALTY|\bCO\b|COMPANY", car_name):
            LOG["data_issue"].append(f"Claim {cid}: carrier '{car_name}' looks like a self-insured employer, but the synthetic employer is '{first['Synthetic Employer']}'")
        # county, location
        cty = add_node("County", first["County (source)"].title(), county_name=first["County (source)"].title())
        add_edge("OCCURRED_IN_COUNTY", claim, cty, "claim_record", src, "structured_field", "approved", cid)
        loc_name = first["Synthetic Location"]
        loc_id = "LOC-" + slug(loc_name)
        site = re.sub(r"^.*? County ", "", loc_name)
        loc = add_node("IncidentLocation", loc_id, location_id=loc_id, name=loc_name, site_type=site)
        add_edge("OCCURRED_AT", claim, loc, "claim_record", src, "structured_field", "approved", cid)
        add_edge("LOCATED_IN", loc, cty, "claim_record", src, "structured_field", "approved", "")
        # injury vocab
        nat = add_node("InjuryNature", "NAT-" + slug(first["Injury Nature (source)"]), nature_id="NAT-" + slug(first["Injury Nature (source)"]),
                       name=first["Injury Nature (source)"], wcio_code="")
        add_edge("HAS_INJURY_NATURE", claim, nat, "claim_record", src, "structured_field", "approved", cid)
        bp = add_node("BodyPart", "BP-wcio-" + slug(first["Body Part (source)"]), body_part_id="BP-wcio-" + slug(first["Body Part (source)"]),
                      name=first["Body Part (source)"], granularity="wcio", wcio_code="")
        add_edge("HAS_BODY_PART", claim, bp, "claim_record", src, "structured_field", "approved", cid)
        cause = first["Cause (source)"]
        cz = add_node("InjuryCause", "CAU-" + slug(cause), cause_id="CAU-" + slug(cause), name=cause,
                      cause_group=cause.split(" - ")[0], wcio_code="")
        add_edge("HAS_CAUSE", claim, cz, "claim_record", src, "structured_field", "approved", cid)
        rec = NY.get(cid)
        if rec:
            def code(v):
                return str(v).split(".")[0] if v not in (None, "") and str(v) != "nan" else ""
            for node_k, v in ((nat, code(rec["nature"])), (bp, code(rec["body"])), (cz, code(rec["cause"]))):
                old = NODES[node_k].get("wcio_code", "")
                if old and v and old != v:
                    LOG["data_issue"].append(f"{node_k[0]} '{NODES[node_k]['name']}' has WCIO code {old} on one claim and {v} on claim {cid}: "
                                             "the same name covers different codes, so key this node by code (see README)")
                elif v:
                    NODES[node_k]["wcio_code"] = v
            acc = str(rec["acc"])[:10] if rec["acc"] not in (None, "") and str(rec["acc"]) != "nan" else ""
            add_node("Claim", cid, accident_date_record=acc, carrier_type_record=rec["ctype"], claim_injury_type_record=rec["itype"],
                     highest_process_record=rec["hp"], district_record=rec["dist"], industry_code_record=code(rec["ind"]),
                     industry_description_record=rec["indd"])
            CLAIM_RECORD_DOI[cid] = acc
        # treating clinic (structured column)
        prov = first["Synthetic Provider"]
        fid = "FAC-" + slug(prov)
        fac = add_node("HealthcareFacility", fid, facility_id=fid, name=prov, facility_type="treating_clinic",
                       email_domain=email_domain_of(prov), aliases=name_variants(prov))
        ctx.treating_facility = fac
        add_edge("TREATED_AT", claim, fac, "claim_record", src, "structured_field", "approved", cid,
                 dedupe_on=("service",), service="treating_clinic")

        # register claim-scope aliases
        ctx.register(clmt, [cname], "alias_match")
        ctx.register(emp, name_variants(first["Synthetic Employer"]))
        ctx.register(car, sorted(car_alias))
        ctx.register(fac, name_variants(prov))
        for fid2, names in FAC_SEED.items():
            ctx.register(("HealthcareFacility", fid2), names)
        for sid, s in STAFF.items():
            ctx.register(("ClaimsStaff", sid), [s["name"], re.sub(r"\s+RN$", "", s["name"])])
        for fc in forms_seed.form_code:
            ctx.register(("Form", fc), [fc] + (["RFA-1LC"] if fc == "RFA-1" else []))
        for r in treat_seed.itertuples():
            pass  # treatments matched by TREAT_RX
        ctx.entities.update({clmt: cname, emp: first["Synthetic Employer"], car: car_name, fac: prov})
        for _, row in g.iterrows():
            note_rows[row["Note ID"]] = row

    # every word used in any person name anywhere in the data (so 'Joan' is never read as a misspelling of 'Jordan')
    ALL_PERSON_WORDS.update(w.lower() for col in ["Note Author", "Synthetic Claimant", "Synthetic Adjuster"] for n in df[col].dropna().unique() for w in str(n).split())
    for n in re.findall(r"\b([A-Z][a-z]+) [A-Z][a-z]+\b", "\n".join(df["Synthetic Note Text"])):
        pass
    for n in re.findall(r"(?:From: |ER contact |ER supervisor |Hi |Dr |\()([A-Z][a-z]+)", "\n".join(df["Synthetic Note Text"])):
        ALL_PERSON_WORDS.add(n.lower())

    # ---------------------------------------------------------- people found in note text (pass 1)
    attorney_firm = {}
    for _, r in df.iterrows():
        for n, d in re.findall(r"From: ([A-Z][a-z]+ [A-Z][a-z]+) <[^@]+@(\w+law)\.example", r["Synthetic Note Text"]):
            attorney_firm[n] = d + ".example"

    for cid, g in df.groupby("Claim Identifier", sort=True):
        cid = str(cid); ctx = claim_ctx[cid]
        T = "\n".join(g["Synthetic Note Text"])
        emp_dom = NODES[ctx.employer]["email_domain"].split(".")[0]
        emp_contacts = {}
        def add_contact(name, role, how, src):
            ckey = "ERC-" + slug(name) + "-" + ctx.employer[1].replace("EMP-", "")
            node = add_node("EmployerContact", ckey, contact_id=ckey, name=name, contact_role=role, aliases=[name])
            if NODES[node].get("contact_role") != role and role == "supervisor":
                NODES[node]["contact_role"] = role
            add_edge("HAS_EMPLOYER_CONTACT", ("Claim", cid), node, "note_text", src, how, "unreviewed", cid,
                     dedupe_on=("role",), role=role)
            add_edge("WORKS_FOR", node, ctx.employer, "note_text", src, how, "unreviewed", cid)
            emp_contacts[name] = node
            return node
        for _, r in g.iterrows():
            t = r["Synthetic Note Text"]
            for m in re.finditer(r"ER contact:? ([A-Z][a-z]+ [A-Z][a-z]+)", t):
                add_contact(m.group(1), "hr_payroll_contact", "rule_v1", r["Note ID"])
            for m in re.finditer(r"ER supervisor:? ([A-Z][a-z]+ [A-Z][a-z]+)", t):
                add_contact(m.group(1), "supervisor", "rule_v1", r["Note ID"])
            for m in re.finditer(r"From: ([A-Z][a-z]+ [A-Z][a-z]+) <[^@]+@" + re.escape(emp_dom) + r"\.example", t):
                add_contact(m.group(1), "hr_payroll_contact", "rule_v1", r["Note ID"])
            if r["Author Role"] == "ER supervisor":
                add_contact(r["Note Author"], "supervisor", "header_field", r["Note ID"])
        for name, node in emp_contacts.items():
            ctx.register(node, [name])
            ctx.entities[node] = name
        # attorneys
        attys = set(re.findall(r"([A-Z][a-z]+ [A-Z][a-z]+) is the worker's attorney", T))
        attys |= set(re.findall(r"\(atty for [^)]*\)", T) and re.findall(r"from ([A-Z][a-z]+ [A-Z][a-z]+) \(atty", T))
        for n, d in re.findall(r"From: ([A-Z][a-z]+ [A-Z][a-z]+) <[^@]+@(\w+law)\.example", T):
            attys.add(n)
        for n in sorted(attys):
            dom = attorney_firm.get(n, "")
            akey = "ATTY-" + slug(n) + ("-" + dom.split(".")[0] if dom else "")
            node = add_node("Attorney", akey, attorney_id=akey, name=n, firm_email_domain=dom, aliases=[n])
            first_src = next((r["Note ID"] for _, r in g.iterrows() if n in r["Synthetic Note Text"]), cid)
            add_edge("REPRESENTED_BY", ("Claim", cid), node, "note_text", first_src, "rule_v1", "unreviewed", cid)
            ctx.register(node, [n]); ctx.entities[node] = n
        # clinicians: treating physician from headers
        tfac = ctx.treating_facility
        for name in sorted(set(g.loc[g["Author Role"] == "treating provider", "Note Author"])):
            ckey = "CLIN-" + slug(name) + "-" + tfac[1].replace("FAC-", "")
            node = add_node("Clinician", ckey, clinician_id=ckey, name=name, clinician_type="treating_physician",
                            aliases=[name, name.replace("Dr ", "DR "), name.upper(), name.replace("Dr ", "Dr. ")])
            src = g.loc[g["Note Author"] == name, "Note ID"].iloc[0]
            add_edge("SEEN_BY", ("Claim", cid), node, "note_header", src, "header_field", "approved", cid,
                     dedupe_on=("role",), role="treating_physician")
            add_edge("PRACTICES_AT", node, tfac, "note_header", src, "header_field", "unreviewed", cid)
            ctx.treating_clinicians.add(node)
            ctx.register(node, NODES[node]["aliases"]); ctx.entities[node] = name
        # IME examiners
        imes = set()
        for m in re.finditer(r"IME (?:sched(?:uled)? [^.\n]{0,25}?)?with (Dr [A-Z][a-z]+)|\((Dr [A-Z][a-z]+)\)\. Purpose|(Dr [A-Z][a-z]+) saw \w+ and the report", T):
            imes.add(next(x for x in m.groups() if x))
        for m in re.finditer(r"Peer review rec'd [^(]*\((Dr [A-Z][a-z]+)\)", T):
            imes.add(m.group(1))
        for name in sorted(imes):
            ckey = "CLIN-" + slug(name) + "-ime"
            node = add_node("Clinician", ckey, clinician_id=ckey, name=name, clinician_type="ime_examiner",
                            aliases=[name, name.replace("Dr ", "DR ")])
            src = next((r["Note ID"] for _, r in g.iterrows() if name in r["Synthetic Note Text"] and "IME" in r["Synthetic Note Text"]), cid)
            add_edge("SEEN_BY", ("Claim", cid), node, "note_text", src, "rule_v1", "unreviewed", cid,
                     dedupe_on=("role",), role="ime_examiner")
            # IME doctor name may equal a treating doctor's surname on another claim: kept separate on purpose
            ctx.register(node, NODES[node]["aliases"]); ctx.entities[node] = name
        # physical therapists from headers; facility = PT clinic named in the same note, else most common on claim
        pt_fac_counts = Counter()
        for _, r in g.iterrows():
            for fid2, names in FAC_SEED.items():
                if NODES[("HealthcareFacility", fid2)]["facility_type"] == "physical_therapy":
                    if any(re.search(re.escape(n), r["Synthetic Note Text"], re.I) for n in names):
                        pt_fac_counts[fid2] += 1
        ctx.pt_facilities = pt_fac_counts
        for _, r in g[g["Author Role"] == "physical therapist"].iterrows():
            name = r["Note Author"]; t = r["Synthetic Note Text"]
            fac_here = [fid2 for fid2, names in FAC_SEED.items()
                        if NODES[("HealthcareFacility", fid2)]["facility_type"] == "physical_therapy"
                        and any(re.search(re.escape(n), t, re.I) for n in names)]
            pfac = fac_here[0] if fac_here else (pt_fac_counts.most_common(1)[0][0] if pt_fac_counts else None)
            if pfac is None:
                pfac_key = tfac
            else:
                pfac_key = ("HealthcareFacility", pfac)
            ckey = "CLIN-" + slug(name) + "-" + pfac_key[1].replace("FAC-", "")
            node = add_node("Clinician", ckey, clinician_id=ckey, name=name, clinician_type="physical_therapist", aliases=[name])
            add_edge("SEEN_BY", ("Claim", cid), node, "note_header", r["Note ID"], "header_field", "approved", cid,
                     dedupe_on=("role",), role="physical_therapist")
            add_edge("PRACTICES_AT", node, pfac_key, "note_header" if fac_here else "derived", r["Note ID"],
                     "header_field" if fac_here else "computed", "unreviewed", cid)
            ctx.register(node, [name]); ctx.entities[node] = name
        # staff on claim (headers)
        for _, r in g[g["Author Role"].isin(staff_roles)].iterrows():
            sid = "STAFF-" + slug(r["Note Author"])
            add_edge("HANDLED_BY", ("Claim", cid), ("ClaimsStaff", sid), "note_header", r["Note ID"], "header_field",
                     "approved", cid, dedupe_on=("role",), role=STAFF[sid]["role"])
        # claimant name misspellings (fuzzy, claim scope only)
        cname = NODES[ctx.claimant]["name"]; fn, ln = cname.split()[0], cname.split()[-1]
        known_words = {w.lower() for n in ctx.entities.values() for w in str(n).split()} | ALL_PERSON_WORDS
        variants = set()
        for w in set(re.findall(r"\b[A-Z][a-z]{3,}\b", T)):
            if w in (fn, ln) or w.lower() in known_words:
                continue
            for target in (fn, ln):
                if len(target) >= 4 and fuzzy_equal(w, target, 0.8) and w[0] == target[0]:
                    variants.add(w)
        if variants:
            NODES[ctx.claimant]["aliases"] = sorted(set(NODES[ctx.claimant]["aliases"]) | variants)
            ctx.register(ctx.claimant, sorted(variants), "fuzzy_match")
            LOG["fuzzy_alias"].append(f"Claim {cid}: claimant '{cname}' also written as {sorted(variants)}")
        # first name of claimant (very common in notes), unless a staff member on the same claim has that first name
        staff_first_on_claim = {STAFF["STAFF-" + slug(a)]["first"] for a in g.loc[g["Author Role"].isin(staff_roles), "Note Author"]}
        if fn in staff_first_on_claim:
            LOG["data_issue"].append(f"Claim {cid}: claimant first name '{fn}' is also the first name of claims staff on this claim; first-name mentions are not linked")
        else:
            ctx.register(ctx.claimant, [fn], "alias_match")

    # ---------------------------------------------------------- notes, chunks
    by_claim_notes = defaultdict(list)
    seen_text = defaultdict(dict)
    for _, r in df.iterrows():
        cid = str(r["Claim Identifier"]); ctx = claim_ctx[cid]
        t = r["Synthetic Note Text"]
        main_t, hist_t, hoff = split_history_paragraph(t)
        has_email = bool(re.search(r"^From: .+\n(?:Sent|To):", t, re.M))
        words = t.strip().split()
        last = words[-1].lower().strip(".,") if words else ""
        prev = words[-2].lower() if len(words) > 1 else ""
        last_line = t.strip().split("\n")[-1]
        signoff = has_email or len(last_line.split()) <= 2 and bool(re.search(r"\n\s*\n", t))
        truncated = bool(words) and not signoff and t.strip()[-1] not in ".!?)" and (
            last in {"a", "an", "the", "to", "for", "of", "if", "with", "and", "or", "says", "said", "is", "was", "that",
                     "about", "from", "at", "on", "in", "by", "wants", "will", "asked", "know", "new", "regular", "reggular"}
            or (prev in {"says", "wants", "asked", "told"} and last in {w.lower() for w in NODES[ctx.claimant]["name"].split()}))
        note = add_node("Note", r["Note ID"], note_id=r["Note ID"], claim_id=cid, note_date=str(r["Note Date"]),
                        note_type=r["Note Type"], author_name=r["Note Author"], author_role=r["Author Role"],
                        text=t, word_count=len(t.split()), has_copied_history=bool(hist_t), has_pasted_email=has_email,
                        looks_truncated=truncated)
        if truncated:
            LOG["truncated_note"].append(f"{r['Note ID']}: ends with '...{t.strip()[-40:]}'")
        add_edge("HAS_NOTE", ("Claim", cid), note, "note_header", r["Note ID"], "header_field", "approved", cid)
        # author
        role = r["Author Role"]
        if role in staff_roles:
            add_edge("WRITTEN_BY", note, ("ClaimsStaff", "STAFF-" + slug(r["Note Author"])), "note_header", r["Note ID"], "header_field", "approved", cid)
        elif role == "treating provider":
            add_edge("WRITTEN_BY", note, ("Clinician", "CLIN-" + slug(r["Note Author"]) + "-" + ctx.treating_facility[1].replace("FAC-", "")),
                     "note_header", r["Note ID"], "header_field", "approved", cid)
        elif role == "physical therapist":
            cands = [k for k in NODES if k[0] == "Clinician" and k[1].startswith("CLIN-" + slug(r["Note Author"]) + "-")
                     and any(e["type"] == "SEEN_BY" and e["from_key"] == cid and e["to_key"] == k[1] for e in EDGES.values())]
            if cands:
                add_edge("WRITTEN_BY", note, cands[0], "note_header", r["Note ID"], "header_field", "approved", cid)
        elif role == "ER supervisor":
            add_edge("WRITTEN_BY", note, ("EmployerContact", "ERC-" + slug(r["Note Author"]) + "-" + ctx.employer[1].replace("EMP-", "")),
                     "note_header", r["Note ID"], "header_field", "approved", cid)
        # pasted message author
        msg_from = None
        m = re.search(r"From: ([^<\n]+?) <([^@>]+)@([\w]+)\.example>", t)
        if m:
            sender, dom = m.group(1).strip(), m.group(3)
            if dom == "mail":
                msg_from = ctx.claimant
            elif dom.endswith("law"):
                msg_from = next((k for k in NODES if k[0] == "Attorney" and NODES[k]["name"] == sender), None)
            elif dom == "gbclaims":
                msg_from = ("ClaimsStaff", "STAFF-" + slug(sender)) if ("ClaimsStaff", "STAFF-" + slug(sender)) in NODES else None
            elif dom == NODES[ctx.employer]["email_domain"].split(".")[0]:
                msg_from = ("EmployerContact", "ERC-" + slug(sender) + "-" + ctx.employer[1].replace("EMP-", ""))
            else:
                fac_dom = [k for k in NODES if k[0] == "HealthcareFacility" and NODES[k].get("email_domain", "").split(".")[0] == dom]
                msg_from = fac_dom[0] if fac_dom else None
                if not msg_from:
                    LOG["unresolved_sender"].append(f"{r['Note ID']}: {sender} @{dom}")
            if msg_from and msg_from in NODES:
                add_edge("CONTAINS_MESSAGE_FROM", note, msg_from, "note_text", r["Note ID"], "rule_v1", "unreviewed", cid,
                         sender_display=sender, sent=clean_space(re.search(r"Sent: ([^\n]+)", t).group(1)) if re.search(r"Sent: ([^\n]+)", t) else "")
            # wrong claim number in a pasted email subject
            subj = re.search(r"Subject: RE: Claim (\d+)", t)
            if subj and subj.group(1) != cid:
                LOG["data_issue"].append(f"{r['Note ID']}: pasted email subject says claim {subj.group(1)}, note is filed on claim {cid}")
        elif r["Note Type"] == "Worker Message" or re.match(r"(?i)(portal msg|text msg|voicemail|email) (?:rec'd )?(?:[^:]*?)?(?:from|\()", t):
            add_edge("CONTAINS_MESSAGE_FROM", note, ctx.claimant, "note_text", r["Note ID"], "rule_v1", "unreviewed", cid,
                     sender_display=NODES[ctx.claimant]["name"], sent="")
        # duplicates
        key = normalize_name(t)
        if key in seen_text[cid] and len(key) > 10:
            add_edge("DUPLICATES", note, ("Note", seen_text[cid][key]), "derived", r["Note ID"], "computed", "approved", cid)
        else:
            seen_text[cid][key] = r["Note ID"]
        by_claim_notes[cid].append(r["Note ID"])
        # chunks
        make_chunks("Note", r["Note ID"], t, cid)

    for cid, ids in by_claim_notes.items():
        for a, b in zip(ids, ids[1:]):
            add_edge("NEXT_NOTE", ("Note", a), ("Note", b), "note_header", b, "header_field", "approved", cid)

    # ---------------------------------------------------------- events (pass 2)
    for (lab, key), nd in NODES.items():
        if lab in ("Claimant", "ClaimsStaff", "EmployerContact", "Clinician", "Attorney"):
            for w in re.findall(r"[A-Za-z]+", nd.get("name", "")):
                if len(w) > 2 and w.lower() not in ("the", "and", "of", "center", "health"):
                    PROPER_TOKENS.add(w.lower())
    PROPER_TOKENS.update(["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
                          "november", "december", "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "oct", "nov", "dec", "board"])
    for cid, ids in by_claim_notes.items():
        ctx = claim_ctx[cid]
        for note_id in ids:
            nd = NODES[("Note", note_id)]
            extract_events(ctx, nd, FORM_RX, TREAT_RX, STAFF_BY_FIRST, STAFF_BY_INIT)

    # corrections (note -> note) and superseded appointment events
    link_corrections(claim_ctx, by_claim_notes)

    # hearing evidence without outcome attaches to the hearing variants of the same date
    merge_unspecified_hearings()
    merge_yearless_dates()

    # write events into the graph
    INVOLVES_TARGETS = set(schema["relationship_types"]["INVOLVES"]["to"])
    for eid, ev in EVENTS.items():
        cid = ev["claim_id"]; ctx = claim_ctx[cid]
        prim = sum(1 for x in ev["evidence"] if x["kind"] == "primary")
        kinds = {x["kind"] for x in ev["evidence"]}
        support = "primary" if prim else ("summary_only" if "summary" in kinds else "restated_only")
        attrs_out, conflicting = {}, {}
        for k, vals in ev["attrs"].items():
            distinct = []
            for v, n in vals:
                if v not in distinct:
                    distinct.append(v)
            attrs_out[k] = distinct[0] if len(distinct) == 1 else distinct
            if len(distinct) > 1 and k in WITHIN_EVENT_SINGLE:
                conflicting[k] = [{"value": v, "notes": sorted({n for vv, n in vals if vv == v})} for v in distinct]
        if conflicting:
            attrs_out["_conflicting_values"] = conflicting
            LOG["within_event_conflict"].append(f"{eid} ({ev['event_type']}, claim {cid}): {json.dumps(conflicting)[:300]}")
        promoted = {}
        for k in PROMOTED:
            if k in attrs_out and attrs_out[k] not in ("", None, []):
                v = attrs_out[k]
                if isinstance(v, list):
                    v = [x for x in v if x not in ("", None)]
                    promoted[k] = (" | ".join(str(x) for x in v) if k not in NUMERIC_PROMOTED else v[0]) if v else None
                else:
                    promoted[k] = v
        evn = add_node("ClaimEvent", eid, event_id=eid, claim_id=cid, event_type=ev["event_type"],
                       has_conflicting_values=bool(conflicting), **{k: v for k, v in promoted.items() if v is not None},
                       event_category=ETYPE_CAT.get(ev["event_type"], ""), event_date=ev["event_date"] or "",
                       date_basis=ev["date_basis"] or "", summary=ev["summary"],
                       attributes_json=json.dumps(attrs_out, default=str), evidence_count=len(ev["evidence"]),
                       primary_evidence_count=prim, support=support)
        if ev["event_type"] not in ETYPE_CAT:
            LOG["schema_error"].append(f"Unknown event_type {ev['event_type']}")
        add_edge("HAS_EVENT", ("Claim", cid), evn, "note_text", ev["evidence"][0]["note_id"], "rule_v1", "unreviewed", cid)
        for x in ev["evidence"]:
            ch = chunk_for(x["note_id"], x["start"])
            add_edge("EVIDENCED_BY", evn, ("Note", x["note_id"]), "note_text", x["note_id"], "rule_v1", "unreviewed", cid,
                     dedupe_on=("char_start",), evidence_kind=x["kind"], quote=x["quote"], char_start=x["start"],
                     char_end=x["end"], chunk_id=ch)
        for (lab, key, role) in ev["participants"]:
            if lab == "Form":
                ev["forms"].add((key, "mentioned")); continue
            if lab not in INVOLVES_TARGETS:
                continue
            if (lab, key) in NODES:
                add_edge("INVOLVES", evn, (lab, key), "note_text", ev["evidence"][0]["note_id"], "rule_v1", "unreviewed", cid,
                         dedupe_on=("role",), role=role)
        for (code, action) in ev["forms"]:
            add_edge("REFERENCES_FORM", evn, ("Form", code), "note_text", ev["evidence"][0]["note_id"], "rule_v1", "unreviewed", cid,
                     dedupe_on=("action",), action=action)
        for t_ in ev["treatments"]:
            add_edge("INCLUDES_TREATMENT", evn, t_, "note_text", ev["evidence"][0]["note_id"], "rule_v1", "unreviewed", cid)
        for m_ in ev["meds"]:
            add_edge("RECORDS_MEDICATION", evn, m_, "note_text", ev["evidence"][0]["note_id"], "rule_v1", "unreviewed", cid)
        if ev["diagnosis"]:
            dkey = make_diagnosis(cid, ev["diagnosis"], ev["evidence"][0]["note_id"])
            add_edge("ABOUT_DIAGNOSIS", evn, dkey, "note_text", ev["evidence"][0]["note_id"], "rule_v1", "unreviewed", cid)
        for step in ETYPE_STEPS.get(ev["event_type"], []):
            if step_applies(ev, step):
                add_edge("INSTANCE_OF", evn, ("ProcessStep", step), "derived", "04_claim_event_types.csv", "curated", "draft", cid)

    # time order of events per claim
    per_claim = defaultdict(list)
    for eid, ev in EVENTS.items():
        first_note = NODES[("Note", ev["evidence"][0]["note_id"])]["note_date"]
        per_claim[ev["claim_id"]].append((ev["event_date"] or first_note, first_note, eid))
    for cid, lst in per_claim.items():
        lst.sort()
        for (_, _, a), (_, _, b) in zip(lst, lst[1:]):
            add_edge("NEXT_EVENT", ("ClaimEvent", a), ("ClaimEvent", b), "derived", "event_dates", "computed", "approved", cid)

    detect_conflicts()
    for cid, acc in CLAIM_RECORD_DOI.items():
        note_dois = sorted({ev["event_date"] for ev in EVENTS.values() if ev["claim_id"] == cid and ev["event_type"] == "injury_occurred"})
        if acc and note_dois and acc not in note_dois:
            LOG["data_issue"].append(f"Claim {cid}: public record accident date {acc} is not among the note dates of injury {note_dois}")

    # ---------------------------------------------------------- body parts and guideline map
    for r in bp_map.itertuples():
        bkey = add_node("BodyPart", "BP-specific-" + slug(r.specific_body_part), body_part_id="BP-specific-" + slug(r.specific_body_part),
                        name=r.specific_body_part, granularity="specific", wcio_code="")
        if r.doc_id:
            add_edge("COVERS_BODY_PART", ("Document", r.doc_id), bkey, "reference_seed",
                     f"02_body_part_to_treatment_guideline_map.csv:{r.specific_body_part}", "curated", "draft",
                     mapping_status=r.mapping_status, note=r.note)

    # ---------------------------------------------------------- mentions
    for k, nd in list(NODES.items()):
        if k[0] != "Chunk" or nd["parent_kind"] != "Note":
            continue
        cid = NODES[("Note", nd["parent_id"])]["claim_id"]
        ctx = claim_ctx[cid]
        for ent, s, e, txt, method in ctx.find(nd["text"]):
            if ent in NODES:
                add_edge("MENTIONS", k, ent, "note_text", nd["parent_id"], method, "unreviewed", cid,
                         dedupe_on=(), matched_text=txt, char_start=s)
        for rx, ent in TREAT_RX:
            mm = rx.search(nd["text"])
            if mm:
                add_edge("MENTIONS", k, ent, "note_text", nd["parent_id"], "alias_match", "unreviewed", cid, matched_text=mm.group(0))

    # facilities used on a claim (PT, imaging, pharmacy) from mentions in that claim's notes
    for e in list(EDGES.values()):
        if e["type"] == "MENTIONS" and e["to_label"] == "HealthcareFacility":
            ft = NODES[(e["to_label"], e["to_key"])]["facility_type"]
            if ft != "treating_clinic" or (e["to_label"], e["to_key"]) != claim_ctx[e["scope_claim_id"]].treating_facility:
                add_edge("TREATED_AT", ("Claim", e["scope_claim_id"]), (e["to_label"], e["to_key"]), "note_text",
                         sorted(e["source_ids"])[0], "alias_match", "unreviewed", e["scope_claim_id"], dedupe_on=("service",), service=ft)
    for (cid, txt), ents in sorted(AMBIGUOUS.items()):
        LOG["ambiguous_mention"].append(f"Claim {cid}: '{txt}' could be {ents}; not linked")

    # ---------------------------------------------------------- reference document chunks (only if downloaded)
    for k, nd in list(NODES.items()):
        if k[0] == "Document" and nd.get("downloaded"):
            text = read_reference_text(os.path.join(args.reference_docs, nd["local_file"]))
            if text:
                make_chunks("Document", k[1], text, "")
            else:
                LOG["info"].append(f"{k[1]}: file present but no text extracted")

    # ---------------------------------------------------------- validate and write
    errors = validate(schema)
    write_outputs(args.out, schema, errors, df)
    print(f"nodes={len(NODES)} relationships={len(EDGES)} schema_errors={len(errors)} events={len(EVENTS)}")
    if errors:
        print("\n".join(errors[:30]))
        sys.exit(1)


# ============================================================== chunking
CHUNK_INDEX = defaultdict(list)   # parent_id -> [(start,end,chunk_id)]


def make_chunks(kind, parent_id, text, cid):
    paras, pos = [], 0
    for m in re.finditer(r"[^\n]+(?:\n(?!\n)[^\n]*)*", text):
        paras.append((m.start(), m.end()))
    if not paras:
        paras = [(0, len(text))]
    chunks, cur_s, cur_e, words = [], None, None, 0
    for s, e in paras:
        w = len(text[s:e].split())
        if cur_s is None:
            cur_s, cur_e, words = s, e, w
        elif words + w <= CHUNK_MAX_WORDS:
            cur_e, words = e, words + w
        else:
            chunks.append((cur_s, cur_e)); cur_s, cur_e, words = s, e, w
    if cur_s is not None:
        chunks.append((cur_s, cur_e))
    # split any paragraph that alone exceeds the limit (long reference documents)
    final = []
    for s, e in chunks:
        toks = list(re.finditer(r"\S+", text[s:e]))
        if len(toks) <= CHUNK_MAX_WORDS * 1.5:
            final.append((s, e)); continue
        for i in range(0, len(toks), CHUNK_MAX_WORDS):
            part = toks[i:i + CHUNK_MAX_WORDS]
            final.append((s + part[0].start(), s + part[-1].end()))
    prev = None
    for i, (s, e) in enumerate(final, 1):
        ch_id = f"{parent_id}-C{i:02d}"
        ck = add_node("Chunk", ch_id, chunk_id=ch_id, parent_id=parent_id, parent_kind=kind, position=i,
                      text=text[s:e], char_start=s, char_end=e, word_count=len(text[s:e].split()))
        add_edge("HAS_CHUNK", (kind, parent_id), ck, "derived", parent_id, "computed", "approved", cid)
        if prev:
            add_edge("NEXT_CHUNK", prev, ck, "derived", parent_id, "computed", "approved", cid)
        prev = ck
        CHUNK_INDEX[parent_id].append((s, e, ch_id))


def chunk_for(parent_id, pos):
    for s, e, cid in CHUNK_INDEX[parent_id]:
        if s <= pos < e or pos < s:
            return cid
    return CHUNK_INDEX[parent_id][-1][2] if CHUNK_INDEX[parent_id] else ""


def read_reference_text(path):
    if not os.path.exists(path):
        return ""
    if path.lower().endswith(".pdf"):
        import subprocess
        try:
            return subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, text=True, timeout=120).stdout
        except Exception:
            try:
                from pypdf import PdfReader
                return "\n".join(p.extract_text() or "" for p in PdfReader(path).pages)
            except Exception:
                return ""
    raw = open(path, encoding="utf-8", errors="ignore").read()
    raw = re.sub(r"(?is)<(script|style|nav|header|footer)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", "\n", raw)
    import html
    raw = html.unescape(raw)
    return re.sub(r"\n\s*\n+", "\n\n", raw).strip()


# ============================================================== diagnosis
BODY_WORDS = [("low back", "low back"), ("lumbar", "low back"), ("back", "back"), ("neck", "neck"), ("shoulder", "shoulder"),
              ("upper arm", "upper arm"), ("uppper arm", "upper arm"), ("forearm", "forearm"), ("wrist", "wrist"), ("hand", "hand"),
              ("hip", "hip"), ("buttock", "buttock"), ("knee", "knee"), ("lower leg", "lower leg"), ("lowr leg", "lower leg"),
              ("ear", "ear"), ("ears", "ear")]


BODY_VOCAB = ["shoulder", "shoulders", "forearm", "knee", "knees", "neck", "back", "wrist", "wrists", "hand", "hip", "buttock",
              "upper", "lower", "leg", "arm", "ears", "ear", "low"]


def fix_body_typos(text):
    from difflib import get_close_matches
    out = []
    for w in text.split():
        core = w.strip(",/")
        if core.isalpha() and core not in BODY_VOCAB and len(core) > 3:
            c = get_close_matches(core, BODY_VOCAB, n=1, cutoff=0.85)
            if c:
                w = w.replace(core, c[0])
        out.append(w)
    return " ".join(out)


def make_diagnosis(cid, dx_text, src_note):
    """One Diagnosis node per claim and condition. Side (left/right/both) is NOT part of the key:
    it is stored on the DIAGNOSIS_AFFECTS edge, so a note that omits the side, or a note that states
    the wrong side, attaches to the same diagnosis and the disagreement stays visible."""
    dx = clean_space(dx_text.lower())
    dx = re.sub(r"\b(rt)\b", "right", dx); dx = re.sub(r"\b(lt)\b", "left", dx)
    dx = re.sub(r"\bheaing\b", "hearing", dx)
    dx = fix_body_typos(dx)
    dx = re.sub(r"\bof (?!the)", "of the ", dx)
    no_side = clean_space(re.sub(r"\b(right|left)\s+", "", dx))
    cond = dx.split(" of ")[0].strip()
    dkey = f"DX-{cid}-{slug(no_side)[:60]}"
    existing = NODES.get(("Diagnosis", dkey), {}).get("text", "")
    node = add_node("Diagnosis", dkey, diagnosis_id=dkey, text=dx, condition=cond)
    if len(dx) > len(existing) and existing:
        NODES[node]["text"] = dx
    add_edge("HAS_DIAGNOSIS", ("Claim", cid), node, "note_text", src_note, "rule_v1", "unreviewed", cid)
    body = dx.split(" of ", 1)[1] if " of " in dx else dx
    taken = []
    for w, bp in BODY_WORDS:
        for m in re.finditer(r"\b" + w + r"s?\b", body):
            if any(m.start() < e and m.end() > s for s, e in taken):
                continue
            taken.append(m.span())
            pre = body[max(0, m.start() - 12):m.start()]
            lat = "both" if "both" in pre or m.group(0).endswith("s") and bp in ("knee", "shoulder", "wrist", "ear") else \
                  "right" if "right" in pre else "left" if "left" in pre else "not stated"
            if bp == "back" and "low back" in body:
                continue
            bkey = add_node("BodyPart", "BP-specific-" + slug(bp), body_part_id="BP-specific-" + slug(bp), name=bp,
                            granularity="specific", wcio_code="")
            add_edge("DIAGNOSIS_AFFECTS", node, bkey, "note_text", src_note, "rule_v1", "unreviewed", cid,
                     dedupe_on=("laterality",), laterality=lat)
    return node


# ============================================================== event extraction rules
PROMOTED = ["decision", "outcome", "reason", "service", "amount", "work_status", "restrictions", "examiner", "finding",
            "result_text", "average_weekly_wage", "weekly_rate", "pain_score"]
NUMERIC_PROMOTED = {"amount", "average_weekly_wage", "weekly_rate", "pain_score"}
WITHIN_EVENT_SINGLE = {"adjournment_reason", "finding", "result_text", "average_weekly_wage", "decision", "examiner"}
PARTY_WORDS = {
    "claimant": r"\b(clmt|cx|EE|IW|pt|claimant)\b",
}


SERVICES = ["PT visits", "office visit", "xray", "MRI", "ortho consult", "Rx", "audiogram", "IME"]


def canonical_service(raw):
    w = clean_space(raw).split()
    for n in range(min(3, len(w)), 0, -1):
        cand = " ".join(w[-n:])
        for svc in SERVICES:
            if cand.lower() == svc.lower() or fuzzy_equal(cand, svc, 0.8):
                return svc
    return clean_space(raw)


def has_provider_email(t, ctx):
    m = re.search(r"From: [^<\n]+<[^@]+@(\w+)\.example>", t)
    if not m:
        return False
    return any(NODES[k].get("email_domain", "").split(".")[0] == m.group(1) for k in NODES if k[0] == "HealthcareFacility")


def kind_for(nd, in_history):
    if in_history:
        return "restated"
    if nd["note_type"] in ("File Review", "Status Report"):
        return "summary"
    return "primary"


def extract_events(ctx, nd, FORM_RX, TREAT_RX, STAFF_BY_FIRST, STAFF_BY_INIT):
    t = rule_text(nd["text"]); ntype = nd["note_type"]; ndate = to_date(nd["note_date"]); nid_ = nd["note_id"]
    cid = ctx.claim_id
    main_t, hist_t, hoff = split_history_paragraph(t)
    hoff = hoff or len(t)
    # status reports: the CLAIM HISTORY block is restated; other blocks are the report's own summary
    if ntype == "Status Report":
        hm = re.search(r"CLAIM HISTORY\n(.*?)\n\n", t, re.S)
        segments = [(0, len(t), "summary")]
        if hm:
            segments = [(0, hm.start(1), "summary"), (hm.start(1), hm.end(1), "restated"), (hm.end(1), len(t), "summary")]
    else:
        segments = [(0, hoff, kind_for(nd, False))] + ([(hoff, len(t), "restated")] if hoff < len(t) else [])
    clin = sorted(ctx.treating_clinicians)
    tfac = ctx.treating_facility
    clmt = ctx.claimant

    def ev(etype, extra, date, basis, span, kind, **kw):
        return record_event(ctx, etype, extra, date, basis, nd, kind, span, **kw)

    def mentions_in(span):
        s, e = span
        return [(ent[0], ent[1], "mentioned") for ent, a, b, _, _ in ctx.find(t[s:e])]

    def treats_meds(span):
        s, e = span
        tr, md = set(), set()
        for rx, ent in TREAT_RX:
            if rx.search(t[s:e]):
                (tr if ent[0] == "Treatment" else md).add(ent)
        return tr, md

    def forms_in(span, default_action):
        s, e = span
        out = set()
        for m in FORM_RX.finditer(t[s:e]):
            code = "RFA-1" if m.group(1).startswith("RFA-1") else m.group(1)
            ctxt = t[max(s, s + m.start() - 40): s + m.end() + 25].lower()
            action = ("received" if "rec'd" in ctxt or "received" in ctxt or "attached" in ctxt else
                      "sent" if "sent" in ctxt or "mail" in ctxt else
                      "requested" if any(w in ctxt for w in ("need", "requesting", "wants", "copy of", "copies")) else
                      "filed" if "filed" in ctxt else
                      "pending" if "to follow" in ctxt or "not yet" in ctxt else default_action)
            out.add((code, action))
        return out

    def dates(text, prefer):
        return parse_dates_in_text(text, ndate, prefer)

    for (seg_s, seg_e, kind) in segments:
        seg = t[seg_s:seg_e]

        def span_of(m, pad_to_sentence=True):
            s, e = seg_s + m.start(), seg_s + m.end()
            if pad_to_sentence:
                while s > seg_s and t[s - 1] not in ".\n":
                    s -= 1
                while e < seg_e and t[e] not in ".\n":
                    e += 1
            return (s, min(e + 1, seg_e))

        # ---------------- injury occurred (DOI + mechanism)
        for m in re.finditer(r"\bDOI:?\s+([^,.\n]+?)(,| at )\s*(?:(?:cx|clmt|IW|EE|[A-Z][a-z]+)(?: [A-Z][a-z]+)?\s+(?:says (?:he|she) |states (?:he|she) )?)?([^.\n]*)", seg):
            d = parse_dates_in_text(m.group(1), ctx.first_note_date, "past")
            if not d:
                continue
            mech = clean_space(m.group(3)) if m.group(2) == "," else ""
            mech = mech if len(mech.split()) >= 3 and re.search(r"\b(was|has|had|got|slipped|tripped|backed|felt|missed|struck|hit|caught|moving|repositioning|grabbed|fell)\b", mech) else ""
            sp = span_of(m)
            ev("injury_occurred", (d[0][0],), d[0][0], "stated", sp, kind,
               attrs={"date_of_injury": d[0][0], "mechanism": mech, "date_written_as": m.group(1).strip(), "year_written": d[0][4]},
               participants=[(clmt[0], clmt[1], "injured_worker")], summary=f"Injury on {d[0][0]}")
        for m in re.finditer(r"(?:confirmed|Chloe confirmed|Cx confirmed|clmt confirmed|\w+ confirmed) DOI ([^,.\n]+?) at ", seg):
            d = parse_dates_in_text(m.group(1), ctx.first_note_date, "past")
            if d:
                ev("injury_occurred", (d[0][0],), d[0][0], "stated", span_of(m), kind,
                   attrs={"date_of_injury": d[0][0], "date_written_as": m.group(1).strip(), "year_written": d[0][4]},
                   participants=[(clmt[0], clmt[1], "injured_worker")], summary=f"Injury on {d[0][0]}")
        for m in re.finditer(r"I was on shift ([^.\n]+?)\.", seg):
            d = parse_dates_in_text(m.group(1), ctx.first_note_date, "past")
            if d and ntype == "Supervisor Incident Statement":
                ev("injury_occurred", (d[0][0],), d[0][0], "stated", span_of(m), kind,
                   attrs={"date_of_injury": d[0][0], "date_written_as": m.group(1).strip()},
                   participants=[(clmt[0], clmt[1], "injured_worker")], summary=f"Injury on {d[0][0]}")

        # ---------------- reported to employer / employer to carrier
        for m in re.finditer(r"(?:[Rr]eported to|told) ([A-Z][a-z]+ [A-Z][a-z]+) (same day|right away|before the end of the shift)", seg):
            parts = [(clmt[0], clmt[1], "reporter")] + [(e[0], e[1], "reported_to") for e in ctx.find(m.group(1))]
            ev("injury_reported_to_employer", (m.group(1),), None, "", span_of(m), kind,
               attrs={"reported_to": m.group(1), "report_timing": m.group(2)}, participants=parts,
               summary=f"Worker reported injury to {m.group(1)} {m.group(2)}")
        for m in re.finditer(r"[Ee]mployer reported it to ([A-Za-z .]+?) on ([^.\n]+)", seg):
            d = dates(m.group(2), "past")
            if d:
                ev("employer_reported_to_carrier", (d[0][0],), d[0][0], "stated", span_of(m), kind,
                   attrs={"report_date": d[0][0]}, participants=[(ctx.employer[0], ctx.employer[1], "reporter"), (ctx.carrier[0], ctx.carrier[1], "recipient")],
                   summary=f"Employer reported to carrier on {d[0][0]}")
        for m in re.finditer(r"(?:company|employer|ER) sent (?:the )?C-2F,? rec'd ([^.\n]+)", seg, re.I):
            d = dates(m.group(1), "past")
            ev("employer_reported_to_carrier", (d[0][0] if d else nid_,), d[0][0] if d else None, "stated" if d else "", span_of(m), kind,
               attrs={"report_date": d[0][0] if d else ""}, forms=[("C-2F", "received")],
               participants=[(ctx.employer[0], ctx.employer[1], "reporter")], summary="Form C-2F received from employer")

        # ---------------- intake
        if ntype == "First Report Summary" and seg_s == 0:
            ev("first_report_received", (nid_,), str(ndate), "note_date", (0, min(len(t), hoff)), kind,
               participants=mentions_in((0, min(len(t), hoff))), summary="First report / new assignment summary")
        if ntype == "Prior Claims Check" and seg_s == 0:
            res = "no prior claims found" if re.search(r"no hits|nthing|nothing|no prior", t, re.I) else clean_space(t)[:80]
            ev("prior_claims_check", (nid_,), str(ndate), "note_date", (0, len(t)), kind, attrs={"result": res}, summary=f"Prior claims check: {res}")
        if ntype == "Statement / Investigation" and seg_s == 0:
            ev("claimant_statement_taken", (str(ndate),), str(ndate), "note_date", (0, min(len(t), hoff)), kind,
               participants=[(clmt[0], clmt[1], "statement_giver")], summary="Recorded statement from the worker")
        if ntype == "Supervisor Incident Statement" and seg_s == 0:
            wit = "no witness" if re.search(r"did not see|no witness", t, re.I) else ""
            parts = [(k[0], k[1], "statement_giver") for k in ctx.entities if k[0] == "EmployerContact" and NODES[k]["name"] == nd["author_name"]]
            ev("supervisor_statement_taken", (str(ndate),), str(ndate), "note_date", (0, min(len(t), hoff)), kind,
               attrs={"witness": wit}, participants=parts, summary=f"Supervisor statement from {nd['author_name']}")
        for m in re.finditer(r"(?:Compensability|Decision on claim \d+|compensability|decision on claim \d+)[^:\n]*?:?\s*(Accepting as work related|Disputing for now|accepting as work related|disputing for now)([^.\n]*)", seg, re.I):
            dec = "accepted" if "accept" in m.group(1).lower() else "disputed"
            reason = clean_space(m.group(2))
            lt = "lost time over 7 days" if re.search(r"lost time over 7 days", t, re.I) else ("no lost time" if re.search(r"no lost time", t, re.I) else "")
            ev("compensability_decision", (dec,), str(ndate), "note_date", span_of(m), kind,
               attrs={"decision": dec, "reason": reason, "lost_time_status": lt, "late_notice": "notice issue" in t.lower()},
               forms=forms_in(span_of(m), "sent"), summary=f"Claim {dec}")

        # ---------------- medical visits (treating doctor notes)
        if ntype == "Medical Update" and seg_s == 0:
            m = re.search(r"(?:OFFICE NOTE|progress|f/u|Dr note rec'd|visit)\s*([^:(\n]*)", t, re.I)
            d = dates(t[:80], "past")
            vdate = d[0][0] if d else str(ndate)
            pain = re.search(r"[Pp]ain:? (\d{1,2})/10", t)
            assess = re.search(r"ASSESSMENT: ([^.\n]+)", t)
            ws = re.search(r"[Ww]ork st\w*: ([^.\n]+)", t)
            rs = re.search(r"[Rr]estr(?:ictions)?:? ([^.\n]+)", t)
            nxt = re.search(r"(?:f/u|F/u|RTC|[Nn]ext visit)\.? ?(?:in )?([^.\n]+)", t)
            nxt_d = dates(nxt.group(1), "future") if nxt else []
            findings = re.findall(r"((?:[Ll]umbar |[Kk]nee |[Ww]rist |[Hh]and )?[Xx]ray [^.\n]+|MRI: [^.\n]+|Audiogram [^.\n]+|OBJECTIVE: [^\n]+|Exam: [^\n]+)", t)
            tr, md = treats_meds((0, len(t)))
            parts = [(c[0], c[1], "treating_physician") for c in clin if NODES[c]["name"] == nd["author_name"]] + [(tfac[0], tfac[1], "treating_clinic")]
            dxm = re.search(r"ASSESSMENT: ([a-z ]+? of the [^,.\n]+(?:, [^,.\n]+)*?)(?:,? (?:no change|improving|worse|resolved))", t)
            ev("medical_visit", (vdate,), vdate, "stated" if d else "note_date", (0, len(t)), kind,
               attrs={"pain_score": int(pain.group(1)) if pain else None, "assessment": clean_space(assess.group(1)) if assess else "",
                      "work_status": clean_space(ws.group(1)) if ws else "", "restrictions": clean_space(rs.group(1)) if rs else "",
                      "findings": "; ".join(clean_space(f) for f in findings)[:300], "next_appointment": nxt_d[0][0] if nxt_d else ""},
               participants=parts, treatments=tr, meds=md, forms=forms_in((0, len(t)), "pending"),
               diagnosis=dxm.group(1) if dxm else None, summary=f"Visit with {nd['author_name']} on {vdate}")
            if nxt_d:
                ev("appointment_scheduled", (nxt_d[0][0],), nxt_d[0][0], "stated", span_of(nxt), kind,
                   attrs={"appointment_date": nxt_d[0][0]}, participants=parts, summary=f"Next appointment {nxt_d[0][0]}")
        # restated "First seen at X on D, dx Y" -> first medical visit + diagnosis
        for m in re.finditer(r"[Ff]irst seen at ([^\n]+?) on ([^,\n]+), dx ([^\n]+?)(?:,? ((?:[\w]+ )?xray[^.\n]*|audiogram[^.\n]*|MRI[^.\n]*))?(?:\.|\n|$)", seg):
            d = dates(m.group(2), "past")
            if not d:
                continue
            ev("medical_visit", (d[0][0],), d[0][0], "stated", span_of(m), kind,
               attrs={"visit_kind": "first visit", "findings": clean_space(m.group(4) or "")},
               participants=[(tfac[0], tfac[1], "treating_clinic")] + [(c[0], c[1], "treating_physician") for c in clin],
               diagnosis=m.group(3), summary=f"First visit on {d[0][0]}")
        for m in re.finditer(r"\bdx (?:per first visit: )?([^.\n]+)", seg, re.I):
            dx = re.split(r",? (?:(?:lumbar |knee |wrist |hand )?xray|audiogram|MRI)\b", m.group(1))[0]
            if " of " in dx:
                make_diagnosis(cid, dx, nid_)

        # ---------------- therapy visits
        if ntype == "Therapy Update" and seg_s == 0:
            vm = re.search(r"(?:[Vv]isit|session #?)\s*(\d+)\s*(?:of|/)\s*(\d+)", t) or re.search(r"session #(\d+)()", t)
            pre = re.search(r"[Pp]ain (\d{1,2})/10 pre-tx,? (\d{1,2})/10 after", t)
            att = "late" if re.search(r"arrived late", t) else ("early" if re.search(r"arrived early", t) else "")
            d = dates(t[:60], "past")
            vdate = d[0][0] if d else str(ndate)
            tr, md = treats_meds((0, len(t)))
            tr.add(("Treatment", "physical-therapy"))
            therapist = [k for k in ctx.entities if k[0] == "Clinician" and NODES[k]["name"] == nd["author_name"]]
            pfac = [k for k in ctx.entities if False]
            for fid2 in ctx.pt_facilities:
                if re.search(re.escape(NODES[("HealthcareFacility", fid2)]["name"].split()[0]), t):
                    pfac.append(("HealthcareFacility", fid2))
            parts = [(k[0], k[1], "physical_therapist") for k in therapist] + [(k[0], k[1], "physical_therapy_clinic") for k in pfac]
            ev("therapy_visit", (nid_,), vdate, "stated" if d else "note_date", (0, len(t)), kind,
               attrs={"visit_number": int(vm.group(1)) if vm and vm.group(1) else None,
                      "visits_planned": int(vm.group(2)) if vm and vm.group(2) else None,
                      "pain_before": int(pre.group(1)) if pre else None, "pain_after": int(pre.group(2)) if pre else None,
                      "attendance": att},
               participants=parts, treatments=tr, meds=md, summary="Physical therapy visit")

        # ---------------- imaging
        for m in re.finditer(r"(MRI|[Xx]ray|CT) (?:ordered|auth'd)(?: ([^,.\n]+?))?(?:,|\.| result|$)", seg):
            d = dates(m.group(2) or "", "past") if m.group(2) else []
            fac_parts = [(e[0], e[1], "imaging_facility") for e in ctx.find(t[seg_s + m.start(): seg_s + m.end() + 60]) if e[0][0] == "HealthcareFacility"]
            ev("imaging_ordered", (m.group(1).upper(), d[0][0] if d else str(ndate)), d[0][0] if d else str(ndate),
               "stated" if d else "note_date", span_of(m), kind, attrs={"modality": m.group(1).upper()}, participants=fac_parts,
               summary=f"{m.group(1).upper()} ordered")
        for m in re.finditer(r"(MRI|[Xx]ray|CT)(?: ordered [^,]+)?, result ([^:\n]+): ([^.\n]+)", seg):
            d = dates(m.group(2), "past")
            if d:
                ev("imaging_result", (m.group(1).upper(), d[0][0]), d[0][0], "stated", span_of(m), kind,
                   attrs={"modality": m.group(1).upper(), "result_text": clean_space(m.group(3)).lower()},
                   summary=f"{m.group(1).upper()} result: {clean_space(m.group(3))}")

        if ntype == "Imaging Result" and seg_s == 0:
            for m in re.finditer(r"(?:(lumbar|knee|wrist|hand|shoulder) )?(xray|x-ray|MRI|audiogram|CT)\s*:?\s*(neg(?:ative)?(?: for fracture)?|no acute findings|mild [^.\n]+|shows [^.\n]+|possible [^.\n]+)", t, re.I):
                mod = m.group(2).upper().replace("X-RAY", "XRAY")
                fac = [(e[0], e[1], "imaging_facility") for e in ctx.find(t) if e[0][0] == "HealthcareFacility"][:1]
                ev("imaging_result", (mod, str(ndate)), str(ndate), "note_date", span_of(m, False), kind,
                   attrs={"modality": mod, "result_text": clean_space(m.group(3)).lower(), "body_region": (m.group(1) or "").lower()},
                   participants=fac, summary=f"{mod} result: {clean_space(m.group(3))}")
        # ---------------- nurse case manager
        if ntype == "Nurse Case Manager Note" and seg_s == 0:
            pain = re.search(r"[Pp]ain (\d{1,2})/10", t)
            bar = re.search(r"Barrier to RTW: ([^.\n]+)", t)
            rs = re.search(r"[Rr]eviewed restrictions: ([^.\n]+)", t)
            nurse = [("ClaimsStaff", "STAFF-" + slug(nd["author_name"]), "nurse_case_manager")]
            ev("nurse_case_review", (nid_,), str(ndate), "note_date", (0, min(len(t), hoff)), kind,
               attrs={"pain_score": int(pain.group(1)) if pain else None, "barrier_to_return_to_work": clean_space(bar.group(1)) if bar else "",
                      "restrictions": clean_space(rs.group(1)) if rs else ""},
               participants=nurse + [(tfac[0], tfac[1], "mentioned")] if tfac[1] and NODES[tfac]["name"].split()[0] in t else nurse,
               summary="Nurse case manager review")

        # ---------------- appointments
        for m in re.finditer(r"(?:[Nn]ext appt|appt) (?:with (?:Dr [A-Z][a-z]+|the Dr) )?is ([0-9/A-Za-z ]+?)(?:[.,\n]|$)|next appt ([0-9/]+)|f/u appt ([0-9/]+)|office says next appt ([0-9/A-Za-z ]+?)(?:[.,\n]|$)|appt got moved to ([0-9/]+)", seg):
            raw = next(x for x in m.groups() if x)
            d = dates(raw, "future")
            if d and ntype != "Correction":
                ev("appointment_scheduled", (d[0][0],), d[0][0], "stated", span_of(m, False), kind,
                   attrs={"appointment_date": d[0][0]}, summary=f"Appointment {d[0][0]}")
        if re.search(r"no ?showed (?:the )?last appt", seg):
            m = re.search(r"no ?showed (?:the )?last appt", seg)
            fac_parts = [(e[0], e[1], "facility") for e in ctx.find(seg) if e[0][0] == "HealthcareFacility"][:1]
            ev("missed_appointment", (nid_,), str(ndate), "note_date", span_of(m), kind, participants=fac_parts,
               summary="Worker missed an appointment")

        # ---------------- authorization
        for m in re.finditer(r"(?:[Ww]e are requesting|requesting) (\d+) (PT visits?)", seg):
            requester = [(e[0], e[1], "requester") for e in ctx.find(t) if e[0][0] in ("HealthcareFacility",)][:1]
            ev("authorization_request", ("PT visits", int(m.group(1)), str(ndate)), str(ndate), "note_date", span_of(m), kind,
               attrs={"service": "PT visits", "quantity": int(m.group(1))}, participants=requester,
               treatments=[("Treatment", "physical-therapy")], summary=f"Request for {m.group(1)} PT visits")
        for m in re.finditer(r"[Pp]lease confirm authorization for the ([a-z \-]+?)\.", seg):
            requester = [(e[0], e[1], "requester") for e in ctx.find(t) if e[0][0] == "HealthcareFacility"][:1]
            ev("authorization_request", (m.group(1), "", str(ndate)), str(ndate), "note_date", span_of(m), kind,
               attrs={"service": m.group(1)}, participants=requester, summary=f"Provider asks to confirm authorization for {m.group(1)}")
        for m in re.finditer(r"[Ww]e request authorization for the treatment recommended by (Dr [A-Z][a-z]+)", seg):
            atty = [(e[0], e[1], "requester") for e in ctx.find(t) if e[0][0] == "Attorney"][:1]
            ev("authorization_request", ("treatment recommended by " + m.group(1), "", str(ndate)), str(ndate), "note_date", span_of(m), kind,
               attrs={"service": "treatment recommended by " + m.group(1)}, participants=atty, summary="Attorney requests treatment authorization")
        for m in re.finditer(r"(?i:approved|auth'd) (\d+ )?(PT vi+sits|MRI|xray|ortho consult)(?: at ([^,.\n]+?))?(?:,? auth # (\d+))?(?=[,.\n]|$)", seg):
            fac_parts = [(e[0], e[1], "authorized_provider") for e in ctx.find(m.group(3) or "")] if m.group(3) else []
            ev("authorization_decision", (nid_, m.group(2)), str(ndate), "note_date", span_of(m), kind,
               attrs={"service": re.sub("vi+sits", "visits", m.group(2)), "quantity": int(m.group(1)) if m.group(1) else None, "decision": "approved",
                      "auth_number": m.group(4) or ""}, participants=fac_parts,
               treatments=[("Treatment", "physical-therapy")] if "PT" in m.group(2) else [], summary=f"Approved {m.group(0)[:40]}")
        for m in re.finditer(r"(Dr [A-Z][a-z]+) requested more PT,? we are checking agai\w+ (?:the )?guideline", seg):
            doc = [(c[0], c[1], "requester") for c in clin if NODES[c]["name"] == m.group(1)]
            ev("authorization_request", ("more PT", m.group(1), str(ndate)), str(ndate), "note_date", span_of(m, False), kind,
               attrs={"service": "additional PT", "requested_by": m.group(1), "review": "checking against the treatment guideline"},
               participants=doc, treatments=[("Treatment", "physical-therapy")], summary=f"{m.group(1)} requested more PT")
        for m in re.finditer(r"(?:[Dd]enied|[Dd]enying) the (extra visits|added PT|PT visits|[a-z ]+?),? (not medically necessary[^,.\n]*)", seg):
            ev("authorization_decision", (nid_, m.group(1)), str(ndate), "note_date", span_of(m, False), kind,
               attrs={"service": m.group(1), "decision": "denied", "reason": clean_space(m.group(2))},
               participants=[(c[0], c[1], "informed") for c in clin if NODES[c]["name"].split()[-1] in t], summary=f"Denied {m.group(1)}")
        for m in re.finditer(r"Attached is the note from [^.\n]*?vi\w*t on ([^.\n]+)", seg):
            d = dates(m.group(1), "past")
            if d:
                ev("medical_visit", (d[0][0],), d[0][0], "stated", span_of(m, False), kind, attrs={"visit_kind": "office note sent by provider"},
                   participants=[(tfac[0], tfac[1], "treating_clinic")], summary=f"Visit on {d[0][0]}")
        for m in re.finditer(r"Next visit is scheduled for ([^.\n]+)", seg):
            d = dates(m.group(1), "future")
            if d:
                ev("appointment_scheduled", (d[0][0],), d[0][0], "stated", span_of(m, False), kind, attrs={"appointment_date": d[0][0], "source": "provider office"},
                   participants=[(tfac[0], tfac[1], "treating_clinic")], summary=f"Appointment {d[0][0]}")
        if has_provider_email(t, ctx):
            for m in re.finditer(r"Restrictions remain: ([^.\n]+)|Work status: ([^.\n]+)", seg):
                ev("work_status_update", (nid_, "provider_email"), str(ndate), "note_date", span_of(m, False), kind,
                   attrs={"restrictions": clean_space(m.group(1) or ""), "work_status": clean_space(m.group(2) or "").lower(), "source": "provider office email"},
                   participants=[(tfac[0], tfac[1], "reporting_provider")], summary="Provider office reports work status")
            for m in re.finditer(r"is being seen for ([^.\n]+)", seg):
                if " of " in m.group(1):
                    make_diagnosis(cid, m.group(1), nid_)
        for m in re.finditer(r"auth # (\d+) for ([a-z ]+)", seg):
            ev("authorization_decision", (nid_, m.group(2)), str(ndate), "note_date", span_of(m), kind,
               attrs={"service": m.group(2).strip(), "decision": "approved", "auth_number": m.group(1)}, summary=f"Auth {m.group(1)} for {m.group(2)}")
        for m in re.finditer(r"(MG-2) rec'd for ([^,]+?), reviewing", seg):
            ev("authorization_request", ("MG-2 variance", m.group(2), str(ndate)), str(ndate), "note_date", span_of(m), kind,
               attrs={"service": "variance (MG-2) for " + m.group(2), "decision": "reviewing"}, forms=[("MG-2", "received")],
               summary="Variance request (MG-2) received")
        for m in re.finditer(r"(RFA-1\w*) filed by ([A-Z][a-z]+ [A-Z][a-z]+)", seg):
            atty = [(e[0], e[1], "filer") for e in ctx.find(m.group(2)) if e[0][0] == "Attorney"]
            ev("form_activity", ("RFA-1", "filed", nid_), str(ndate), "note_date", span_of(m), kind,
               attrs={"form_code": "RFA-1", "action": "filed"}, forms=[("RFA-1", "filed")], participants=atty,
               summary="RFA-1 filed by claimant attorney")

        # ---------------- bills
        for m in re.finditer(r"(?:[Oo]ur billing for|sent a bill for) \$([\d,.]+)(?: was sent on ([^,]+?), please \w+ receipt|, forwarded to bill review)", seg):
            d = dates(m.group(2) or "", "past") if m.group(2) else []
            billp = [(e[0], e[1], "billing_provider") for e in ctx.find(t) if e[0][0] == "HealthcareFacility"][:1]
            amt = float(m.group(1).replace(",", ""))
            ev("bill_submitted", (amt, d[0][0] if d else str(ndate)), d[0][0] if d else str(ndate), "stated" if d else "note_date",
               span_of(m), kind, attrs={"amount": amt}, participants=billp, summary=f"Provider bill ${amt:,.2f}")
        for m in re.finditer(r"([A-Za-z ]+?|Rx|MRI|xray) from ([A-Z][^$.\n]+?) \$([\d,.]+) (paid per fee schedule|paid|denied - ([^.\n]+)|reduced to fee schedule|p\w*nd\w*d for rec\w+)", seg):
            amt = float(m.group(3).replace(",", "").rstrip("."))
            dec = "denied" if "denied" in m.group(4) else ("reduced" if "reduced" in m.group(4) else "pended" if re.match(r"p\w*nd", m.group(4)) else "paid")
            svc = canonical_service(m.group(1))
            if svc not in SERVICES:
                continue
            billp = [(e[0], e[1], "billing_provider") for e in ctx.find(m.group(2)) if e[0][0] == "HealthcareFacility"]
            ev("bill_review", (nid_, svc, amt), str(ndate), "note_date", span_of(m), kind,
               attrs={"service": svc, "amount": amt, "decision": dec, "reason": clean_space(m.group(5) or ("records needed" if dec == "pended" else "")),
                      "duplicate_bill_flagged": bool(re.search(r"duplicate bill", t))},
               participants=billp, treatments=[("Treatment", "physical-therapy")] if "PT" in svc else [],
               summary=f"Bill review: {svc} ${amt:,.2f} {dec}")
        for m in re.finditer(r"(?:got a bill for|i got a bill for|bill for) \$([\d,.]+)(?: from ([A-Z][^,.\n]+))?", seg, re.I):
            if "forwarded to bill review" in t[seg_s + m.end(): seg_s + m.end() + 30]:
                continue
            amt = float(m.group(1).replace(",", "").rstrip("."))
            billp = [(e[0], e[1], "billing_provider") for e in ctx.find(m.group(2) or "")]
            ev("bill_submitted", (amt, str(ndate), "worker"), str(ndate), "note_date", span_of(m), kind,
               attrs={"amount": amt, "received_by": "worker"}, participants=billp + [(clmt[0], clmt[1], "bill_recipient")],
               summary=f"Worker received a bill for ${amt:,.2f}")

        # ---------------- pharmacy, mileage
        if ntype == "Pharmacy" and seg_s == 0:
            res = clean_space(re.sub(r"(?i)^.*?(?:pharmacy note|rx check)[^:]*:\s*", "", t))[:120]
            ph = [(e[0], e[1], "pharmacy") for e in ctx.find(t) if e[0][0] == "HealthcareFacility"]
            ev("pharmacy_review", (nid_,), str(ndate), "note_date", (0, len(t)), kind, attrs={"result": res},
               participants=ph + [(("ClaimsStaff", "STAFF-" + slug(nd["author_name"])) + ("specialist",))] if ("ClaimsStaff", "STAFF-" + slug(nd["author_name"])) in NODES else ph,
               summary="Pharmacy review")
        for m in re.finditer(r"(?:[Aa]sked about mileage reimbursement, told to send C-257 (?:with|w/) receipts|mileage request \(C-257\) rec'd[^.\n]*|who to talk to (?:about|abt) mileage)", seg):
            action = "received" if "rec'd" in m.group(0) else ("asked" if "who to talk" in m.group(0) else "advised to send")
            ev("mileage_reimbursement_request", (nid_,), str(ndate), "note_date", span_of(m), kind,
               attrs={"action": action}, forms=[("C-257", "received" if action == "received" else "advised")],
               participants=[(clmt[0], clmt[1], "requester")], summary=f"Mileage reimbursement ({action})")

        # ---------------- money
        for m in re.finditer(r"(?:payroll s\w+ \w+ earned (?:about|aobut) \$([\d,]+) a we\w+|AWW \$([\d,]+))", seg):
            aww = float((m.group(1) or m.group(2)).replace(",", ""))
            ev("wage_information", (aww,), str(ndate), "note_date", span_of(m), kind, attrs={"average_weekly_wage": aww},
               participants=[(ctx.employer[0], ctx.employer[1], "source")], summary=f"Average weekly wage about ${aww:,.0f}")
        if ntype == "Benefits Payment" and seg_s == 0:
            wr = re.search(r"Paid \$([\d,.]+)/wk thru ([^.\n]+?)(?:\.|$| -)", t)
            out_ = re.search(r"\$([\d,.]+) outstanding", t)
            d = dates(wr.group(2), "past") if wr else []
            ev("benefit_payment", (nid_,), str(ndate), "note_date", (0, len(t)), kind,
               attrs={"weekly_rate": float(wr.group(1).replace(",", "")) if wr else None, "paid_through": d[0][0] if d else "",
                      "amount_outstanding": float(out_.group(1).replace(",", "").rstrip(".")) if out_ else None,
                      "lost_time": "no" if re.search(r"no lost time", t, re.I) else ("yes" if wr else ""),
                      "check_reissued": bool(re.search(r"re-issued", t)), "direct_deposit": bool(re.search(r"[Dd]irect deposit", t))},
               summary="Benefits ledger entry")
        for m in re.finditer(r"weekly rate (?:is )?\$([\d,.]+)(?:, not \$([\d,.]+))?", seg):
            ev("benefit_payment", (nid_, "rate"), str(ndate), "note_date", span_of(m), kind,
               attrs={"weekly_rate": float(m.group(1).replace(",", "").rstrip(".")), "corrected_from": m.group(2) or ""},
               summary=f"Weekly rate ${m.group(1)}")
        for m in re.finditer(r"(med(?:ical)?|indemnity) reserve \$([\d,]+)", seg):
            amt = float(m.group(2).replace(",", ""))
            act = ("increased" if re.search(r"increased", t) else "unchanged" if re.search(r"unchanged|keep the reserve|no change", t) else "")
            ev("reserve_review", (nid_, m.group(1)[:3], amt), str(ndate), "note_date", span_of(m), kind,
               attrs={"reserve_type": "medical" if m.group(1).startswith("med") else "indemnity", "amount": amt, "action": act},
               participants=[(("ClaimsStaff", "STAFF-" + slug(nd["author_name"])) + ("reviewer",))] if ("ClaimsStaff", "STAFF-" + slug(nd["author_name"])) in NODES else [],
               summary=f"{'Medical' if m.group(1).startswith('med') else 'Indemnity'} reserve ${amt:,.0f}")
        if ntype == "Reserve Review" and seg_s == 0 and not re.search(r"reserve \$", t):
            act = ("increased" if "increased" in t else "more authority requested" if "authority" in t else "reviewed")
            ev("reserve_review", (nid_, "note"), str(ndate), "note_date", (0, min(len(t), hoff)), kind,
               attrs={"action": act, "note_text": clean_space(t[:160])},
               participants=[("ClaimsStaff", "STAFF-" + slug(nd["author_name"]), "reviewer")], summary=f"Reserve review: {act}")
        for m in re.finditer(r"(?:approx \$([\d,]+) paid to date|paid to date approx \$([\d,]+)|[Tt]otal paid on (?:the )?file approx \$([\d,]+))", seg):
            amt = float(next(x for x in m.groups() if x).replace(",", ""))
            ev("paid_to_date_statement", (nid_, amt), str(ndate), "note_date", span_of(m, False), kind, attrs={"amount": amt},
               summary=f"Paid to date about ${amt:,.0f}")

        # ---------------- work status
        if ntype in ("Work Status",) or re.search(r"^(?:\w+ \d+ - )?RTW:", seg):
            ws = re.search(r"(back to full duty|working w/ restr\w*|working modified duty|back on light duty|working regular duty|still off work|remains off work[^.\n]*|is working w/ restr\w*)", seg, re.I)
            rs = re.search(r"[Rr]estr(?:ictions)? per (Dr [A-Z][a-z]+): ([^.\n]+?)(?:\.|$| Full| Asked| Chloe| [A-Z][a-z]+ (?:says|did|worried))", seg)
            exp = re.search(r"[Ff]ull duty release ex\w+ ([0-9/]+)", seg)
            notready = re.search(r"(?:says|states) (?:he|she) isnt r\w*|isnt ready|not ready", seg)
            exp_d = dates(exp.group(1), "future") if exp else []
            if ws or rs or exp_d or notready:
                ev("work_status_update", (nid_,), str(ndate), "note_date", (seg_s, seg_e), kind,
                   attrs={"work_status": ws.group(1).lower() if ws else "", "restrictions": clean_space(rs.group(2)) if rs else "",
                          "full_duty_release_expected": exp_d[0][0] if exp_d else "", "worker_says_not_ready": bool(notready)},
                   participants=[(c[0], c[1], "restricting_doctor") for c in clin if rs and NODES[c]["name"] == rs.group(1)],
                   summary=f"Work status: {(ws.group(1) if ws else 'restrictions')}")
        for m in re.finditer(r"WORK(?: STATUS)?: ([^;\n]+)(?:; restr: ([^\n]+))?", seg):
            ev("work_status_update", (nid_,), str(ndate), "note_date", span_of(m, False), kind,
               attrs={"work_status": clean_space(m.group(1)).lower(), "restrictions": clean_space(m.group(2) or "")},
               summary=f"Work status: {clean_space(m.group(1))}")
        for m in re.finditer(r"Restr (?:are|were): ([^.\n]+(?:, [^.\n]+)?)\. (?:\w+ is )?([^.\n]+?)\.", seg):
            ev("work_status_update", (nid_,), str(ndate), "note_date", span_of(m, False), kind,
               attrs={"restrictions": clean_space(m.group(1)), "work_status": clean_space(m.group(2)).lower()},
               summary="Work status in file review")
        for m in re.finditer(r"[Bb]ack to full duty (?:from|since) ([^,.\n]+)", seg):
            d = dates(m.group(1), "past")
            if d:
                ev("return_to_full_duty", (d[0][0],), d[0][0], "stated", span_of(m, False), kind,
                   attrs={"effective_date": d[0][0], "date_written_as": m.group(1).strip()},
                   participants=[(clmt[0], clmt[1], "worker")], summary=f"Back to full duty from {d[0][0]}")
        for m in re.finditer(r"On modified duty from ([^,.\n]+)", seg):
            d = dates(m.group(1), "past")
            if d:
                ev("work_status_update", ("modified_from", d[0][0]), d[0][0], "stated", span_of(m, False), kind,
                   attrs={"work_status": "modified duty", "effective_date": d[0][0]}, summary=f"Modified duty from {d[0][0]}")
        for m in re.finditer(r"(?:[Ww]e can offer|offer) light duty starting ([^,]+), (\d+ hrs/day)", seg):
            d = dates(m.group(1), "future")
            ev("light_duty_offer", (d[0][0] if d else nid_,), d[0][0] if d else str(ndate), "stated" if d else "note_date", span_of(m), kind,
               attrs={"start_date": d[0][0] if d else "", "hours": m.group(2)}, participants=[(ctx.employer[0], ctx.employer[1], "offering_employer")],
               summary=f"Light duty offered from {d[0][0] if d else '?'} ({m.group(2)})")
        for m in re.finditer(r"light duty available, hours reduced|has not returned our calls about the modified duty offer", seg):
            ev("light_duty_offer", ("mention", nid_), str(ndate), "note_date", span_of(m), kind,
               attrs={"detail": m.group(0)}, participants=[(ctx.employer[0], ctx.employer[1], "offering_employer")], summary="Light/modified duty offer mentioned")
        for m in re.finditer(r"(?:missed (\d+) days (last month|this month|last week))|(?:been late a few times)", seg):
            ev("attendance_report", (nid_,), str(ndate), "note_date", span_of(m), kind,
               attrs={"missed_days": int(m.group(1)) if m.group(1) else None, "period": m.group(2) or "", "lateness": m.group(1) is None},
               participants=[(ctx.employer[0], ctx.employer[1], "reporter")], summary="Employer attendance report")
        for m in re.finditer(r"did (\d+) days of modified duty then called out", seg):
            ev("attendance_report", (nid_, "called_out"), str(ndate), "note_date", span_of(m), kind,
               attrs={"modified_duty_days_before_call_out": int(m.group(1))}, summary=f"Worked {m.group(1)} days modified duty then called out")

        # ---------------- IME
        for m in re.finditer(r"IME sched(?:uled)? ([^,.\n]+?) (?:with|w/) (Dr [A-Z][a-z]+)\.(?: [Pp]urpose: ([^.\n]+))?|IME with (Dr [A-Z][a-z]+) on ([^,.\n]+)", seg):
            examiner = m.group(2) or m.group(4)
            d = dates(m.group(1) or m.group(5) or "", "nearest" if (m.group(1) and kind == "primary") else "past")
            exk = ("Clinician", "CLIN-" + slug(examiner) + "-ime")
            ev("ime_scheduled", (examiner, d[0][0] if d else ""), d[0][0] if d else None, "stated" if d else "", span_of(m, False), kind,
               attrs={"exam_date": d[0][0] if d else "", "examiner": examiner, "purpose": clean_space(m.group(3) or "")},
               participants=[(exk[0], exk[1], "examiner"), (clmt[0], clmt[1], "examinee")], summary=f"IME with {examiner}")
        for m in re.finditer(r"(?:IME report in: ([^.\n]+)|report ([^,\n]+?) says (?:says )?([^.\n]+)|[Pp]eer review rec'd ([^(\n]*)\((Dr [A-Z][a-z]+)\))", seg):
            exam = re.search(r"IME (?:with|w/|sched [^.]*? (?:with|w/)) (Dr [A-Z][a-z]+)|\((Dr [A-Z][a-z]+)\)|(Dr [A-Z][a-z]+) saw", t)
            examiner = m.group(5) or (next((x for x in exam.groups() if x), "") if exam else "")
            known_ime = sorted({NODES[k]["name"] for k in ctx.entities if k[0] == "Clinician" and NODES[k]["clinician_type"] == "ime_examiner"})
            inferred = False
            if not examiner and len(known_ime) == 1:
                examiner, inferred = known_ime[0], True
            if m.group(2) and "IME" not in seg[max(0, m.start() - 60):m.start()]:
                continue
            finding = clean_space(m.group(1) or m.group(3) or "")
            d = dates(m.group(2) or m.group(4) or "", "past") if (m.group(2) or m.group(4)) else []
            fee = re.search(r"IME fee \$([\d,]+)", t)
            exk = ("Clinician", "CLIN-" + slug(examiner) + "-ime") if examiner else None
            ev("ime_report", (examiner,), d[0][0] if d else str(ndate), "stated" if d else "note_date", span_of(m, False), kind,
               attrs={"examiner": examiner, "finding": finding.lower(), "fee": float(fee.group(1).replace(",", "")) if fee else None,
                      "labelled_as": "peer review" if m.group(5) else "IME", "examiner_inferred_from_claim": inferred},
               participants=[(exk[0], exk[1], "examiner")] if exk else [], summary=f"IME report: {finding}")
        for m in re.finditer(r"IME update: ((?:Dr [A-Z][a-z]+ may disagree|Report due[^.\n]*|Need to decide[^.\n]*)[^\n]*)", seg):
            sched = [e for e in EVENTS.values() if e["claim_id"] == cid and e["event_type"] == "ime_scheduled"]
            if len(sched) == 1:
                ex = sched[0]["identity"][2:]
                ev("ime_scheduled", ex, sched[0]["event_date"], sched[0]["date_basis"], span_of(m, False), kind,
                   attrs={"update": clean_space(m.group(1))[:160]})
        for m in re.finditer(r"IME fee \$([\d,]+)", seg):
            pass  # kept on ime_report when the report is in; the fee figures in these notes look like reserve amounts (see README)

        # ---------------- hearings
        for m in re.finditer(r"(?i:(first|next) hearing is on) ([^,.\n]+)|(?i:conciliation conference is on) ([^,.\n]+)", seg):
            d = dates(m.group(2) or m.group(3), "future")
            if d:
                hk = "conciliation conference" if m.group(3) else "hearing"
                parts = [(e[0], e[1], "notified") for e in ctx.find(t[seg_s + m.start(): seg_s + m.end() + 50]) if e[0][0] == "Attorney"]
                ev("hearing_scheduled", (d[0][0],), d[0][0], "stated", span_of(m, False), kind,
                   attrs={"hearing_date": d[0][0], "hearing_kind": hk, "which": (m.group(1) or "").lower()}, participants=parts,
                   summary=f"{hk.title()} scheduled {d[0][0]}")
        for m in re.finditer(r"((?i:hearing|conciliation)) held ([^,.\n]+?)(?:, (adjourned for ([^.\n]+?)|issue narrowed to ([^.\n]+)|no a\w*ment[^.\n]*))?(?:\.|$|\n)|(?:[Ss]econd hearing) ([0-9/A-Za-z ]+?)(?: held, (judge reserved decision))?(?:\.|$|\n)|[Jj]udge's decision rec'd after (?:the )?([^ ]+) hearing", seg):
            raw_date = m.group(2) or m.group(6) or m.group(8)
            d = dates(raw_date, "past")
            if not d:
                continue
            if m.group(4):
                outcome, reason = "adjourned", clean_space(m.group(4))
            elif m.group(5):
                outcome, reason = "issue narrowed", clean_space(m.group(5))
            elif m.group(3) and re.match(r"no a\w*ment", m.group(3)):
                outcome, reason = "no agreement", ""
            elif m.group(7):
                outcome, reason = "judge reserved decision", ""
            elif m.group(8):
                outcome, reason = "decision received", ""
            else:
                outcome, reason = "unspecified", ""
            hk = "conciliation conference" if (m.group(1) or "").lower().startswith("concil") else "hearing"
            ev("hearing_held", (d[0][0], outcome), d[0][0], "stated", span_of(m, False), kind,
               attrs={"hearing_date": d[0][0], "hearing_kind": hk, "outcome": outcome, "adjournment_reason": reason,
                      "called_second_hearing": bool(m.group(6))},
               summary=f"{hk.title()} {d[0][0]}: {outcome}" + (f" ({reason})" if reason else ""))

        for m in re.finditer(r"[Aa]dmin determination notice (?:rec'd )?([0-9/A-Z]+)", seg):
            d = dates(m.group(1), "past")
            ev("board_determination", (d[0][0] if d else nid_,), d[0][0] if d else str(ndate), "stated" if d else "note_date",
               span_of(m, False), kind, attrs={"determination_date": d[0][0] if d else "", "kind": "administrative determination"},
               summary="Board administrative determination notice")
        # ---------------- attorney requests
        if ntype == "Attorney Correspondence" and seg_s == 0:
            req = []
            for pat, lab in [(r"claim file|copies of medical|medical and wage records|wage statement", "records"),
                             (r"has not been paid for ([a-zA-Z ]+?),", "payment"), (r"request authorization", "authorization"),
                             (r"asking for a hearing", "hearing threat"), (r"copy of the IME report", "IME report copy"),
                             (r"position on", "carrier position"), (r"status of", "status")]:
                mm = re.search(pat, t)
                if mm:
                    req.append(lab + (": " + mm.group(1) if lab == "payment" and mm.groups() else ""))
            atty = [(e[0], e[1], "requester") for e in ctx.find(t) if e[0][0] == "Attorney"][:1]
            ev("attorney_request", (nid_,), str(ndate), "note_date", (0, min(len(t), hoff)), kind,
               attrs={"request_types": req}, participants=atty, forms=forms_in((0, len(t)), "requested"),
               summary="Attorney request: " + ", ".join(req))
        # ---------------- settlement / permanency
        if ntype == "Permanency / Settlement" and seg_s == 0:
            ev("permanency_evaluation", (nid_,), str(ndate), "note_date", (0, min(len(t), hoff)), kind,
               attrs={"mmi_reached": "MMI reached" in t, "rating_status": "pending" if "rating pending" in t else ""},
               participants=[(c[0], c[1], "evaluating_doctor") for c in clin], summary="MMI / permanency")
            if "Section 32" in t:
                ev("settlement_discussion", (nid_,), str(ndate), "note_date", (0, min(len(t), hoff)), kind,
                   attrs={"topic": "Section 32", "medicare_check_needed": "Medicare" in t, "authority": "none authorized yet" if "none authorized" in t else ""},
                   participants=[(e[0], e[1], "negotiator") for e in ctx.find(t) if e[0][0] == "Attorney"], summary="Section 32 settlement raised")

        # ---------------- communication
        if seg_s == 0:
            if ntype.startswith("Contact - ") and not re.match(r"(?i)\s*(no answer|tried|LM|left (?:a )?message|2nd attempt)", t):
                party = {"Contact - Injured Worker": "claimant", "Contact - Employer": "employer", "Contact - Provider": "provider"}[ntype]
                channel = "email" if re.search(r"^From: |[Ee]mail from", t, re.M) else ("phone" if re.search(r"[Cc]all|[Ss]poke|phone|called", t) else "")
                ev("contact", (nid_,), str(ndate), "note_date", (0, min(len(t), hoff)), kind, attrs={"party_type": party, "channel": channel},
                   participants=mentions_in((0, min(len(t), hoff))), summary=f"Contact with {party}")
            if ntype == "Contact Attempt" or re.match(r"(?i)\s*(no answer|tried|LM for|left (?:a )?message|2nd attempt)", t):
                party = ("employer" if re.search(r"employer|ER\b", t) else "provider" if re.search(r"office|Center|Clinic|Health|Medicine|Rehab", t) else "claimant")
                res = "voicemail full" if "VM full" in t else ("left message" if re.search(r"\bLM\b|left (?:a )?message", t) else "no answer")
                ev("contact_attempt", (nid_,), str(ndate), "note_date", (0, len(t)), kind, attrs={"party_type": party, "result": res},
                   participants=mentions_in((0, len(t))), forms=forms_in((0, len(t)), "received"), summary=f"Attempt to reach {party}: {res}")
            if ntype == "Worker Message":
                channel = ("portal" if "portal" in t else "text" if "text msg" in t else "voicemail" if "voicemail" in t else "email")
                concerns = [lab for pat, lab in [(r"next check", "payment timing"), (r"bill", "bill"), (r"mileage", "mileage"),
                                                  (r"called me back|call me back|nobody called", "no call back"), (r"cant sleep|can't sleep", "sleep"),
                                                  (r"IME", "IME"), (r"light duty|come back", "return to work"), (r"hurts|bothering|not really helping", "ongoing pain"),
                                                  (r"forms", "forms sent")] if re.search(pat, t, re.I)]
                ev("worker_message", (nid_,), str(ndate), "note_date", (0, len(t)), kind, attrs={"channel": channel, "concerns": concerns},
                   participants=[(clmt[0], clmt[1], "sender")], summary=f"Worker {channel} message")
            if ntype == "Supervisor Direction":
                due = re.search(r"by ([0-9/]+|[A-Z][a-z]+ \d+)", t)
                dd = dates(due.group(1), "future") if due else []
                refer = re.search(r"refer to ([A-Z][a-z]+) for case mgmt", t)
                parts = [("ClaimsStaff", "STAFF-" + slug(nd["author_name"]), "supervisor")]
                if refer and len(STAFF_BY_FIRST.get(refer.group(1).lower(), [])) == 1:
                    parts.append(("ClaimsStaff", STAFF_BY_FIRST[refer.group(1).lower()][0], "referred_nurse"))
                ev("supervisor_direction", (nid_,), str(ndate), "note_date", (0, len(t)), kind,
                   attrs={"directions": clean_space(re.sub(r"(?s)^.*?Subject:[^\n]*\n", "", t))[:300], "due_date": dd[0][0] if dd else ""},
                   participants=parts, summary="Supervisor direction")
            if ntype == "Status Report":
                rec = re.search(r"\nHi ([A-Z][a-z]+),", t)
                ev("status_report_sent", (nid_,), str(ndate), "note_date", (0, len(t)), kind,
                   attrs={"recipient_first_name": rec.group(1) if rec else ""}, participants=[(ctx.carrier[0], ctx.carrier[1], "report_subject_carrier")],
                   summary=f"Status report to {rec.group(1) if rec else '?'}")
            if ntype == "Closure / Reopen":
                tp = re.search(r"[Tt]otal paid on (?:the )?file approx \$([\d,]+)", t)
                ev("claim_closed", (nid_,), str(ndate), "note_date", (0, len(t)), kind,
                   attrs={"total_paid": float(tp.group(1).replace(",", "")) if tp else None, "board_closed": "Board closed" in t or "board closed" in t},
                   summary="Claim closing note")
            if ntype == "Reopen Inquiry":
                ev("reopen_request", (nid_,), str(ndate), "note_date", (0, len(t)), kind,
                   attrs={"body_region": clean_space(re.sub(r"(?i).*?(?:about the |says )(.+?)(?: hurting again| flared up again).*", r"\1", re.sub(r"(?i)about (?!the )", "about the ", t)))[:60]},
                   participants=[(clmt[0], clmt[1], "caller")], summary="Worker reports flare-up after closure")
        for m in re.finditer(r"[Aa]sked (Dr [A-Z][a-z]+) for (?:an )?updated work stat\w+", seg):
            doc = [(c[0], c[1], "asked") for c in clin if NODES[c]["name"] == m.group(1)]
            ev("pending_item", (nid_, "updated work status"), str(ndate), "note_date", span_of(m, False), kind,
               attrs={"item": f"updated work status from {m.group(1)}"}, participants=doc, summary=f"Asked {m.group(1)} for updated work status")
        if seg_s == 0 and ntype in ("Diary Entry", "File Review"):
            cs = re.search(r"(?:claim|file) is ((?:still )?open[^.;\n]*|scheduled for a hearing|closed by the Board)", t, re.I)
            lmr = re.search(r"[Ll]ast med report ([0-9/]+|[A-Z][a-z]+ \d+)", t)
            nxt = re.search(r"(?:next review|review again|close the diary|if nothing by|[Nn]ext review) ([0-9/\-]+|[A-Z][a-z]+ \d+)", t)
            plus = re.search(r"diary \+(\d+)", t)
            lmr_d = dates(lmr.group(1), "past") if lmr else []
            nxt_d = dates(nxt.group(1), "future") if nxt else []
            ev("file_review", (nid_,), str(ndate), "note_date", (0, min(len(t), hoff)), kind,
               attrs={"claim_status_statement": clean_space(cs.group(1)).lower() if cs else "",
                      "last_med_report": lmr_d[0][0] if lmr_d else "", "next_review_date": nxt_d[0][0] if nxt_d else "",
                      "diary_days": int(plus.group(1)) if plus else None,
                      "no_change": bool(re.search(r"no change|nothing new|no activity|nothing still outstanding|nthing", t, re.I)),
                      "reserves_unchanged": bool(re.search(r"[Rr]eserves unch\w+", t))},
               participants=[("ClaimsStaff", "STAFF-" + slug(nd["author_name"]), "reviewer")] if ("ClaimsStaff", "STAFF-" + slug(nd["author_name"])) in NODES else [],
               summary="File review" if ntype == "File Review" else "Diary check")
        # pending items
        for m in re.finditer(r"(?:[Ss]till waiting on|[Ww]aiting on|[Pp]ending:|we need|We need|[Nn]eed the) ([^.\n]+)", seg):
            item = clean_space(m.group(1))
            if item.lower() in ("nothing", "nothing still outstanding") or item.lower().startswith(("nothing", "causation", "to respond", "the ime report before")):
                continue
            ev("pending_item", (nid_, item[:40]), str(ndate), "note_date", span_of(m, False), kind, attrs={"item": item[:120]},
               forms=forms_in(span_of(m, False), "requested"), summary=f"Waiting on {item[:60]}")
        # forms (generic)
        if seg_s == 0:
            for code, action in forms_in((0, min(len(t), hoff)), "mentioned"):
                if code in ("C-257",) or (code == "MG-2" and "reviewing" in t) or (code == "RFA-1" and "filed by" in t):
                    continue
                ev("form_activity", (code, action, nid_), str(ndate), "note_date", (0, min(len(t), hoff)), kind,
                   attrs={"form_code": code, "action": action}, forms=[(code, action)], summary=f"Form {code} {action}")


# ============================================================== corrections, hearings merge, conflicts
def link_corrections(claim_ctx, by_claim_notes):
    """'Correction to my <date> note - X is A, not B' -> CORRECTS edge to the note that holds B.
    Appointment and DOI corrections also create the corrected event and mark the wrong one."""
    for cid, ids in by_claim_notes.items():
        ctx = claim_ctx[cid]
        for note_id in ids:
            nd = NODES[("Note", note_id)]
            if nd["note_type"] != "Correction":
                continue
            t = rule_text(nd["text"]); ndate = to_date(nd["note_date"])
            m = re.search(r"[Cc]orrection to my ([^-]+?) note\s*-\s*(.+)", t)
            if not m:
                LOG["unresolved_correction"].append(f"{note_id}: pattern not recognized"); continue
            target_date = first_date(m.group(1), ndate, "past")
            body = m.group(2).strip().rstrip(".")
            vm = re.search(r"(?:is|IS) \$?(.+?),? (?:not|NOT) \$?(.+?)\.?(?:\s+-\w+)?$", body)
            right, wrong = (clean_space(vm.group(1)), clean_space(vm.group(2))) if vm else ("", "")
            what = ("appointment" if "appt" in body.lower() else "date of injury" if "doi" in body.lower() else
                    "weekly rate" if "rate" in body.lower() else "body side" if re.search(r"right|left", body, re.I) else "other")
            cands = [i for i in ids if NODES[("Note", i)]["note_date"] == target_date and i != note_id]
            best = [i for i in cands if wrong and re.search(r"(?<![\d/])" + re.escape(wrong.split()[0]) + r"(?![\d/])", rule_text(NODES[("Note", i)]["text"]), re.I)]
            target = (best or [i for i in cands if NODES[("Note", i)]["author_name"] == nd["author_name"]] or cands or [None])[0]
            if target:
                add_edge("CORRECTS", ("Note", note_id), ("Note", target), "note_text", note_id, "rule_v1", "unreviewed", cid,
                         corrected_fact=what, wrong_value=wrong, right_value=right,
                         target_match="wrong_value_found_in_target" if best else "same_date_only")
            else:
                LOG["unresolved_correction"].append(f"{note_id}: no note on {target_date} in claim {cid}")
            if what == "appointment" and right:
                rd = first_date(right, ndate, "nearest")
                if rd:
                    record_event(ctx, "appointment_scheduled", (rd,), rd, "stated", nd, "primary", (0, len(t)),
                                 attrs={"appointment_date": rd, "source": "correction"}, summary=f"Appointment {rd} (corrected)")
                wd = first_date(wrong, ndate, "nearest") if wrong else None
                old = EVENT_KEYS.get((cid, "appointment_scheduled", wd))
                if old:
                    EVENTS[old]["attrs"]["superseded_by_correction"].append((note_id, note_id))
            if what == "date of injury" and right:
                rd = first_date(right, ctx.first_note_date, "past")
                if rd:
                    record_event(ctx, "injury_occurred", (rd,), rd, "stated", nd, "primary", (0, len(t)),
                                 attrs={"date_of_injury": rd, "source": "correction", "year_written": True},
                                 participants=[(ctx.claimant[0], ctx.claimant[1], "injured_worker")], summary=f"Injury on {rd} (corrected)")
                wd = first_date(wrong, ctx.first_note_date, "past") if wrong else None
                old = EVENT_KEYS.get((cid, "injury_occurred", wd))
                if old:
                    EVENTS[old]["attrs"]["superseded_by_correction"].append((note_id, note_id))


def merge_yearless_dates():
    """A date written without a year ('DOI May 1') is compatible with the same month/day written
    with a year elsewhere ('DOI 5/1/15'). Merge such evidence instead of reporting a false conflict."""
    for et in ("injury_occurred",):
        groups = defaultdict(list)
        for eid, ev in EVENTS.items():
            if ev["event_type"] == et and ev["event_date"]:
                groups[(ev["claim_id"], ev["event_date"][5:])].append(eid)
        for k, eids in groups.items():
            if len(eids) < 2:
                continue
            def has_year(e):
                return any(v is True for v, _ in EVENTS[e]["attrs"].get("year_written", [])) or not EVENTS[e]["attrs"].get("year_written")
            with_year = [e for e in eids if has_year(e)]
            yearless = [e for e in eids if e not in with_year]
            if len(with_year) == 1:
                tgt = with_year[0]
                for e in yearless:
                    EVENTS[tgt]["evidence"].extend(EVENTS[e]["evidence"])
                    for a, vals in EVENTS[e]["attrs"].items():
                        if a not in ("date_of_injury", "year_written"):
                            EVENTS[tgt]["attrs"][a].extend(vals)
                    LOG["info"].append(f"merged year-less {et} evidence {EVENTS[e]['event_date']} into {EVENTS[tgt]['event_date']} (claim {k[0]})")
                    del EVENTS[e]


def merge_unspecified_hearings():
    by_date = defaultdict(list)
    for eid, ev in EVENTS.items():
        if ev["event_type"] == "hearing_held":
            by_date[(ev["claim_id"], ev["event_date"])].append(eid)
    for k, eids in by_date.items():
        unspec = [e for e in eids if EVENTS[e]["identity"][-1] == "unspecified"]
        specific = [e for e in eids if e not in unspec]
        if unspec and specific:
            for u in unspec:
                for s in specific:
                    EVENTS[s]["evidence"].extend(dict(x, kind=x["kind"]) for x in EVENTS[u]["evidence"])
                del EVENTS[u]


def detect_conflicts():
    by_claim_type = defaultdict(list)
    for eid, ev in EVENTS.items():
        by_claim_type[(ev["claim_id"], ev["event_type"])].append(eid)

    def link(a, b, fact, va, vb):
        sup = [x for x in (a, b) if EVENTS[x]["attrs"].get("superseded_by_correction")]
        add_edge("CONFLICTS_WITH", ("ClaimEvent", a), ("ClaimEvent", b), "derived", "detect_conflicts", "computed", "unreviewed",
                 EVENTS[a]["claim_id"], fact=fact, value_a=str(va), value_b=str(vb),
                 resolution=("value " + str(EVENTS[sup[0]]["event_date"]) + " was corrected by note " + EVENTS[sup[0]]["attrs"]["superseded_by_correction"][0][0]) if sup else "unresolved")
        LOG["conflict"].append(f"claim {EVENTS[a]['claim_id']}: {fact}: {va} vs {vb} ({a} / {b})")

    for (cid, et), eids in by_claim_type.items():
        if et in ("injury_occurred", "return_to_full_duty"):
            for i, a in enumerate(eids):
                for b in eids[i + 1:]:
                    link(a, b, "date_of_injury" if et == "injury_occurred" else "return_to_full_duty_date",
                         EVENTS[a]["event_date"], EVENTS[b]["event_date"])
        if et == "hearing_held":
            by_d = defaultdict(list)
            for e in eids:
                by_d[EVENTS[e]["event_date"]].append(e)
            for d, lst in by_d.items():
                for i, a in enumerate(lst):
                    for b in lst[i + 1:]:
                        link(a, b, f"hearing_outcome_{d}", EVENTS[a]["identity"][-1], EVENTS[b]["identity"][-1])
        if et == "ime_report":
            for i, a in enumerate(eids):
                for b in eids[i + 1:]:
                    if EVENTS[a]["identity"][-1] != EVENTS[b]["identity"][-1]:
                        link(a, b, "ime_examiner", EVENTS[a]["identity"][-1], EVENTS[b]["identity"][-1])
        if et == "imaging_result":
            by_r = defaultdict(list)
            for e in eids:
                a = EVENTS[e]["attrs"]
                by_r[(EVENTS[e]["identity"][2], str(a.get("result_text", [("", "")])[0][0])[:25])].append(e)
            for k, lst in by_r.items():
                if k[0] != "MRI" or len(k[1]) < 15:
                    continue  # several x-rays with 'neg' results are normal; one MRI with one result should have one date
                for i, a in enumerate(lst):
                    for b in lst[i + 1:]:
                        if EVENTS[a]["event_date"] != EVENTS[b]["event_date"]:
                            link(a, b, f"{k[0]}_result_date (same result, two dates)", EVENTS[a]["event_date"], EVENTS[b]["event_date"])
        if et == "ime_report":
            for r_ in eids:
                for s_ in by_claim_type.get((cid, "ime_scheduled"), []):
                    if EVENTS[s_]["event_date"] and EVENTS[r_]["event_date"] and EVENTS[r_]["event_date"] < EVENTS[s_]["event_date"]:
                        link(s_, r_, "ime_report_dated_before_exam", EVENTS[s_]["event_date"], EVENTS[r_]["event_date"])
        if et == "wage_information":
            for i, a in enumerate(eids):
                for b in eids[i + 1:]:
                    link(a, b, "average_weekly_wage", EVENTS[a]["identity"][-1], EVENTS[b]["identity"][-1])
        if et == "paid_to_date_statement":
            seq = sorted(eids, key=lambda e: (NODES[("Note", EVENTS[e]["evidence"][0]["note_id"])]["note_date"], EVENTS[e]["evidence"][0]["note_id"]))
            for prev, e in zip(seq, seq[1:]):
                if EVENTS[e]["identity"][-1] < EVENTS[prev]["identity"][-1]:
                    link(prev, e, "paid_to_date_decreased", EVENTS[prev]["identity"][-1], EVENTS[e]["identity"][-1])


def step_applies(ev, step):
    """Only link an event to a process step when the event really is an instance of it."""
    t = ev["event_type"]; a = {k: [v for v, _ in vals] for k, vals in ev["attrs"].items()}
    if t == "compensability_decision":
        return "disputed" in a.get("decision", [])
    if t == "benefit_payment" and step == "PS06":
        return any(v for v in a.get("weekly_rate", []) if v)
    if t == "benefit_payment" and step == "PS07":
        return any(v for v in a.get("weekly_rate", []) if v)
    if t == "form_activity":
        codes = set(a.get("form_code", []))
        return {"PS02": "C-3", "PS03": "C-2F", "PS09": "MG-2"}.get(step) in codes
    if t in ("authorization_request", "authorization_decision") and step == "PS09":
        return any("MG-2" in str(v) or "variance" in str(v) for v in a.get("service", []))
    if t == "work_status_update":
        return True
    if t == "medical_visit" and step == "PS08":
        return True
    return True


# ============================================================== validation and outputs
def validate(schema):
    errs = []
    labels = schema["node_labels"]; rels = schema["relationship_types"]
    for (lab, key), nd in NODES.items():
        if lab not in labels:
            errs.append(f"node label not in schema: {lab}")
            continue
        allowed = set(labels[lab]["properties"]) | {"_label", "_key"}
        extra = set(nd) - allowed
        if extra:
            errs.append(f"{lab}:{key} has properties not in schema: {sorted(extra)}")
        if not nd.get(labels[lab]["key"]):
            errs.append(f"{lab}:{key} missing key property {labels[lab]['key']}")
    for e in EDGES.values():
        r = rels.get(e["type"])
        if not r:
            errs.append(f"relationship type not in schema: {e['type']}"); continue
        if e["from_label"] not in r["from"] or e["to_label"] not in r["to"]:
            errs.append(f"{e['type']} not allowed from {e['from_label']} to {e['to_label']}")
        if (e["from_label"], e["from_key"]) not in NODES or (e["to_label"], e["to_key"]) not in NODES:
            errs.append(f"{e['type']} points to a missing node: {e['from_label']}:{e['from_key']} -> {e['to_label']}:{e['to_key']}")
    # every claim must have the required claim-record links
    for (lab, key) in [k for k in NODES if k[0] == "Claim"]:
        for rt in ["FILED_BY", "HAS_EMPLOYER", "INSURED_BY", "OCCURRED_IN_COUNTY", "HAS_INJURY_NATURE", "HAS_BODY_PART", "HAS_CAUSE"]:
            if not any(e["type"] == rt and e["from_key"] == key for e in EDGES.values()):
                errs.append(f"Claim {key} missing required {rt}")
    return errs


def write_outputs(out, schema, errors, df):
    # nodes.csv and relationships.csv (long format, one row per node / edge)
    with open(os.path.join(out, "02_graph_nodes_all.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["node_id", "label", "key", "properties_json"])
        for (lab, key), nd in sorted(NODES.items()):
            props = {k: v for k, v in nd.items() if not k.startswith("_")}
            w.writerow([nid(lab, key), lab, key, json.dumps(props, default=str, ensure_ascii=False)])
    with open(os.path.join(out, "03_graph_relationships_all.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["type", "from_node_id", "to_node_id", "source_type", "source_ids", "method", "review_status",
                    "schema_version", "scope_claim_id", "properties_json"])
        for e in EDGES.values():
            w.writerow([e["type"], nid(e["from_label"], e["from_key"]), nid(e["to_label"], e["to_key"]), e["source_type"],
                        ";".join(sorted(e["source_ids"])), e["method"], e["review_status"], e["schema_version"],
                        e["scope_claim_id"], json.dumps(e["props"], default=str, ensure_ascii=False)])
    write_cypher(out, schema)
    write_json(out)
    write_reports(out, schema, errors, df)


def cy(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, (list, tuple, set)):
        return "[" + ", ".join(cy(x) for x in v) + "]"
    s = str(v).replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
    return f"'{s}'"


def write_cypher(out, schema):
    labels = schema["node_labels"]
    with open(os.path.join(ROOT, "04_neo4j", "02_load_graph_generated.cypher"), "w") as f:
        f.write("// 02_load_graph_generated.cypher -- GENERATED by 03_code/02_build_graph_from_claim_notes.py. Do not edit by hand.\n")
        f.write(f"// Schema version {SCHEMA_VERSION}. Run 01_create_constraints_and_indexes.cypher first, on an empty database.\n")
        f.write("// Uses MERGE everywhere, so running it twice does not create duplicates.\n\n")
        for (lab, key), nd in sorted(NODES.items()):
            k = labels[lab]["key"]
            props = {p: v for p, v in nd.items() if not p.startswith("_") and p != k and v not in (None, "")}
            sets = ", ".join(f"n.{p} = {cy(v)}" for p, v in props.items())
            f.write(f"MERGE (n:{lab} {{{k}: {cy(nd[k])}}})" + (f" SET {sets}" if sets else "") + ";\n")
        f.write("\n")
        for e in EDGES.values():
            fk = labels[e["from_label"]]["key"]; tk = labels[e["to_label"]]["key"]
            fv = NODES[(e["from_label"], e["from_key"])][fk]; tv = NODES[(e["to_label"], e["to_key"])][tk]
            props = dict(e["props"]); props.update(source_type=e["source_type"], source_ids=sorted(e["source_ids"]), method=e["method"],
                                                   review_status=e["review_status"], schema_version=e["schema_version"], scope_claim_id=e["scope_claim_id"])
            ident = {p: props[p] for p in ("role", "char_start", "action", "laterality", "service") if p in props}
            ident_s = (" {" + ", ".join(f"{p}: {cy(v)}" for p, v in ident.items()) + "}") if ident else ""
            sets = ", ".join(f"r.{p} = {cy(v)}" for p, v in props.items() if p not in ident)
            f.write(f"MATCH (a:{e['from_label']} {{{fk}: {cy(fv)}}}), (b:{e['to_label']} {{{tk}: {cy(tv)}}}) "
                    f"MERGE (a)-[r:{e['type']}{ident_s}]->(b) SET {sets};\n")


def write_json(out):
    nodes = [{"id": nid(l, k), "label": l, **{p: v for p, v in nd.items() if not p.startswith("_") and p not in ("text",)}}
             for (l, k), nd in NODES.items() if l != "Chunk"]
    links = [{"source": nid(e["from_label"], e["from_key"]), "target": nid(e["to_label"], e["to_key"]), "type": e["type"], **e["props"]}
             for e in EDGES.values() if e["from_label"] != "Chunk" and e["to_label"] != "Chunk"]
    json.dump({"nodes": nodes, "links": links}, open(os.path.join(out, "08_graph_for_ui_without_chunks.json"), "w"), default=str)


def write_reports(out, schema, errors, df):
    lab_counts = Counter(l for l, _ in NODES)
    rel_counts = Counter(e["type"] for e in EDGES.values())
    ev_counts = Counter(ev["event_type"] for ev in EVENTS.values())
    review = Counter(e["review_status"] for e in EDGES.values())
    # coverage: notes with at least one event
    noted = defaultdict(set)
    for ev in EVENTS.values():
        for x in ev["evidence"]:
            noted[x["note_id"]].add(ev["event_type"])
    all_notes = [k[1] for k in NODES if k[0] == "Note"]
    no_event = [n for n in all_notes if n not in noted]
    by_type_cov = defaultdict(lambda: [0, 0])
    for n in all_notes:
        t = NODES[("Note", n)]["note_type"]
        by_type_cov[t][1] += 1
        by_type_cov[t][0] += n in noted
    with open(os.path.join(out, "06_unmapped_notes_for_review.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["note_id", "note_type", "note_date", "text"])
        for n in no_event:
            nd = NODES[("Note", n)]
            w.writerow([n, nd["note_type"], nd["note_date"], nd["text"][:400]])
    with open(os.path.join(out, "05_conflicts_found.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["claim_id", "fact", "value_a", "value_b", "event_a", "event_b", "evidence_notes_a", "evidence_notes_b"])
        for e in EDGES.values():
            if e["type"] == "CONFLICTS_WITH":
                a, b = e["from_key"], e["to_key"]
                w.writerow([e["scope_claim_id"], e["props"]["fact"], e["props"]["value_a"], e["props"]["value_b"], a, b,
                            ";".join(sorted({x["note_id"] for x in EVENTS[a]["evidence"]})),
                            ";".join(sorted({x["note_id"] for x in EVENTS[b]["evidence"]}))])
        for eid, ev in EVENTS.items():
            a = json.loads(NODES[("ClaimEvent", eid)]["attributes_json"]).get("_conflicting_values")
            if a:
                for fact, vals in a.items():
                    w.writerow([ev["claim_id"], f"{ev['event_type']}.{fact} (same event)", json.dumps(vals[0]), json.dumps(vals[1:]), eid, eid, "", ""])
    with open(os.path.join(out, "04_claim_events_timeline.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["claim_id", "event_date", "event_type", "event_category", "summary", "support", "evidence_notes", "attributes_json", "event_id"])
        for eid, ev in sorted(EVENTS.items(), key=lambda x: (x[1]["claim_id"], x[1]["event_date"] or "", x[0])):
            nd = NODES[("ClaimEvent", eid)]
            w.writerow([ev["claim_id"], ev["event_date"] or "", ev["event_type"], nd["event_category"], ev["summary"], nd["support"],
                        ";".join(sorted({x["note_id"] for x in ev["evidence"]})), nd["attributes_json"], eid])

    L = []
    L.append(f"# Graph build report (schema v{SCHEMA_VERSION})\n")
    L.append(f"Built {dt.datetime.now().strftime('%Y-%m-%d %H:%M')} from {df['Claim Identifier'].nunique()} claims and {len(df)} notes.\n")
    L.append(f"**{len(NODES):,} nodes, {len(EDGES):,} relationships, {len(EVENTS):,} claim events. Schema violations: {len(errors)}.**\n")
    L.append("## Nodes by label\n\n| Label | Count |\n|---|---|")
    for lab in schema["node_labels"]:
        L.append(f"| {lab} | {lab_counts.get(lab, 0)} |")
    L.append("\n## Relationships by type\n\n| Type | Count |\n|---|---|")
    for rt in schema["relationship_types"]:
        L.append(f"| {rt} | {rel_counts.get(rt, 0)} |")
    L.append("\n## Review status of relationships\n\n| Status | Count | Meaning |\n|---|---|---|")
    meaning = {"approved": "deterministic, from structured columns or note headers", "unreviewed": "extracted from note text by rules; audit a sample", "draft": "curated by us from public documents; needs team review"}
    for k, v in review.most_common():
        L.append(f"| {k} | {v} | {meaning.get(k, '')} |")
    L.append("\n## Claim events by type\n\n| Event type | Count |\n|---|---|")
    for k, v in sorted(ev_counts.items(), key=lambda x: -x[1]):
        L.append(f"| {k} | {v} |")
    L.append(f"\n## Coverage: notes that produced at least one event\n\n{len(all_notes) - len(no_event)} of {len(all_notes)} notes "
             f"({100 * (len(all_notes) - len(no_event)) / len(all_notes):.1f}%). The rest are listed in `06_unmapped_notes_for_review.csv`.\n")
    L.append("| Note type | Notes | With an event | % |\n|---|---|---|---|")
    for t, (a, b) in sorted(by_type_cov.items(), key=lambda x: x[1][0] / x[1][1]):
        L.append(f"| {t} | {b} | {a} | {100 * a / b:.0f}% |")
    L.append("\n## Problems found in the data\n")
    for k in ["data_issue", "ambiguous_mention", "fuzzy_alias", "truncated_note", "unresolved_sender", "unresolved_correction"]:
        if LOG[k]:
            L.append(f"\n### {k.replace('_', ' ')} ({len(LOG[k])})\n")
            L.extend(f"- {x}" for x in LOG[k][:60])
    L.append(f"\n### conflicts between events ({len(LOG['conflict'])})\nSee `05_conflicts_found.csv`.\n")
    L.extend(f"- {x}" for x in LOG["conflict"][:80])
    L.append(f"\n### same event, different values ({len(LOG['within_event_conflict'])})\n")
    L.extend(f"- {x}" for x in LOG["within_event_conflict"][:40])
    L.append("\n## Notes\n")
    L.extend(f"- {x}" for x in LOG["info"])
    if errors:
        L.append("\n## Schema violations\n"); L.extend(f"- {x}" for x in errors[:200])
    open(os.path.join(out, "01_graph_build_report.md"), "w").write("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
