"""Remaining-work schedule ESTIMATE for 588 Thomas S. Boyland St, from local data.

    PYTHONUTF8=1 python backend/scripts/intel_588_schedule.py [DATA_DIR] [--model]

DATA_DIR (default: env INTEL588_DATA, else C:/Users/asddd/bv-worktrees/intel588-data)
holds drawings/building.json, records/588_records.jsonl, public/*.json and,
optionally, model/588_model.json (the state reconstruction). Writes
DATA_DIR/schedule/588_schedule.json and README.md. Real data never enters git:
this script reads and writes only DATA_DIR. No database, no network, no paid API.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import schedule_generator as G  # noqa: E402

DATA_DATE = date(2026, 11, 10)


def _load(data: Path):
    building = json.loads((data / "drawings" / "building.json").read_text(encoding="utf-8"))
    records = [json.loads(line) for line in (data / "records" / "588_records.jsonl").read_text(encoding="utf-8").splitlines()
               if line.strip()]
    inspections = json.loads((data / "public" / "dob_now_inspections_588.json").read_text(encoding="utf-8"))
    timeline = json.loads((data / "public" / "588_public_timeline.json").read_text(encoding="utf-8"))
    return building, records, inspections, timeline


def run(data: Path, use_model: bool) -> dict:
    building, records, inspections, timeline = _load(data)
    kw = dict(data_date=DATA_DATE, inspections=inspections, timeline=timeline,
              project="588 Thomas S. Boyland St, Brooklyn (Block 3540 Lot 25)")
    doc = G.generate(building, records, **kw)
    model_path = data / "model" / "588_model.json"
    doc["model_run"] = None
    if use_model and model_path.exists():
        model = json.loads(model_path.read_text(encoding="utf-8"))
        doc["model_run"] = G.model_run(building, records, model, **kw)
    elif use_model:
        doc["model_run"] = {"present": False, "note": f"{model_path} not present at run time"}
    return doc


def main(argv) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    data = Path(args[0] if args else os.environ.get("INTEL588_DATA", "C:/Users/asddd/bv-worktrees/intel588-data"))
    doc = run(data, use_model="--no-model" not in argv)
    out = data / "schedule"
    out.mkdir(parents=True, exist_ok=True)
    (out / "588_schedule.json").write_text(json.dumps(G.jsonable(doc), indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "README.md").write_text(G.readme(doc), encoding="utf-8")
    c = doc["completion"]
    print("TCO  fast", c["fast"]["tco"], " normal", c["normal"]["tco"], " conservative", c["conservative"]["tco"])
    print("activities", doc["network"]["counts"]["activities"], "links", doc["network"]["counts"]["links"])
    if doc.get("model_run") and doc["model_run"].get("completion"):
        m = doc["model_run"]["completion"]
        print("WITH 588_model.json: TCO fast", m["fast"]["tco"], " normal", m["normal"]["tco"], " conservative",
              m["conservative"]["tco"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
