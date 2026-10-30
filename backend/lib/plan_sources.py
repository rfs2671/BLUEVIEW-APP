"""Where a sheet comes from: its file, its drawing set, and what the
drawing list says about it.

Oct 27, the owner on WhatsApp: asked about EN-001 / EN-002, then "what file
is it on", then "send me the PDF". The evidence the brain was handed named
the sheet and nothing else, so neither question had an answer.

This module is DATA AND RENDERING ONLY. Nothing here binds, withholds or
ranks a record, and nothing here decides whether an answer may assert
something (plan_search / plan_emit do that, unchanged). It adds three things
to what the model is shown:

  * THE FILE AND THE SET. A drawing set is `project_files.drawing_track`
    ("filed" | "post_co", server.DRAWING_TRACKS; no track is the filed set)
    with `drawing_track_label`, set per file by a company admin. There is no
    other set field: a "design plans" set is not something the system
    records, so none is named here.
  * A NON-FILED SHEET NAMES ITS SET where it is cited: "A-302 (owner's set)".
  * A SHEET THAT BORROWS ITS NUMBER SAYS SO (ruling 136): a page the office
    recorded as REPLACING another (lib.plan_set_questions, answer "replaces")
    whose own title block prints no sheet number is read as the replaced
    sheet's number, and is cited as it is: 'A-105.01 (gas-change set,
    unnumbered) "Roof Plan"'.
  * THE DRAWING LIST against the sheets: a sheet's own title block wins over
    the list's title for it (the list's title may be mentioned), and sheets
    the list names that were never uploaded are said to be just that.

Pure: no database, no network.
"""

from __future__ import annotations

import io
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

FILED = "filed"
#: How a set is named in an answer (project_files.drawing_track).
SET_NAMES = {FILED: "filed set", "post_co": "owner's set"}

#: The largest PDF send_plan_file sends in one WhatsApp message. The
#: temp-media proxy reads the object whole to serve it, so this is a limit of
#: this system (not of WhatsApp's own 100 MB), and it is said as one.
MAX_SEND_MB = 25
MAX_SEND_BYTES = MAX_SEND_MB * 1024 * 1024
#: Pages one send_plan_file range may extract.
MAX_RANGE_PAGES = 60


# ── THE FILE AND THE SET ─────────────────────────────────────────────────────

def source_of(file_row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """{file_id, file_name, track, set_name, filed, label} for a
    `project_files` row, or None without one."""
    if not file_row:
        return None
    track = str(file_row.get("drawing_track") or FILED).strip().lower() or FILED
    label = re.sub(r"\s+", " ", str(file_row.get("drawing_track_label") or "")).strip()
    set_name = SET_NAMES.get(track) or (label or f"{track} set")
    return {"file_id": str(file_row.get("_id") or ""),
            "file_name": str(file_row.get("name") or "").strip(),
            "track": track, "set_name": set_name, "filed": track == FILED,
            "label": label}


def set_tag(src: Optional[Dict[str, Any]]) -> str:
    """" (owner's set)" for a sheet from a set that is not the filed one;
    "" for the filed set or no source."""
    if not src or src.get("filed"):
        return ""
    return f" ({src.get('set_name') or 'other set'})"


def cite_with_set(where: str, src: Optional[Dict[str, Any]]) -> str:
    """A citation that names a non-filed set: "A-302 (owner's set)"."""
    return f"{where}{set_tag(src)}" if where else where


def evidence_where(where: str, src: Optional[Dict[str, Any]], *, sheet_number: str = "",
                   page_number: Any = None) -> str:
    """The bracket a record is shown to the model with: the citation (its
    set named when it is not the filed one), then the file and page, then
    "filed set" for the filed one. Without a source, the citation as is."""
    if not src:
        return where
    out = cite_with_set(tag_sheet(where, src, page_number) if (sheet_number or "").strip() else where, src)
    if (sheet_number or "").strip() and src.get("file_name"):
        out += f" · {src['file_name']}" + (f" p{page_number}" if page_number is not None else "")
    if src.get("filed"):
        out += " · filed set"
    return out


def sheet_source_text(sheet: str, src: Optional[Dict[str, Any]], page_number: Any = None) -> str:
    """"EN-001 is page 3 of MEP set.pdf (filed set)." -- what file a sheet is on."""
    if not src or not src.get("file_name"):
        return ""
    page = f"page {page_number} of " if page_number is not None else ""
    return f"{sheet} is {page}{src['file_name']} ({src['set_name']})."


# ── A SHEET THAT BORROWS ITS NUMBER (ruling 136) ─────────────────────────────
#
# Q2 on 588 Boyland: the gas-change file's page 2 prints no sheet number (its
# title block reads "Roof Plan"); the office recorded that it REPLACES A-105.01,
# so the glyph pass writes its rows as sheet A-105.01. A row carries no marker
# that the number was lent, and a citation "A-105.01 · AR - 6.9.26 (Gas
# change).pdf p2" reads as if the sheet printed it. Nothing is stored for this:
# it is derived, at render or query time, from the answered replaces questions
# and the replacing page's own index record (server._unnumbered_marks), and
# rides on the file's source row under UNNUMBERED_KEY -- {page_number: mark} --
# so every renderer that already holds the source can say it. DATA AND
# RENDERING ONLY: no row, count or binding changes (the gate removes the tag
# with the other citations: plan_search.strip_source_citations).

#: the key on a source_of row: {page number: {"sheet", "title", "set"}}
UNNUMBERED_KEY = "unnumbered"
#: a numbered replacing page (gas A-100.00) keeps its own number and gets no
#: tag: its number is printed on it, and the file name beside it says the file.
_DATE = re.compile(r"\b\d{1,2}\s*[./-]\s*\d{1,2}\s*[./-]\s*\d{2,4}\b")
_PARENS = re.compile(r"\(([^()]*)\)")
_TAG = re.compile(r'\s*\([^()]*,\s*unnumbered\)(?:\s*"[^"\n]*")?')


def set_name(file_name: Any, label: Any = "") -> str:
    """How a drawing set is named in a tag: "gas-change set". THE RULE: the
    set's own label when an admin gave it one; otherwise the file's name with
    its extension and its dates removed -- the last parenthesised phrase when
    the name has one ("AR - 6.9.26 (Gas change).pdf" -> "Gas change"), else
    what is left -- lower-cased, its words joined by hyphens, and " set"
    after it. "" when nothing is left (the tag then says only "unnumbered")."""
    lab = re.sub(r"\s+", " ", str(label or "")).strip()
    if lab:
        return lab
    stem = re.sub(r"\.pdf\s*$", "", str(file_name or "").strip(), flags=re.I)
    stem = _DATE.sub(" ", stem)
    inner = _PARENS.findall(stem)
    core = inner[-1] if inner else stem
    core = re.sub(r"[^\w\s'-]+|_", " ", core)
    words = [w.strip("-'") for w in core.split()]
    words = [w for w in words if w]
    if not words:
        return ""
    name = "-".join(words).lower()
    return name if name.endswith("set") else f"{name} set"


def unnumbered_tag(sheet: str, mark: Optional[Dict[str, Any]]) -> str:
    """'A-105.01 (gas-change set, unnumbered) "Roof Plan"' -- the borrowed
    number, what the page is, and its printed title."""
    if not mark:
        return sheet
    out = f"{sheet} ({mark['set']}, unnumbered)" if mark.get("set") else f"{sheet} (unnumbered)"
    if mark.get("title"):
        out += f' "{mark["title"]}"'
    return out


def unnumbered_mark(src: Optional[Dict[str, Any]], sheet: Any, page_number: Any) -> Optional[Dict[str, Any]]:
    """The mark for a record on (source file, page) whose sheet number is
    `sheet`: only when the page is a replacing page that prints no number AND
    the record carries the number it was given -- a pass that could not apply
    the answer wrote no such number, and nothing is claimed then."""
    marks = (src or {}).get(UNNUMBERED_KEY)
    if not marks or page_number is None:
        return None
    try:
        mark = marks.get(int(page_number))
    except (TypeError, ValueError):
        return None
    if mark and sheet_key(sheet) and sheet_key(sheet) == sheet_key(mark.get("sheet")):
        return mark
    return None


def tag_sheet(sheet: str, src: Optional[Dict[str, Any]], page_number: Any) -> str:
    """`sheet` as a citation names it: with the unnumbered tag when it is the
    number a replacing page borrowed, else as given."""
    mark = unnumbered_mark(src, sheet, page_number)
    return unnumbered_tag(sheet, mark) if mark else sheet


def _places(r: Dict[str, Any]) -> Iterable[Tuple[str, str, Any]]:
    """(sheet, file_id, page_number) of a record and, for a mechanical symbol,
    of the architectural page it is placed on (payload.arch)."""
    yield str(r.get("sheet_number") or "").strip(), str(r.get("file_id") or ""), r.get("page_number")
    a = (r.get("payload") or {}).get("arch") if isinstance(r.get("payload"), dict) else None
    if isinstance(a, dict) and a.get("sheet_number"):
        yield str(a.get("sheet_number")).strip(), str(a.get("file_id") or ""), a.get("page_number")


def borrowed_labels(records: Iterable[Dict[str, Any]], sources: Optional[Dict[str, Dict[str, Any]]]
                    ) -> Dict[str, str]:
    """{sheet: its tagged citation} for the sheet numbers the records name
    that a replacing page borrowed -- for the evidence blocks that name a
    SHEET with no file or page beside it (the located-symbol, opening, area
    and set-health text). Only when EVERY place the records give for that
    sheet number is the marked page: the same number on another page (the
    page it replaced, still indexed) leaves the bare number, since the text
    cannot say which page it means."""
    if not sources or not any((s or {}).get(UNNUMBERED_KEY) for s in sources.values()):
        return {}
    places: Dict[str, List[Optional[Dict[str, Any]]]] = {}
    for r in records or []:
        for sheet, fid, page in _places(r):
            if sheet:
                places.setdefault(sheet, []).append(unnumbered_mark(sources.get(fid), sheet, page))
    return {sheet: unnumbered_tag(sheet, marks[0]) for sheet, marks in places.items()
            if marks and all(m is not None for m in marks)}


def label_borrowed(text: str, labels: Dict[str, str]) -> str:
    """`text` with each standalone sheet number in `labels` replaced by its
    tagged citation."""
    for sheet, tagged in labels.items():
        text = re.sub(r"(?<![\w.-])" + re.escape(sheet) + r"(?![\w-]|\.\d)",
                      lambda _m, t=tagged: t, text)
    return text


def without_tags(text: Any) -> str:
    """`text` with every unnumbered tag removed ("A-105.01 (gas-change set,
    unnumbered) "Roof Plan"" -> "A-105.01"): what the gate reads figures from."""
    return _TAG.sub("", str(text or ""))


def unnumbered_marks(decisions: Iterable[Dict[str, Any]], pages: Dict[str, Dict[str, Any]],
                     files: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[int, Dict[str, Any]]]:
    """{file_id: {page_number: mark}} from the ANSWERED replaces questions
    (`decisions`), the replacing pages' own index records (`pages`, by page id)
    and the project's files (`files`, by id: name, drawing_track_label).
    UNNUMBERED means the page's own index record has no sheet number; the
    number it is read as is the one the office gave it (takes_sheet_number,
    else the replaced sheet's). A numbered page, or a record that is missing,
    is not marked."""
    out: Dict[str, Dict[int, Dict[str, Any]]] = {}
    for d in decisions or []:
        if d.get("answer") != "replaces" or d.get("status", "answered") != "answered":
            continue
        for r in d.get("replacements") or []:
            page = pages.get(str(r.get("page_id"))) or {}
            if not page or str(page.get("sheet_number") or "").strip():
                continue
            sheet = str(r.get("takes_sheet_number") or (r.get("replaces") or {}).get("sheet_number")
                        or "").strip()
            try:
                number = int(page.get("page_number") if page.get("page_number") is not None
                             else r.get("page_number"))
            except (TypeError, ValueError):
                continue
            fid = str(page.get("file_id") or r.get("file_id") or "")
            if not sheet or not fid:
                continue
            f = files.get(fid) or {}
            out.setdefault(fid, {})[number] = {
                "sheet": sheet,
                "title": re.sub(r"\s+", " ", str(page.get("sheet_title") or "")).strip(),
                "set": set_name(page.get("file_name") or f.get("name"), f.get("drawing_track_label"))}
    return out


# ── THE DRAWING LIST ─────────────────────────────────────────────────────────

_SHEET = re.compile(r"^\s*([A-Z]{1,4})\s*-?\s*(\d{1,4}[A-Z]?)(?:\.(\d{1,3}))?\s*$")
_HAS_WORD = re.compile(r"[A-Za-z]{2,}")
_DATE_OR_REV = re.compile(r"^\s*(?:\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|rev\.?\s*\w+|\d+)\s*$", re.I)


def sheet_key(sheet: Any) -> str:
    """One form of a sheet id: "EN 001" / "EN001" / "EN-001.00" -> "EN-001";
    "A-101.01" keeps its ".01". "" when it is not shaped like one."""
    m = _SHEET.match(str(sheet or "").upper())
    if not m:
        return ""
    sub = m.group(3)
    return f"{m.group(1)}-{m.group(2)}" + (f".{sub}" if sub and int(sub) != 0 else "")


def _norm_title(t: Any) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", str(t or "").upper()).split())


def drawing_list(records: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, str]]:
    """{sheet key: {sheet, title, on}} from the drawing list's rows: index
    records (plan_search.is_index_record, decided by the caller) whose rows
    carry a sheet id and, after it, its title. The first listing of a sheet
    is kept."""
    out: Dict[str, Dict[str, str]] = {}
    for r in records or []:
        payload = r.get("payload") if isinstance(r.get("payload"), dict) else {}
        for row in payload.get("rows") or []:
            if not isinstance(row, list):
                continue
            cells = [str(c or "").strip() for c in row]
            at = next((i for i, c in enumerate(cells) if sheet_key(c)), None)
            if at is None:
                continue
            key = sheet_key(cells[at])
            words = [c for c in cells[at + 1:] if _HAS_WORD.search(c) and not _DATE_OR_REV.match(c)]
            title = max(words, key=len) if words else ""
            if key not in out:
                out[key] = {"sheet": cells[at].strip(), "title": re.sub(r"\s+", " ", title),
                            "on": str(r.get("sheet_number") or "")}
    return out


def _prefix(key: str) -> str:
    return key.split("-", 1)[0] if "-" in key else ""


def list_notes(sheet: str, own_title: str, listed: Dict[str, Dict[str, str]],
               uploaded: Iterable[str]) -> List[str]:
    """What the drawing list adds about `sheet`, as lines for the model:

    * the sheet's own title block wins: when the list titles it differently,
      the line says which is the sheet's title and that the list's may be
      mentioned as the list's;
    * the asked sheet listed but not uploaded, said so;
    * other sheets of its series (same letters) listed but not uploaded:
      "EN-003, EN-004 are listed in the drawing list but not uploaded."
    """
    key = sheet_key(sheet)
    if not key or not listed:
        return []
    have = {sheet_key(s) for s in uploaded or []} - {""}
    lines: List[str] = []
    entry = listed.get(key)
    if entry and key in have:
        if own_title and entry.get("title") and _norm_title(own_title) != _norm_title(entry["title"]):
            lines.append(
                f"Title: the sheet's own title block reads \"{own_title}\" -- that is its title. "
                f"The drawing list calls {key} \"{entry['title']}\"; mention that only as the "
                f"drawing list's title.")
    elif entry:
        title = f" (\"{entry['title']}\")" if entry.get("title") else ""
        lines.append(f"{key}{title} is listed in the drawing list but not uploaded: there is no "
                     f"sheet to read or send.")
    missing = sorted(k for k in listed if _prefix(k) == _prefix(key) and k not in have and k != key)
    if missing:
        verb = "is" if len(missing) == 1 else "are"
        lines.append(f"{', '.join(missing)} {verb} listed in the drawing list but not uploaded.")
    return lines


# ── PAGE RANGES ──────────────────────────────────────────────────────────────

def parse_pages(spec: Any, page_count: Optional[int] = None) -> Tuple[List[int], str]:
    """("3-5, 8" -> [3, 4, 5, 8], "") -- 1-based PDF pages, in order, no
    repeats. ([], why) when it can't be read or is out of the file."""
    s = str(spec or "").strip().lower().replace("pages", "").replace("page", "").replace("pp.", "")
    s = s.replace("p.", "").replace("–", "-").replace("—", "-").replace(" to ", "-")
    if not s.strip():
        return [], "no pages given"
    s = re.sub(r"\s*-\s*", "-", s)
    pages: List[int] = []
    for part in re.split(r"[,;\s]+", s):
        part = part.strip()
        if not part:
            continue
        m = re.fullmatch(r"p?(\d{1,5})(?:-p?(\d{1,5}))?", part)
        if not m:
            return [], f"can't read the page range {spec!r}"
        a, b = int(m.group(1)), int(m.group(2) or m.group(1))
        if a < 1 or b < a:
            return [], f"can't read the page range {spec!r}"
        if len(pages) + (b - a + 1) > MAX_RANGE_PAGES:
            return [], f"that is more than {MAX_RANGE_PAGES} pages; send the whole file or a shorter range"
        for p in range(a, b + 1):
            if p not in pages:
                pages.append(p)
    if not pages:
        return [], f"can't read the page range {spec!r}"
    if page_count is not None and max(pages) > page_count:
        return [], f"the file has {page_count} pages"
    return pages, ""


def extract_pages(src_path: str, pages: Sequence[int]) -> Tuple[bytes, int]:
    """(a new PDF of `pages` -- 1-based -- of the PDF at `src_path`, the
    source's page count). Raises ValueError for a page past its end."""
    from pypdf import PdfReader, PdfWriter
    reader = PdfReader(src_path)
    count = len(reader.pages)
    if any(p < 1 or p > count for p in pages):
        raise ValueError(f"the file has {count} pages")
    writer = PdfWriter()
    for p in pages:
        writer.add_page(reader.pages[p - 1])
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue(), count


def pages_label(pages: Sequence[int]) -> str:
    """[3, 4, 5, 8] -> "pages 3-5, 8"; [3] -> "page 3"."""
    runs, start, prev = [], None, None
    for p in pages:
        if start is None:
            start = prev = p
        elif p == prev + 1:
            prev = p
        else:
            runs.append((start, prev))
            start = prev = p
    if start is not None:
        runs.append((start, prev))
    txt = ", ".join(f"{a}-{b}" if a != b else str(a) for a, b in runs)
    return ("page " if len(pages) == 1 else "pages ") + txt


def size_mb(n: Any) -> str:
    try:
        return f"{float(n) / (1024 * 1024):.1f} MB"
    except (TypeError, ValueError):
        return "unknown size"
