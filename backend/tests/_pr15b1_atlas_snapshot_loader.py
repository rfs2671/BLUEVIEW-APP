"""PR #15B.1 — Atlas project snapshot loader for canary tests.

Filename starts with ``_`` so pytest's default collector skips it.

Loads JSON files from ``backend/tests/fixtures/atlas_snapshots/`` via
``bson.json_util`` so ObjectId + datetime fields round-trip correctly.

Sanitization (T6'): the loader strips 4 categories of internal /
organizational fields before returning the dict so tests don't
silently depend on (or accidentally publish) operator-internal
state:

  • admin_id          — internal admin user ObjectId
  • company_id        — internal company ObjectId
  • report_email_list — operator email addresses (empty in all 5
                        snapshots at PR #15B.1 capture time but
                        could be populated on other projects)
  • dropbox_folder    — operator-configured path string

The raw JSON files retain these fields for forensic auditability;
the loader is the choke point that scrubs them before tests see them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from bson import json_util

_HERE = Path(__file__).resolve().parent
_FIXTURES = _HERE / "fixtures" / "atlas_snapshots"


_STRIP_FIELDS = {
    "admin_id",
    "company_id",
    "report_email_list",
    "dropbox_folder",
}


def _strip_sensitive(obj: Any) -> Any:
    """Recursively remove _STRIP_FIELDS from any dict in the tree."""
    if isinstance(obj, dict):
        return {
            k: _strip_sensitive(v) for k, v in obj.items()
            if k not in _STRIP_FIELDS
        }
    if isinstance(obj, list):
        return [_strip_sensitive(x) for x in obj]
    return obj


def load_atlas_snapshot(name: str) -> Dict[str, Any]:
    """Load a saved Atlas project document by short name.

    ``name`` matches the filename prefix; e.g. ``"menahan"`` matches
    ``menahan_69e7c100.json``. Raises FileNotFoundError with
    actionable guidance if the snapshot is missing.
    """
    paths = sorted(_FIXTURES.glob(f"{name}_*.json"))
    if not paths:
        raise FileNotFoundError(
            f"No Atlas snapshot for {name!r} in {_FIXTURES}. "
            f"Operator: run scripts/download_atlas_snapshots.sh "
            f"after creating the snapshot via "
            f"`railway run python backend/scripts/dump_atlas_snapshot.py "
            f"{name}=<object_id>`."
        )
    raw = paths[0].read_text(encoding="utf-8")
    doc = json_util.loads(raw)
    return _strip_sensitive(doc)


def list_available_snapshots() -> list[str]:
    """Return short-names of all snapshots present."""
    return sorted(p.stem.split("_")[0] for p in _FIXTURES.glob("*.json"))
