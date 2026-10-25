# Sample progress report

`progress_report_588.pdf` (+ `_no_schedule.pdf`, page PNGs, WhatsApp text) is rendered by
`backend/scripts/render_report_sample.py` from the **test fixture** `backend/tests/report_588.py`.
It is **not** production data and has **no photographs** (the repository holds none and none are
drawn or generated). Its purpose is to show layout, wording and gating.

A real report is produced read-only with `backend/scripts/real_report_dry_run.py` against a
read-only database user (see its docstring). It was not run for the committed sample because no
production database credentials exist in the build environment.
