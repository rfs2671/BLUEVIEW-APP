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
  MATCH (classify_summons, DOT Phase 1 A): BBL first (a different BBL
  stops); then house + street (+ borough) exact normalized; then the permit
  the summons was written against (ydkf-mpxb inspections: novnumber =
  ticket_number, stored in dot_nov_permits) when that permit is one of the
  project's confirmed permits; then the block -- "<ON> BTWN <FROM> AND
  [<TO>]" against a confirmed frontage -- which is only ever NEEDS
  CONFIRMATION. Every charge (1-10), the hearing and the money are kept.

Street Construction Permits 2022–present — tqtj-sjs8 (daily)
  permitnumber, permittypedesc, permitteename, permitstatusshortdesc,
  permitissuedate, issuedworkstartdate (stored as work_start),
  issuedworkenddate (the expiry, stored as expiration_date),
  boroughname (full name, "STATEN ISLAND"), permithousenumber (~36%
  filled), onstreetname, fromstreetname, tostreetname. NO BIN, NO BBL.
  Also permitseriesshortdesc, previouspermitnumber, nextpermitnumber (the
  renewal chain). oftcode stopped being filled in July 2025: not read.
  MATCH, two ways (classify_permit):
    * ADDRESS: borough + house number + street, all three, exact normalized;
    * SEGMENT (DOT Phase 1 B): once the project's DOT setup is CONFIRMED, a
      permit whose borough + on/from/to equals a confirmed frontage (from/to
      in either order; a name DOT cut off matches as a prefix of at least 6
      characters). By a confirmed permittee it is the project's; by anyone
      else it is stored as NEEDS CONFIRMATION and nothing alerts on it until
      a person says "yours" (review accepted). "Not ours" is remembered.
  A segment permit (no house number, is_segment_permit) never matches by
  address. Our permittee on a street that is not a confirmed frontage is
  not matched at all.
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
from datetime import date
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
    """A permit for a street segment: no house number. It never matches by
    ADDRESS (match_permit); it can match by SEGMENT (classify_permit)."""
    return not _v(rec, "permithousenumber")


def is_dot_agency(rec: Dict[str, Any]) -> bool:
    agency = _v(rec, "issuing_agency").upper()
    return any(agency.startswith(p) for p in DOT_AGENCY_PREFIXES)


ACTIVE_PERMIT_STATUSES = ("ISSUED",)   # "ISSUED & PRINTED"


def permit_is_active(status: Any) -> bool:
    s = str(status or "").strip().upper()
    return any(s.startswith(a) for a in ACTIVE_PERMIT_STATUSES)


def permit_is_voided(status: Any) -> bool:
    """VOIDED, VOIDED AFTER ISSUE, CANCELLED: a permit that never stood."""
    s = str(status or "").strip().upper()
    return s.startswith("VOID") or "VOIDED" in s or s.startswith("CANCEL")


# ── Segment matching (DOT Phase 1 B) ────────────────────────────────────────
#
# About two thirds of DOT permits carry no house number: they are filed by
# street SEGMENT -- "HOPKINSON AVENUE from BLAKE AVENUE to SUTTER AVENUE". A
# project says which segments are its frontages and which permittee names are
# its own (projects.dot_setup, confirmed by a person); a permit on a confirmed
# frontage is then the project's when its permittee is one of those names, and
# "needs confirmation" when it is anyone else's.

#: A name DOT cut off ("THOMAS S BOYLAN") matches the whole name when it is a
#: prefix of it and at least this long. Shorter is too ambiguous ("E 1").
CUT_OFF_MIN = 6

MATCH_ADDRESS = "address"
MATCH_SEGMENT = "segment_permittee"
MATCH_OTHER = "segment_other_permittee"
STATE_CONFIRMED = "confirmed"
STATE_NEEDS = "needs_confirmation"
STATE_REJECTED = "rejected"

_ORDINAL = re.compile(r"\b(\d+)(?:ST|ND|RD|TH)\b")
_CORP_WORDS = {"INC", "LLC", "CORP", "CORPORATION", "CO", "COMPANY", "LTD", "LP",
               "LLP", "PC", "PLLC", "INCORPORATED"}


def seg_street(v: Any) -> str:
    """norm_street, and an ordinal as its number: DOT writes both "WEST 23RD
    STREET" and "WEST   23 STREET" for one street."""
    return _ORDINAL.sub(r"\1", norm_street(v))


def _renamed(s: str) -> List[str]:
    """A normalized street and its other official names, both directions."""
    out = [s]
    for current, olds in RENAMED_STREETS.items():
        if s == current:
            out += olds
        elif s in olds:
            out.append(current)
    return out


def street_variants(v: Any) -> List[str]:
    s = norm_street(v)
    if not s:
        return []
    return list(dict.fromkeys(seg_street(x) for x in _renamed(s)))


def _same_name(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    short, long_ = sorted((a, b), key=len)
    return len(short) >= CUT_OFF_MIN and long_.startswith(short)


def same_street(a: Any, b: Any) -> bool:
    """Exact after normalizing, or one of a renamed street's names, or a name
    DOT cut off (a prefix of at least CUT_OFF_MIN characters)."""
    va, vb = street_variants(a), street_variants(b)
    return any(_same_name(x, y) for x in va for y in vb)


def _cross_eq(a: Any, b: Any) -> bool:
    if not norm_street(a) and not norm_street(b):
        return True
    return same_street(a, b)


def permit_segment(rec: Dict[str, Any]) -> Dict[str, str]:
    """The segment a permit names: borough code and normalized street names."""
    return {"boro": boro_code(_v(rec, "boroughname")),
            "on": norm_street(_v(rec, "onstreetname")),
            "from": norm_street(_v(rec, "fromstreetname")),
            "to": norm_street(_v(rec, "tostreetname"))}


def frontage_matches(frontage: Dict[str, Any], seg: Dict[str, Any]) -> bool:
    """Same borough, same on-street, and the same two cross streets in either
    order. A frontage names at least one cross street."""
    fb, sb = str(frontage.get("boro") or ""), str(seg.get("boro") or "")
    if not fb or fb != sb:
        return False
    if not same_street(frontage.get("on"), seg.get("on")):
        return False
    a, b = frontage.get("from"), frontage.get("to")
    if not norm_street(a) and not norm_street(b):
        return False
    c, d = seg.get("from"), seg.get("to")
    return (_cross_eq(a, c) and _cross_eq(b, d)) or (_cross_eq(a, d) and _cross_eq(b, c))


def norm_permittee(v: Any) -> str:
    """A permittee name for comparing: upper case, '&' as AND, punctuation
    gone, a leading THE and trailing INC / LLC / CORP ... dropped. "Blue Elm,
    Inc." and "BLUE ELM INC." are one permittee."""
    s = str(v or "").upper().replace("&", " AND ").replace(".", "")
    words = re.sub(r"[^A-Z0-9 ]", " ", s).split()
    if len(words) > 1 and words[0] == "THE":
        words = words[1:]
    while len(words) > 1 and words[-1] in _CORP_WORDS:
        words = words[:-1]
    return " ".join(words)


def setup_confirmed(setup: Any) -> bool:
    return isinstance(setup, dict) and setup.get("status") == "confirmed"


def confirmed_frontages(setup: Any) -> List[Dict[str, Any]]:
    """The frontages that match: only once the setup is confirmed, and only
    those a company admin or full-access PM confirmed (a superintendent's
    suggestion is stored with confirmed False and matches nothing)."""
    if not setup_confirmed(setup):
        return []
    return [f for f in setup.get("frontages") or []
            if isinstance(f, dict) and f.get("confirmed") is True]


def confirmed_permittees(setup: Any) -> set:
    if not setup_confirmed(setup):
        return set()
    out = set()
    for p in setup.get("permittees") or []:
        if isinstance(p, dict):
            n = norm_permittee(p.get("norm") or p.get("name"))
            if n:
                out.add(n)
    return out


def classify_permit(pk: Dict[str, Any], setup: Any,
                    rec: Dict[str, Any]) -> Optional[tuple]:
    """(how, state) for one tqtj-sjs8 record, or None (not the project's).

    address match                      -> ("address", "confirmed")
    confirmed frontage + our permittee -> ("segment_permittee", "confirmed")
    confirmed frontage + anyone else   -> ("segment_other_permittee",
                                           "needs_confirmation")
    our permittee anywhere else        -> None"""
    if match_permit(pk, permit_keys(rec)):
        return (MATCH_ADDRESS, STATE_CONFIRMED)
    fronts = confirmed_frontages(setup)
    if not fronts:
        return None
    seg = permit_segment(rec)
    if not any(frontage_matches(f, seg) for f in fronts):
        return None
    who = norm_permittee(_v(rec, "permitteename"))
    if who and who in confirmed_permittees(setup):
        return (MATCH_SEGMENT, STATE_CONFIRMED)
    return (MATCH_OTHER, STATE_NEEDS)


def match_state(row: Dict[str, Any]) -> str:
    """confirmed | needs_confirmation | rejected. A row stored before Phase 1
    B carries no `match`: it was address-matched, so it is confirmed."""
    m = row.get("match") if isinstance(row, dict) else None
    if not isinstance(m, dict):
        return STATE_CONFIRMED
    st = m.get("state")
    return st if st in (STATE_CONFIRMED, STATE_NEEDS, STATE_REJECTED) else STATE_CONFIRMED


def permit_confirmed(row: Dict[str, Any]) -> bool:
    """Is this dot_logs row the project's? Summonses always are (they match
    by BBL/address only); a permit when its match state is confirmed. The
    one predicate every alert and report path asks."""
    if str((row or {}).get("record_type") or "dot_permit") != "dot_permit":
        return True
    return match_state(row) == STATE_CONFIRMED


def record_confirmed(row: Dict[str, Any]) -> bool:
    """Is this dot_logs row the project's -- a summons OR a permit? DOT Phase
    1 A gives summonses a match state too: a SEGMENT-matched summons is "on
    your block", not "yours", until a person accepts it. A row with no
    `match` (stored before Phase 1) was matched by BBL or address:
    confirmed. Every alert, brief, report and answer asks this."""
    return match_state(row) == STATE_CONFIRMED


# ── Summonses (DOT Phase 1 A) ───────────────────────────────────────────────
#
# First match wins (operator ruling, spec v3 A):
#   1 BBL      the summons' borough + block + lot equal the project's BBL. A
#              DIFFERENT BBL is a non-match and stops here.
#   2 address  house + street (any alias) + borough, all equal.
#   3 permit   the ticket is a DOT inspection's novnumber (ydkf-mpxb, stored in
#              dot_nov_permits) whose permit is one of this project's
#              CONFIRMED permits.
#   4 segment  the street reads "<ON> BTWN <FROM> AND [<TO>]": ON is a
#              confirmed frontage's on-street, FROM is that frontage's from or
#              to street, the borough agrees. An EXACT street name always
#              counts; a prefix of at least 6 counts only when DOT cut the text
#              off at its field width (OATH_STREET_MAX) and FROM is what was
#              cut (operator ruling 2026-10-23). NEEDS CONFIRMATION -- never
#              emailed or posted as the project's.

SUMMONS_BBL = "bbl"
SUMMONS_ADDRESS = "address"
SUMMONS_PERMIT = "permit"
SUMMONS_SEGMENT = "segment"
#: The ways a summons is the project's on its own evidence (a new one may email).
OWN_MATCHES = (SUMMONS_BBL, SUMMONS_ADDRESS, SUMMONS_PERMIT)

_BTWN = re.compile(r"\s(?:BTWN|BTW|BTWEEN|BETWEEN|BET|B/T)\s")
_AND = re.compile(r"\s+(?:AND|&)\s+|\s+(?:AND|&)$")
NOV_DATASET = "ydkf-mpxb"
#: DOT's OATH street field is cut at 32 characters (recorded fixture: 4 of 6
#: rows at 32, 2 at 31 where the cut fell on a space that was then stripped).
OATH_STREET_MAX = 32
OATH_BORO = {"1": "MANHATTAN", "2": "BRONX", "3": "BROOKLYN", "4": "QUEENS", "5": "STATEN IS"}


def oath_segment(raw: Any, house: Any = "") -> Optional[Dict[str, str]]:
    """{on, from, to} of an OATH location written as a segment, normalized;
    None for anything else (a plain street, an intersection "A AND B", an
    address with no BTWN). TO may be '' (cut off, or never written)."""
    s = " " + re.sub(r"\s+", " ", str(raw or "").strip().upper()) + " "
    h = norm_house(house)
    if h:
        m = re.match(r"^ (\S+) (.+)$", s)
        if m and norm_house(m.group(1)) == h:
            s = " " + m.group(2)
    m = _BTWN.search(s)
    if not m:
        return None
    on = norm_street(s[:m.start()])
    rest = s[m.end():].strip()
    parts = [p for p in _AND.split(rest)] if rest else []
    fr = norm_street(parts[0]) if parts else ""
    to = norm_street(parts[1]) if len(parts) > 1 else ""
    if not on or not fr:
        return None
    return {"on": on, "from": fr, "to": to}


def oath_street_cut(raw: Any) -> bool:
    """True when the OATH street text is at DOT's field width, i.e. was
    (probably) cut off. One short of the width counts: a cut that lands on a
    space loses the space when the text is stripped."""
    return len(str(raw or "").strip()) >= OATH_STREET_MAX - 1


def _exact_street(a: Any, b: Any) -> bool:
    """Equal after normalizing, through a renamed street's other names; no
    prefix allowance."""
    va, vb = street_variants(a), street_variants(b)
    return any(x == y for x in va for y in vb)


def summons_segment_matches(frontage: Dict[str, Any], boro: str,
                            seg: Optional[Dict[str, str]], cut: bool = False) -> bool:
    """Spec v3 A rule 4: same borough, ON = the frontage's on-street, FROM =
    the frontage's from OR to street. TO is not compared (it is usually cut
    off). `cut`: the raw text is at DOT's field width (oath_street_cut).

    An exact name always counts. The cut-name prefix (same_street, at least
    CUT_OFF_MIN characters) applies only to FROM, and only when the text was
    cut with FROM last: ON comes before BTWN and cannot have been cut, and a
    FROM followed by a TO was written whole (operator ruling 2026-10-23:
    "BLAKE AVE" complete matches; "... BTWN BLAK" cut does not)."""
    if not seg or not boro or str(frontage.get("boro") or "") != str(boro):
        return False
    if not _exact_street(frontage.get("on"), seg.get("on")):
        return False
    fr = seg.get("from")
    prefix_ok = cut and not seg.get("to")
    return any(norm_street(x) and (_exact_street(x, fr) or (prefix_ok and same_street(x, fr)))
               for x in (frontage.get("from"), frontage.get("to")))


def classify_summons(pk: Dict[str, Any], setup: Any, rec: Dict[str, Any],
                     nov_links: Optional[Dict[str, str]] = None) -> Optional[tuple]:
    """(how, state, permit_number) for one DOT OATH record, or None.
    `nov_links`: {ticket_number: permit_number} for THIS project's confirmed
    permits only (the server builds it from dot_nov_permits)."""
    rk = oath_keys(rec)
    if pk.get("bbl") and rk.get("bbl"):
        return (SUMMONS_BBL, STATE_CONFIRMED, None) if pk["bbl"] == rk["bbl"] else None
    if match_oath(pk, rk) == "address":
        return (SUMMONS_ADDRESS, STATE_CONFIRMED, None)
    ticket = _v(rec, "ticket_number")
    permit = (nov_links or {}).get(ticket)
    if ticket and permit:
        return (SUMMONS_PERMIT, STATE_CONFIRMED, permit)
    fronts = confirmed_frontages(setup)
    if fronts:
        raw_street = _v(rec, "violation_location_street_name")
        seg = oath_segment(raw_street, _v(rec, "violation_location_house"))
        boro = rk.get("boro") or ""
        cut = oath_street_cut(raw_street)
        if any(summons_segment_matches(f, boro, seg, cut) for f in fronts):
            return (SUMMONS_SEGMENT, STATE_NEEDS, None)
    return None


def summons_segment_queries(setup: Any, today: date) -> List[Dict[str, Any]]:
    """One jz4z-kudi request per confirmed frontage street: DOT summonses in
    the borough whose location names the street, issued within 24 months,
    newest first, $limit 400. classify_summons keeps the frontage's."""
    out, seen = [], set()
    since = months_ago(today, SEGMENT_MONTHS).isoformat() + "T00:00:00"
    for f in confirmed_frontages(setup):
        boro, on = OATH_BORO.get(str(f.get("boro") or "")), norm_street(f.get("on"))
        if not boro or not on or (boro, on) in seen:
            continue
        seen.add((boro, on))
        words = [max(n.split(), key=len) for n in _renamed(on) if n.split()]
        like = " OR ".join(f"upper(violation_location_street_name) like '%{_q(w)}%'"
                           for w in dict.fromkeys(words))
        out.append({"dataset": OATH_DATASET, "kind": "dot_violation", "segment": True, "params": {
            "$where": f"{_AGENCY_WHERE} AND violation_location_borough = '{boro}' "
                      f"AND ({like}) AND violation_date >= '{since}'",
            "$order": "violation_date DESC", "$limit": SEGMENT_LIMIT}})
    return out


TICKET_CAP = 100


# At most this many ticket batches (TICKET_CAP each) per project per sync
# tick. Under it (<= 1,000 linked tickets) every batch is read every tick;
# over it, a deterministic rotation (ticket_queries' `rotation`) moves the
# window each day so every ticket is read within ceil(batches / cap) days.
TICKET_BATCHES_PER_TICK = 10


def ticket_queries(tickets: Iterable[str], rotation: int = 0) -> List[Dict[str, Any]]:
    """The OATH requests for the summonses linked to the project's permits:
    the full sorted ticket set split into batches of TICKET_CAP, one request
    per batch (never truncated to the first batch: Codex P2 on #855). When
    there are more than TICKET_BATCHES_PER_TICK batches, `rotation` (the
    server passes the New York day's ordinal) picks which consecutive
    window of batches this tick reads, wrapping around."""
    t = sorted({str(x).strip() for x in tickets or [] if str(x).strip()})
    batches = [t[i:i + TICKET_CAP] for i in range(0, len(t), TICKET_CAP)]
    if len(batches) > TICKET_BATCHES_PER_TICK:
        start = (int(rotation) * TICKET_BATCHES_PER_TICK) % len(batches)
        batches = [batches[(start + k) % len(batches)] for k in range(TICKET_BATCHES_PER_TICK)]
    return [{"dataset": OATH_DATASET, "kind": "dot_violation", "nov": True, "params": {
        "$where": f"{_AGENCY_WHERE} AND ticket_number in ({', '.join(repr_q(x) for x in b)})",
        "$order": "violation_date DESC", "$limit": str(TICKET_CAP)}} for b in batches]


def repr_q(v: str) -> str:
    return f"'{_q(str(v))}'"


def nov_link_params(permits: Iterable[str]) -> Optional[Dict[str, str]]:
    """ydkf-mpxb: the inspections of these permits that carry a summons."""
    p = sorted({str(x).strip() for x in permits or [] if str(x).strip()})[:TICKET_CAP]
    if not p:
        return None
    return {"$where": f"permitnumber in ({', '.join(repr_q(x) for x in p)}) AND novnumber IS NOT NULL",
            "$select": "permitnumber,novnumber,novcode,inspectiondate,inspectiontype,inspectionresulttype",
            "$order": "inspectiondate DESC", "$limit": "1000"}


def nov_link_row(rec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """A dot_nov_permits document from one inspection record, or None."""
    nov, permit = _v(rec, "novnumber"), _v(rec, "permitnumber")
    if not nov or not permit:
        return None
    return {"_id": nov, "permit_number": permit,
            "inspection_date": _v(rec, "inspectiondate") or None,
            "inspection_type": _v(rec, "inspectiontype") or None,
            "inspection_result": _v(rec, "inspectionresulttype") or None,
            "nov_code": _v(rec, "novcode") or None}


# ── Renewal chain ───────────────────────────────────────────────────────────

CHAIN_CAP = 50


def renewed_by(row: Dict[str, Any], others: Iterable[Dict[str, Any]]) -> Optional[str]:
    """The permit number that renews this one, or None. `others`: stored-log
    shaped permits (number, status, previous_permit). Renewed when DOT set
    nextpermitnumber (unless that renewal is known VOIDED), or when another
    permit names this one as its previouspermitnumber and is not voided."""
    num = str(row.get("number") or "").strip()
    others = [o for o in others or [] if isinstance(o, dict)]
    by_num = {str(o.get("number") or "").strip(): o for o in others if o.get("number")}
    nxt = str(row.get("next_permit") or "").strip()
    if nxt:
        o = by_num.get(nxt)
        if o is None or not permit_is_voided(o.get("status")):
            return nxt
    for o in others:
        onum = str(o.get("number") or "").strip()
        if (onum and onum != num and str(o.get("previous_permit") or "").strip() == num
                and not permit_is_voided(o.get("status"))):
            return onum
    return None


def chain_wanted(rows: Iterable[Dict[str, Any]]) -> tuple:
    """(next numbers to read, permit numbers to look up as someone's
    previouspermitnumber) for a project's stored permits, capped."""
    permits = [r for r in rows or [] if isinstance(r, dict)
               and str(r.get("record_type") or "") == "dot_permit"
               and r.get("number") and match_state(r) != STATE_REJECTED]
    known = {str(r["number"]) for r in permits}
    nexts = sorted({str(r["next_permit"]) for r in permits
                    if r.get("next_permit") and str(r["next_permit"]) not in known})
    live = [r for r in permits if not r.get("next_permit") and (
        permit_is_active(r.get("status"))
        or str(r.get("status") or "").strip().upper().startswith("EMERGENCY"))]
    live.sort(key=lambda r: str(r.get("work_end") or r.get("expiration_date") or "9999"))
    prevs = list(dict.fromkeys(str(r["number"]) for r in live))
    return nexts[:CHAIN_CAP], prevs[:CHAIN_CAP]


def chain_params(nexts: Iterable[str], prevs: Iterable[str]) -> Optional[Dict[str, str]]:
    """ONE tqtj-sjs8 request completing the chains: the renewals named by
    nextpermitnumber (their status), and any permit naming ours as previous."""
    parts = []
    n = [f"'{_q(str(x))}'" for x in nexts or []]
    p = [f"'{_q(str(x))}'" for x in prevs or []]
    if n:
        parts.append(f"permitnumber in ({', '.join(n)})")
    if p:
        parts.append(f"previouspermitnumber in ({', '.join(p)})")
    if not parts:
        return None
    return {"$where": " OR ".join(parts), "$order": "permitissuedate DESC", "$limit": "200"}


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


SEGMENT_MONTHS = 24
SEGMENT_LIMIT = "400"


def months_ago(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 - n, 12)
    return date(d.year + y, m + 1, min(d.day, 28))


def _street_like(on: str) -> str:
    """onstreetname LIKE the street's longest word, for each of its names
    (DOT pads and abbreviates; the match itself is done here, exactly)."""
    words = [max(n.split(), key=len) for n in _renamed(norm_street(on)) if n.split()]
    return " OR ".join(f"upper(onstreetname) like '%{_q(w)}%'" for w in dict.fromkeys(words))


def segment_queries(setup: Any, today: date) -> List[Dict[str, Any]]:
    """One tqtj-sjs8 request per confirmed frontage's on-street: borough +
    on-street + issued within 24 months, newest first, $limit 400. Every
    permit on the street comes back; classify_permit keeps the frontage's."""
    out, seen = [], set()
    since = months_ago(today, SEGMENT_MONTHS).isoformat() + "T00:00:00"
    for f in confirmed_frontages(setup):
        boro, on = BORO_NAME.get(str(f.get("boro") or "")), norm_street(f.get("on"))
        if not boro or not on or (boro, on) in seen:
            continue
        seen.add((boro, on))
        out.append({"dataset": PERMIT_DATASET, "kind": "dot_permit", "segment": True, "params": {
            "$where": f"boroughname = '{boro}' AND ({_street_like(on)}) "
                      f"AND permitissuedate >= '{since}'",
            "$order": "permitissuedate DESC", "$limit": SEGMENT_LIMIT}})
    return out


def cross_street_params(boro: str, on: str, today: date) -> Optional[Dict[str, str]]:
    """The cross streets DOT has published for a street (setup suggestion when
    no permit is matched yet): ONE grouped request."""
    name = BORO_NAME.get(str(boro or ""))
    if not name or not norm_street(on):
        return None
    since = months_ago(today, SEGMENT_MONTHS).isoformat() + "T00:00:00"
    return {"$select": "fromstreetname,tostreetname,count(*)",
            "$where": f"boroughname = '{name}' AND ({_street_like(on)}) "
                      f"AND permitissuedate >= '{since}'",
            "$group": "fromstreetname,tostreetname",
            "$order": "count(*) DESC", "$limit": "200"}


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


def _num(v: Any) -> Optional[float]:
    """A dataset amount as a number (an int when whole), or None."""
    n = _money(v)
    if n is None:
        return None
    return int(n) if n == int(n) else n


def summons_charges(rec: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Charges 1-10 that carry a code: [{code, section, description, amount}]."""
    out = []
    for i in range(1, 11):
        code = _v(rec, f"charge_{i}_code")
        if not code:
            continue
        out.append({"code": code, "section": _v(rec, f"charge_{i}_code_section") or None,
                    "description": _v(rec, f"charge_{i}_code_description") or None,
                    "amount": _num(rec.get(f"charge_{i}_infraction_amount"))})
    return out


_DEFAULT_WORDS = re.compile(r"\bDEFAULT(?:ED)?\b|\bDOCKET(?:ED)?\b")


def default_result(row: Dict[str, Any]) -> Optional[str]:
    """'DEFAULTED' / 'DOCKETED' when the summons' hearing result (or status:
    DOT writes DOCKETED there) says so, else None."""
    words = " ".join(str((row or {}).get(k) or "").upper() for k in ("hearing_result", "hearing_status"))
    found = {m.group(0)[:6] for m in _DEFAULT_WORDS.finditer(words)}
    if "DOCKET" in found:          # the later stage wins: docketed after a default
        return "DOCKETED"
    return "DEFAULTED" if "DEFAUL" in found else None


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
                # Phase 1 A: money as numbers (they were strings), every charge,
                # the hearing in full, and DOT's own date as a calendar date
                # (issued_on drives the 2-day new-summons rule).
                "penalty_imposed": _num(rec.get("penalty_imposed")),
                "balance_due": _num(rec.get("balance_due")),
                "total_amount": _num(rec.get("total_violation_amount")),
                "paid_amount": _num(rec.get("paid_amount")),
                "charges": summons_charges(rec),
                "issued_on": (_v(rec, "violation_date") or "")[:10] or None,
                "hearing_time": _v(rec, "hearing_time") or None,
                "hearing_location": _v(rec, "scheduled_hearing_location") or None,
                "decision_date": _v(rec, "decision_date") or None,
                "location": _v(rec, "violation_location_street_name") or None,
                "house": _v(rec, "violation_location_house") or None,
                "respondent": _v(rec, "respondent_last_name") or None,
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
                # The work window: start and end. The holiday embargo check
                # (lib/dot_embargo.py) asks whether it overlaps Nov 15 - Jan 2.
                "work_start": _v(rec, "issuedworkstartdate") or None,
                "expiration_date": _v(rec, "issuedworkenddate") or None,
                # Phase 1 B. work_end IS expiration_date (both kept: every
                # existing reader asks for expiration_date).
                "work_end": _v(rec, "issuedworkenddate") or None,
                "series": _v(rec, "permitseriesshortdesc") or None,
                "permit_type": _v(rec, "permittypedesc") or None,
                "segment": permit_segment(rec),
                "previous_permit": _v(rec, "previouspermitnumber") or None,
                "next_permit": _v(rec, "nextpermitnumber") or None,
                # renewed_by is NOT set here: it needs the other permits of
                # the chain (renewed_by()), and the sync stores it after the
                # chain read -- a record arriving alone must not erase it.
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
