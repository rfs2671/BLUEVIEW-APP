"""DOT records for a project — the pure parts (no database, no network).

Two NYC Open Data datasets, read per project and stored in `dot_logs`:

  * OATH Hearings Division Case Status, filtered to issuing agency DOT:
    DOT violations / summonses.
  * DOT Street Construction Permits: DOT permits, with their expiry.

NOT VERIFIED FROM HERE. The dataset ids and field names below are what these
datasets are documented to carry; the build sandbox cannot reach
data.cityofnewyork.us. So every field is read from a short list of candidate
names, and the sync logs the field NAMES each dataset actually returned (never
values). If a name is wrong the record simply fails to match and nothing is
alerted: wrong field names fail closed.

MATCHING, STRICT, IN THIS ORDER — the first key BOTH sides carry decides:
  1. BIN   equal, or no match
  2. BBL   equal, or no match
  3. address: house number + normalized street (+ borough when both carry
     one) exactly equal, or no match.
Never fuzzy: "588 THOMAS S BOYLAND ST" does not match "586 …" or "THOMAS
BOYLAND ST". A record that carries none of the keys matches nothing.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

SODA = "https://data.cityofnewyork.us/resource"

OATH_DATASET = "jz4z-kudi"
PERMIT_DATASET = "tqtj-sjs8"
DOT_AGENCY_WORDS = ("TRANSPORTATION", "DOT")

# Candidate field names, first non-empty wins.
F = {
    "oath_number": ("ticket_number", "summons_number", "violation_number"),
    "oath_date": ("violation_date", "issue_date", "violation_issue_date"),
    "oath_status": ("hearing_status", "status", "hearing_result"),
    "oath_desc": ("charge_1_code_description", "charge_description",
                  "violation_description"),
    "oath_agency": ("issuing_agency", "agency"),
    "permit_number": ("permitnumber", "permit_number"),
    "permit_issue": ("permitissuedate", "issuedworkstartdate", "issue_date"),
    "permit_expiry": ("permitexpirationdate", "issuedworkenddate",
                      "expiration_date"),
    "permit_status": ("permitstatusshortdesc", "permit_status", "status"),
    "permit_type": ("permittypedesc", "permit_type", "permittypeshortdesc"),
    "bin": ("bin", "bin_number", "building_identification_number"),
    "bbl": ("bbl",),
    "boro": ("violation_location_borough", "boroughname", "borough", "boro"),
    "block": ("violation_location_block_no", "block", "block_no"),
    "lot": ("violation_location_lot_no", "lot", "lot_no"),
    "house": ("violation_location_house", "housenumber", "house_number",
              "house_no"),
    "street": ("violation_location_street_name", "onstreetname", "street_name",
               "street"),
}


def pick(rec: Dict[str, Any], key: str) -> str:
    for name in F[key]:
        v = rec.get(name)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


# ── Location keys ───────────────────────────────────────────────────────────

_BORO_CODE = {"MANHATTAN": "1", "MN": "1", "NEW YORK": "1", "BRONX": "2",
              "BX": "2", "BROOKLYN": "3", "BK": "3", "KINGS": "3",
              "QUEENS": "4", "QN": "4", "STATEN ISLAND": "5", "SI": "5",
              "RICHMOND": "5", "1": "1", "2": "2", "3": "3", "4": "4", "5": "5"}

_SUFFIX = {"STREET": "ST", "STR": "ST", "AVENUE": "AVE", "AV": "AVE",
           "ROAD": "RD", "BOULEVARD": "BLVD", "PLACE": "PL", "COURT": "CT",
           "DRIVE": "DR", "LANE": "LN", "PARKWAY": "PKWY", "TERRACE": "TER",
           "HIGHWAY": "HWY", "EXPRESSWAY": "EXPY", "SQUARE": "SQ"}
_DIR = {"NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W"}


def norm_bin(v: Any) -> str:
    d = re.sub(r"\D", "", str(v or ""))
    # A real BIN is 7 digits; X000000 is DOB's "no BIN yet" placeholder.
    if len(d) != 7 or d[1:] == "000000":
        return ""
    return d


def norm_bbl(v: Any) -> str:
    d = re.sub(r"\D", "", str(v or ""))
    return d if len(d) == 10 and d[0] in "12345" else ""


def bbl_from_parts(boro: Any, block: Any, lot: Any) -> str:
    code = _BORO_CODE.get(str(boro or "").strip().upper(), "")
    b = re.sub(r"\D", "", str(block or ""))
    l_ = re.sub(r"\D", "", str(lot or ""))
    if not code or not b or not l_ or len(b) > 5 or len(l_) > 4:
        return ""
    return f"{code}{int(b):05d}{int(l_):04d}"


def norm_street(v: Any) -> str:
    words = re.sub(r"[^A-Z0-9 ]", " ", str(v or "").upper()).split()
    out = []
    for w in words:
        w = _SUFFIX.get(w, _DIR.get(w, w))
        out.append(w)
    return " ".join(out)


def norm_house(v: Any) -> str:
    return re.sub(r"\s+", "", str(v or "").upper())


def project_keys(project: Dict[str, Any]) -> Dict[str, str]:
    """BIN, BBL and the address of a project, normalized."""
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
    return {
        "bin": norm_bin(project.get("nyc_bin")),
        "bbl": norm_bbl(project.get("bbl") or project.get("nyc_bbl")),
        "house": norm_house(m.group(1)) if m else "",
        "street": norm_street(m.group(2)) if m else "",
        "boro": boro,
    }


def record_keys(rec: Dict[str, Any]) -> Dict[str, str]:
    bbl = norm_bbl(pick(rec, "bbl")) or bbl_from_parts(
        pick(rec, "boro"), pick(rec, "block"), pick(rec, "lot"))
    return {
        "bin": norm_bin(pick(rec, "bin")),
        "bbl": bbl,
        "house": norm_house(pick(rec, "house")),
        "street": norm_street(pick(rec, "street")),
        "boro": _BORO_CODE.get(pick(rec, "boro").upper(), ""),
    }


def match(project_k: Dict[str, str], rec_k: Dict[str, str]) -> Optional[str]:
    """'bin' | 'bbl' | 'address' when the record is this project's, else None."""
    if project_k.get("bin") and rec_k.get("bin"):
        return "bin" if project_k["bin"] == rec_k["bin"] else None
    if project_k.get("bbl") and rec_k.get("bbl"):
        return "bbl" if project_k["bbl"] == rec_k["bbl"] else None
    if (project_k.get("house") and project_k.get("street")
            and rec_k.get("house") and rec_k.get("street")):
        if project_k.get("boro") and rec_k.get("boro") \
                and project_k["boro"] != rec_k["boro"]:
            return None
        if (project_k["house"] == rec_k["house"]
                and project_k["street"] == rec_k["street"]):
            return "address"
    return None


# ── What to ask the datasets ────────────────────────────────────────────────

def _q(v: str) -> str:
    return v.replace("'", "''")


def queries(pk: Dict[str, str]) -> List[Dict[str, Any]]:
    """The requests for one project. Each fetches a bounded candidate set;
    `match` alone decides what is the project's."""
    out = []
    agency = "upper(issuing_agency) like '%TRANSPORTATION%'"
    if pk.get("bbl"):
        block = str(int(pk["bbl"][1:6]))
        out.append({"dataset": OATH_DATASET, "kind": "dot_violation", "params": {
            "$where": f"{agency} AND (violation_location_block_no = '{block}' "
                      f"OR violation_location_block_no = '{int(block):05d}')",
            "$limit": "200", "$order": "violation_date DESC"}})
    if pk.get("house") and pk.get("street"):
        out.append({"dataset": OATH_DATASET, "kind": "dot_violation", "params": {
            "$where": f"{agency} AND violation_location_house = '{_q(pk['house'])}'",
            "$limit": "200", "$order": "violation_date DESC"}})
        first = pk["street"].split()[0]
        out.append({"dataset": PERMIT_DATASET, "kind": "dot_permit", "params": {
            "$where": f"upper(onstreetname) like '%{_q(first)}%'",
            "$limit": "200"}})
    return out


# ── A stored record ─────────────────────────────────────────────────────────

def to_log(kind: str, rec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The dot_logs fields for one source record, or None when it lacks its
    number (or, for OATH, is not DOT's)."""
    if kind == "dot_violation":
        agency = pick(rec, "oath_agency").upper()
        if not any(w in agency for w in DOT_AGENCY_WORDS):
            return None
        num = pick(rec, "oath_number")
        if not num:
            return None
        return {"record_type": "dot_violation", "raw_id": f"oath:{num}",
                "number": num, "issue_date": pick(rec, "oath_date") or None,
                "status": pick(rec, "oath_status") or None,
                "description": pick(rec, "oath_desc") or None,
                "charge": pick(rec, "oath_desc") or None,
                "agency": pick(rec, "oath_agency") or None,
                "dataset": OATH_DATASET,
                "link": f"{SODA}/{OATH_DATASET}.json?ticket_number={num}"}
    if kind == "dot_permit":
        num = pick(rec, "permit_number")
        if not num:
            return None
        return {"record_type": "dot_permit", "raw_id": f"dotpermit:{num}",
                "number": num, "issue_date": pick(rec, "permit_issue") or None,
                "expiration_date": pick(rec, "permit_expiry") or None,
                "status": pick(rec, "permit_status") or None,
                "description": pick(rec, "permit_type") or None,
                "dataset": PERMIT_DATASET,
                "link": f"{SODA}/{PERMIT_DATASET}.json?permitnumber={num}"}
    return None


def field_names(records: Iterable[Dict[str, Any]], limit: int = 3) -> List[str]:
    """The field names a dataset actually returned — for the log, no values."""
    names = set()
    for i, r in enumerate(records):
        if i >= limit:
            break
        if isinstance(r, dict):
            names |= set(r.keys())
    return sorted(names)
