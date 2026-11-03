# plan_reader_model_v10 (588 Thomas S Boyland model export scripts, v1.0 and v1.0.1/v10b)

One-off scripts that produced C:/Users/asddd/bv-worktrees/model_export_v10 and model_export_v10b (local, outside the repo). Scripts use absolute paths under C:/Users/asddd/bv-worktrees and C:/Users/asddd/boyland-pdfs; they are kept here as the committed record of how the numbers were produced, not as app code. Nothing here is imported by the backend.

- v1.0: build_v10.py, verify_v10.py, make_box_beam_designations.py, sw45_panel_check.py (SW 4&5 X-panel quad coordinates, ST - 7.29.26.pdf p12; output sw45_panel_check_output.json).
- v1.0.1 (v10b): apply_v10b.py (PM rulings + corrections applied to a copy of v10), make_discrepancies_v10b.py, make_verify_v10b.py + verify_v10b_tail.py -> verify_v10b.py, thickness_stroke_test.py, w1_pairing_trace.py, sw_panel_heights.py.
- pitch_v2/: sensitivity.py, make_pitch_v2.py (pitchmap method re-run; pitchmap itself untouched).
