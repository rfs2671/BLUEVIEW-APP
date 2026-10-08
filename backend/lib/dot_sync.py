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
  A segment permit (no house number) never matches — it is counted, not
  guessed. Status "ISSUED & PRINTED" is the active one; EXPIRED*, VOIDED*,
  DELINQUENT* rows get no reminder and no alert.

Never fuzzy: "588 THOMAS S BOYLAND ST" does not match "586 …" or "THOMAS
BOYLAND ST", and a different BBL is a different lot whatever the address.
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


def project_keys(project: Dict[str, Any]) -> Dict[str, str]:
    """BBL, borough and street address of a project, normalized."""
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
    return {
        "bbl": bbl,
        "house": norm_house(m.group(1)) if m else "",
        "street": norm_street(m.group(2)) if m else "",
        "boro": boro,
    }


# ── Matching ────────────────────────────────────────────────────────────────

def oath_keys(rec: Dict[str, Any]) -> Dict[str, str]:
    return {
        "bbl": bbl_from_parts(_v(rec, "violation_location_borough"),
                              _v(rec, "violation_location_block_no"),
                              _v(rec, "violation_location_lot_no")),
        "house": norm_house(_v(rec, "violation_location_house")),
        "street": norm_street(_v(rec, "violation_location_street_name")),
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
        if pk["house"] == rk["house"] and pk["street"] == rk["street"]:
            return "address"
    return None


def match_permit(pk: Dict[str, str], rk: Dict[str, str]) -> Optional[str]:
    """'address' | None. Borough, house number and street, all three."""
    if not (pk.get("boro") and pk.get("house") and pk.get("street")):
        return None
    if not (rk.get("boro") and rk.get("house") and rk.get("street")):
        return None
    if (pk["boro"], pk["house"], pk["street"]) == (rk["boro"], rk["house"], rk["street"]):
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
            word = max(pk["street"].split(), key=len)
            out.append({"dataset": PERMIT_DATASET, "kind": "dot_permit", "params": {
                "$where": f"boroughname = '{BORO_NAME[pk['boro']]}' "
                          f"AND permithousenumber = '{_q(pk['house'])}' "
                          f"AND upper(onstreetname) like '%{_q(word)}%'",
                "$limit": "200"}})
    return out


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
                "status": _v(rec, "hearing_status") or None,
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
