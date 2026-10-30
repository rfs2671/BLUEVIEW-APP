Ruling 154 standing probes (read-only). Run: `bash run.sh <backend tree> <out dir>`.
Baselines on the #936 tip are in baselines.json: value grid 186 claims, 156 bound on main -> 130 with the fix (26 bound->refused, 0 refused->bound); census count-shaped claims A-400 interior doors 56 -> 34, A-500 300 -> 182, windows 4 -> 4.
Step-3 rule for the record (NOT built): an untagged claim through a multi-tag ID-less grid binds only if all candidate cells agree, or exactly one candidate exists. Measured now: 90 untagged claims bind; 67 have every tag agreeing; 23 cover a family whose tags print different values (they bind on one tag's cell only).
No blank-header-column adjacency attribution (Roy): geometry span only, step 3.
