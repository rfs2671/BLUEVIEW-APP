"""DOT records for a project — the pure parts (no database, no network).

Two NYC Open Data datasets, read per project and stored in `dot_logs`.
Schemas verified from the NYC Open Data metadata (2026-10-08):

OATH Hearings Division Case Status — jz4z-kudi
  ticket_number, violation_date, issuing_agency, hearing_status,
  hearing_result, hearing_date, compliance_status, penalty_imposed,
  balance_due, charge_1_code_description, violation_location_borough
  ("STATEN IS" for Staten Island), violation_location_block_no (5 digits),
  violation_location_lot_no (4 digits; "00000" / "0000" mean missing),
  violation_location_house, violation_location_street_name.
  issuing_agency is "DEPT OF TRANSPORTATION" or "DEPT OF TRAN" for DOT.
  (Respondent street/city fields were removed from the dataset in May 2026
  and are not read.)
  MATCH: BBL first; then house + street (+ borough) exact normalized.

Street Construction Permits 2022–present — tqtj-sjs8 (daily)
  permitnumber, permittypedesc, permitteename, permitstatusshortdesc,
  permitissuedate, issuedworkstartdate, issuedworkenddate (the expiry),
  boroughname (full name, "STATEN ISLAND"), permithousenumber (~36%
  filled), onstreetname, fromstreetname, tostreetname. NO BIN, NO BBL.
  MATCH: borough + house number + street, all three, exact normalized.
  A segment permit (no house number) never matches — it is not guessed
  (and the request, filtered on the house number, does not fetch them).
  Status "ISSUED & PRINTED" is the active one; EXPIRED*, VOIDED*,
  DELINQUENT* rows get no reminder and no alert.

Never fuzzy: "588 THOMAS S BOYLAND ST" does not match "586 …" or "THOMAS
BOYLAND ST", and a different BBL is a different lot whatever the address.

THE ONE EXCEPTION IS A STREET'S OTHER NAME, and it is exact too: a street
renamed by the city is still written with its old name by inspectors and in
the datasets. DOT wrote two OATH summonses (Sept 29, 2026) for "588 HOPKINSON
AVENUE btwn Blake and Sutter Avenues" -- that is 588 Thomas S. Boyland Street
(Hopkinson Avenue was renamed for Thomas S. Boyland) -- and the report showed
no DOT violations, because "HOPKINSON AVE" is not "THOMAS S BOYLAND ST". A
project's other street names are `RENAMED_STREETS` (a curated, documented
table) plus the project's own `street_aliases`; the house number, borough (and
BBL when the record has one) must still agree.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

SODA = "https://data.cityofnewyork.us/resource"

OATH_DATASET = "jz4z-kudi"
PERMIT_DATASET = "tqtj-sjs8"
DOT_AGENCY_PREFIXES = ("DEPT OF TRANSPORTATION", "DEPT OF TRAN")


def _v(rec: Dict[str, Any], key: str) -> str:
    v = rec.get(key)
    return str(v).strip() if v is not None else ""


# ── Normalizing ─────────────────────────────────────────────────────────────

_BORO_CODE = {"MANHATTAN": "1", "BRONX": "2", "BROOKLYN": "3", "QUEENS": "4",
              "STATEN ISLAND": "5", "STATEN IS": "5", "STATEN IS.": "5"}
BORO_NAME = {"1": "MANHATTAN", "2": "BRONX", "3": "BROOKLYN", "4": "QUEENS",
             "5": "STATEN ISLAND"}

_SUFFIX = {"STREET": "ST", "STR": "ST", "AVENUE": "AVE", "AV": "AVE",
           "ROAD": "RD", "BOULEVARD": "BLVD", "PLACE": "PL", "COURT": "CT",
           "DRIVE": "DR", "LANE": "LN", "PARKWAY": "PKWY", "TERRACE": "TER",
           "HIGHWAY": "HWY", "EXPRESSWAY": "EXPY", "SQUARE": "SQ"}
_DIR = {"NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W"}


def boro_code(v: Any) -> str:
    return _BORO_CODE.get(re.sub(r"\s+", " ", str(v or "").strip().upper()), "")


def norm_bbl(v: Any) -> str:
    d = re.sub(r"\D", "", str(v or ""))
    return d if len(d) == 10 and d[0] in "12345" else ""


def bbl_from_parts(boro: Any, block: Any, lot: Any) -> str:
    """A 10-digit BBL, or '' when a part is missing ("00000" / "0000" are
    the datasets' 'missing')."""
    code = boro_code(boro)
    b = re.sub(r"\D", "", str(block or ""))
    l_ = re.sub(r"\D", "", str(lot or ""))
    if not code or not b or not l_ or len(b) > 5 or len(l_) > 4:
        return ""
    if int(b) == 0 or int(l_) == 0:
        return ""
    return f"{code}{int(b):05d}{int(l_):04d}"


def norm_street(v: Any) -> str:
    words = re.sub(r"[^A-Z0-9 ]", " ", str(v or "").upper()).split()
    return " ".join(_SUFFIX.get(w, _DIR.get(w, w)) for w in words)


def norm_house(v: Any) -> str:
    return re.sub(r"\s+", "", str(v or "").upper())


def norm_name(v: Any) -> str:
    return " ".join(re.sub(r"[^A-Z0-9 ]", " ", str(v or "").upper()).split())


#: Streets the city renamed, by their CURRENT normalized name -> the old names
#: records may still carry. Add a street only with its source; a wrong entry
#: would attach another street's summonses to a project.
RENAMED_STREETS: Dict[str, List[str]] = {
    # Hopkinson Avenue (Brooklyn) was renamed Thomas S. Boyland Street. Seen on
    # real DOT summonses 0704345548 / 0704345557: "588 HOPKINSON AVENUE btwn
    # BLAKE AVENUE and SUTTER AVENUE", for a job at 588 Thomas S Boyland Street.
    "THOMAS S BOYLAND ST": ["HOPKINSON AVE"],
}


def street_names(street: str, aliases: Iterable[Any] = ()) -> List[str]:
    """A street's normalized names: its own, the old names the city renamed it
    from, and any a person added to the project -- never a fuzzy guess."""
    out = [street] if street else []
    for a in list(RENAMED_STREETS.get(street, [])) + [norm_street(x) for x in aliases or []]:
        if a and a not in out:
            out.append(a)
    return out


def project_keys(project: Dict[str, Any]) -> Dict[str, Any]:
    """BBL, borough and street address of a project, normalized; `streets`
    is every name the street goes by."""
    addr = str(project.get("address") or "").split(",")[0].strip()
    m = re.match(r"^\s*([0-9][0-9A-Za-z-]*)\s+(.+)$", addr)
    # The borough only when the address names one ("New York" does not: it
    # is also the state in every borough's address).
    boro = ""
    full = str(project.get("address") or "").upper()
    for name in ("BROOKLYN", "QUEENS", "BRONX", "STATEN ISLAND", "MANHATTAN"):
        if re.search(rf"\b{name}\b", full):
            boro = _BORO_CODE[name]
            break
    bbl = norm_bbl(project.get("bbl") or project.get("nyc_bbl"))
    if not boro and bbl:
        boro = bbl[0]
    street = norm_street(m.group(2)) if m else ""
    return {
        "bbl": bbl,
        "house": norm_house(m.group(1)) if m else "",
        "street": street,
        "streets": street_names(street, project.get("street_aliases") or []),
        "boro": boro,
    }


# ── Matching ────────────────────────────────────────────────────────────────

_CROSS = re.compile(r"\s+(?:BTWN|BTW|BTWEEN|BETWEEN|BET|B/T|BT)\b.*$")


def oath_street(raw: Any, house: Any = "") -> str:
    """The street NAME of an OATH location. The field often holds the whole
    location text -- "588 HOPKINSON AVENUE BTWN BLAKE", "MYRTLE AVE BET CLASSON
    AVE T" -- so the house number in front and the cross streets behind are
    removed. Real DOT summonses 0704345548 / 0704345557 were never matched while
    the whole string was compared with the street name."""
    s = re.sub(r"\s+", " ", str(raw or "").strip().upper())
    h = norm_house(house)
    if h:
        m = re.match(r"^(\S+)\s+(.+)$", s)
        if m and norm_house(m.group(1)) == h:
            s = m.group(2)
    return norm_street(_CROSS.sub("", s))


def oath_keys(rec: Dict[str, Any]) -> Dict[str, str]:
    return {
        "bbl": bbl_from_parts(_v(rec, "violation_location_borough"),
                              _v(rec, "violation_location_block_no"),
                              _v(rec, "violation_location_lot_no")),
        "house": norm_house(_v(rec, "violation_location_house")),
        "street": oath_street(_v(rec, "violation_location_street_name"), _v(rec, "violation_location_house")),
        "boro": boro_code(_v(rec, "violation_location_borough")),
    }


def permit_keys(rec: Dict[str, Any]) -> Dict[str, str]:
    return {
        "bbl": "",   # the dataset has none
        "house": norm_house(_v(rec, "permithousenumber")),
        "street": norm_street(_v(rec, "onstreetname")),
        "boro": boro_code(_v(rec, "boroughname")),
    }


def match_oath(pk: Dict[str, str], rk: Dict[str, str]) -> Optional[str]:
    """'bbl' | 'address' | None. BBL first: a different BBL is no match."""
    if pk.get("bbl") and rk.get("bbl"):
        return "bbl" if pk["bbl"] == rk["bbl"] else None
    if pk.get("house") and pk.get("street") and rk.get("house") and rk.get("street"):
        if pk.get("boro") and rk.get("boro") and pk["boro"] != rk["boro"]:
            return None
        if pk["house"] == rk["house"] and rk["street"] in (pk.get("streets") or [pk["street"]]):
            return "address"
    return None


def match_permit(pk: Dict[str, str], rk: Dict[str, str]) -> Optional[str]:
    """'address' | None. Borough, house number and street, all three."""
    if not (pk.get("boro") and pk.get("house") and pk.get("street")):
        return None
    if not (rk.get("boro") and rk.get("house") and rk.get("street")):
        return None
    if (pk["boro"], pk["house"]) == (rk["boro"], rk["house"]) and rk["street"] in (pk.get("streets") or [pk["street"]]):
        return "address"
    return None


def is_segment_permit(rec: Dict[str, Any]) -> bool:
    """A permit for a street segment (no house number): never matched."""
    return not _v(rec, "permithousenumber")


def is_dot_agency(rec: Dict[str, Any]) -> bool:
    agency = _v(rec, "issuing_agency").upper()
    return any(agency.startswith(p) for p in DOT_AGENCY_PREFIXES)


ACTIVE_PERMIT_STATUSES = ("ISSUED",)   # "ISSUED & PRINTED"


def permit_is_active(status: Any) -> bool:
    s = str(status or "").strip().upper()
    return any(s.startswith(a) for a in ACTIVE_PERMIT_STATUSES)


# ── What to ask the datasets ────────────────────────────────────────────────

def _q(v: str) -> str:
    return v.replace("'", "''")


_AGENCY_WHERE = ("(upper(issuing_agency) like 'DEPT OF TRAN%')")


def queries(pk: Dict[str, str]) -> List[Dict[str, Any]]:
    """The requests for one project, each narrowed on the server; the
    match functions alone decide what is the project's."""
    out = []
    if pk.get("bbl"):
        block, lot = pk["bbl"][1:6], pk["bbl"][6:10]
        out.append({"dataset": OATH_DATASET, "kind": "dot_violation", "params": {
            "$where": f"{_AGENCY_WHERE} AND violation_location_block_no = '{block}' "
                      f"AND violation_location_lot_no = '{lot}'",
            "$limit": "200", "$order": "violation_date DESC"}})
    if pk.get("house") and pk.get("street"):
        out.append({"dataset": OATH_DATASET, "kind": "dot_violation", "params": {
            "$where": f"{_AGENCY_WHERE} AND violation_location_house = '{_q(pk['house'])}'",
            "$limit": "200", "$order": "violation_date DESC"}})
        if pk.get("boro"):
            words = [max(name.split(), key=len) for name in (pk.get("streets") or [pk["street"]])]
            like = " OR ".join(f"upper(onstreetname) like '%{_q(w)}%'" for w in dict.fromkeys(words))
            out.append({"dataset": PERMIT_DATASET, "kind": "dot_permit", "params": {
                "$where": f"boroughname = '{BORO_NAME[pk['boro']]}' "
                          f"AND permithousenumber = '{_q(pk['house'])}' "
                          f"AND ({like})",
                # DEFECT MEASURED (2026 audit): a $limit with NO $order returns
                # an arbitrary 200 rows, so on a busy street the NEWEST permits
                # could silently be the ones left out. permitissuedate is the
                # field to_log() stores as issue_date; newest first.
                "$limit": "200", "$order": "permitissuedate DESC"}})
    return out


# ── Is the summons settled? ─────────────────────────────────────────────────

def _money(v: Any) -> Optional[float]:
    try:
        return float(re.sub(r"[^0-9.\-]", "", str(v))) if str(v or "").strip() else None
    except ValueError:
        return None


_NEGATED = re.compile(r"\b(?:NOT|NON|NEVER|WITHOUT|UN)\s*[- ]?\s*(?:PAID|IN\s+COMPLIANCE|COMPLIED|DISMISSED)\b")


def closed_reason(rec: Dict[str, Any]) -> Optional[str]:
    """Why an OATH summons is settled, from what the record SAYS -- or None.

    The stored status is the hearing's (NEW, SCHEDULED, HEARING COMPLETED), and
    a summons paid after its hearing is still "hearing completed": the payment
    is in the penalty and balance fields. Without this a paid ticket would be
    reported open for ever. Only positive evidence closes it:
      * the record's own words (hearing result / compliance / status) say paid,
        dismissed, not guilty, or in compliance;
      * a penalty was imposed and nothing is owed (balance 0).
    A summons with a balance still due, or no outcome yet, is open."""
    words = " ".join(_v(rec, k).upper() for k in ("hearing_result", "compliance_status", "hearing_status"))
    clean = _NEGATED.sub(" ", words)
    if re.search(r"\bPAID\b", clean):
        return "PAID IN FULL"
    if re.search(r"\bDISMISS", clean) or "NOT GUILTY" in clean or re.search(r"\bNOT\s+IN\s+VIOLATION\b", clean):
        return "DISMISSED"
    if re.search(r"\bIN\s+COMPLIANCE\b", clean) or re.search(r"\bCOMPLIED\b", clean):
        return "COMPLIED"
    penalty, balance = _money(rec.get("penalty_imposed")), _money(rec.get("balance_due"))
    if penalty is not None and penalty > 0 and balance is not None and balance <= 0:
        return "PAID IN FULL"
    return None


# ── A stored record ─────────────────────────────────────────────────────────

def to_log(kind: str, rec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The dot_logs fields for one source record, or None when it lacks its
    number (or, for OATH, is not DOT's)."""
    if kind == "dot_violation":
        if not is_dot_agency(rec):
            return None
        num = _v(rec, "ticket_number")
        if not num:
            return None
        desc = _v(rec, "charge_1_code_description") or None
        return {"record_type": "dot_violation", "raw_id": f"oath:{num}",
                "number": num, "issue_date": _v(rec, "violation_date") or None,
                # The status is the hearing's UNLESS the summons is settled, then
                # what settled it: a change of status is how the history (and
                # "resolved this period") learns of a payment.
                "status": closed_reason(rec) or _v(rec, "hearing_status") or None,
                "hearing_status": _v(rec, "hearing_status") or None,
                "hearing_result": _v(rec, "hearing_result") or None,
                "hearing_date": _v(rec, "hearing_date") or None,
                "compliance_status": _v(rec, "compliance_status") or None,
                "penalty_imposed": _v(rec, "penalty_imposed") or None,
                "balance_due": _v(rec, "balance_due") or None,
                "description": desc, "charge": desc,
                "agency": _v(rec, "issuing_agency") or None,
                "dataset": OATH_DATASET,
                "link": f"{SODA}/{OATH_DATASET}.json?ticket_number={num}"}
    if kind == "dot_permit":
        num = _v(rec, "permitnumber")
        if not num:
            return None
        return {"record_type": "dot_permit", "raw_id": f"dotpermit:{num}",
                "number": num, "issue_date": _v(rec, "permitissuedate") or None,
                "expiration_date": _v(rec, "issuedworkenddate") or None,
                "status": _v(rec, "permitstatusshortdesc") or None,
                "description": _v(rec, "permittypedesc") or None,
                "permittee": _v(rec, "permitteename") or None,
                "dataset": PERMIT_DATASET,
                "link": f"{SODA}/{PERMIT_DATASET}.json?permitnumber={num}"}
    return None


def keys_for(kind: str, rec: Dict[str, Any]) -> Dict[str, str]:
    return oath_keys(rec) if kind == "dot_violation" else permit_keys(rec)


def match(kind: str, pk: Dict[str, str], rec: Dict[str, Any]) -> Optional[str]:
    rk = keys_for(kind, rec)
    return match_oath(pk, rk) if kind == "dot_violation" else match_permit(pk, rk)


def field_names(records: Iterable[Dict[str, Any]], limit: int = 3) -> List[str]:
    """The field names a dataset actually returned — for the log, no values."""
    names = set()
    for i, r in enumerate(records):
        if i >= limit:
            break
        if isinstance(r, dict):
            names |= set(r.keys())
    return sorted(names)
