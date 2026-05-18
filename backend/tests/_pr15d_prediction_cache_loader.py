"""PR #15D — load prediction_cache snapshot fixtures saved at Stage 1.

Filename starts with ``_`` so pytest's default collector skips it.

Fixtures live at:
  backend/tests/fixtures/atlas_snapshots/prediction_cache_<name>_<id_short>.json

Each file contains the full project doc (with embedded prediction_cache)
serialized via ``bson.json_util.dumps`` so ObjectId + datetime
round-trip correctly when reloaded with ``bson.json_util.loads``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from bson import json_util

_HERE = Path(__file__).resolve().parent
_FIXTURES = _HERE / "fixtures" / "atlas_snapshots"


def load_prediction_cache_fixture(name: str) -> Dict[str, Any]:
    """Load a saved prediction_cache snapshot by short project name.

    ``name`` matches the filename infix; e.g. ``"menahan"`` matches
    ``prediction_cache_menahan_69e7c100.json``. Raises
    FileNotFoundError with actionable guidance if missing.
    """
    paths = sorted(_FIXTURES.glob(f"prediction_cache_{name}_*.json"))
    if not paths:
        raise FileNotFoundError(
            f"No prediction_cache snapshot for {name!r} in {_FIXTURES}. "
            f"Operator: re-run PR #15D Stage 1 Probe E to regenerate."
        )
    return json_util.loads(paths[0].read_text(encoding="utf-8"))


def available_snapshots() -> list[str]:
    """Short-name list of available prediction_cache snapshots."""
    return sorted(
        p.stem.split("_")[2]
        for p in _FIXTURES.glob("prediction_cache_*.json")
    )
