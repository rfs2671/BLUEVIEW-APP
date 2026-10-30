Ruling 154 standing probes (read-only). Run: `bash run.sh <backend tree> <out dir>`.
Baselines on the #936 tip are in baselines.json: value grid 186 claims, 156 bound on main -> 130 with the fix (26 bound->refused, 0 refused->bound); census count-shaped claims A-400 interior doors 56 -> 34, A-500 300 -> 182, windows 4 -> 4.
Step-3 rule for the record (NOT built): an untagged claim through a multi-tag ID-less grid binds only if all candidate cells agree, or exactly one candidate exists. Measured now: 90 untagged claims bind; 67 have every tag agreeing; 23 cover a family whose tags print different values (they bind on one tag's cell only).
No blank-header-column adjacency attribution (Roy): geometry span only, step 3.

Step 3 (branch fix/idless-untagged-claim-all-agree): an untagged claim in a multi-tag ID-less grid binds only if every candidate cell of the family (every tag column and every blank-header column; no adjacency attribution) prints the figure, or the family is one cell. Baselines in baselines.json under "step3"; the 32 refused untagged claims are in step3_untagged_diff.json.
