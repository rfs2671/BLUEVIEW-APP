# worker_project_trades backfill — runbook

Populates the per-worker-per-project `{trade, company}` pairing from check-in
history, so a returning worker is not re-prompted for a trade the site already
knows.

These are **mongosh** scripts, so they are `.js` — the first non-Python scripts
in this directory. They are here rather than in a session scratchpad because a
script that runs against production must outlive the session that wrote it.

Both are safe by default: `audit_company_values.js` never writes, and
`backfill_worker_project_trades.js` is dry-run unless you edit it.

---

## Order

Run step 1 first. Step 2 is the only one that writes.

### 1. Audit company values — read only

```bash
mongosh "$ATLAS_URI" --file backend/scripts/audit_company_values.js
```

Writes nothing. Prints distinct company spellings per source, collision groups
(different spellings that normalize to one company), and the blank-company count.

**What to look for.** A high collision count means step 2 will hit more
ambiguous company values, which it deliberately stores as blank rather than
guessing. Blank company is a legitimate bucket by operator ruling — it is not an
error and must not be backfilled.

### 2. Backfill the pairings — dry run, then execute

```bash
mongosh "$ATLAS_URI" --file backend/scripts/backfill_worker_project_trades.js
```

Dry run. Prints every pairing it would write plus three counts: would-write,
skipped-already-exists, skipped-conflicting.

**Before executing, read the conflict list.** Those are workers showing two
different trades on the same project. Nothing is written for them; they need a
human decision.

To execute, set `EXECUTE = true` at the top of the script and re-run.

---

## The three rules, all enforced in code

1. **`UNASSIGNED` is never stored.** A worker whose history is UNASSIGNED-only
   gets no pairing. Writing one would make the gate stop flagging a trade
   assignment the CP still owes — the flag is the point.
2. **Conflicts are listed, not resolved.** Two trades on one project is a
   question for a person, not a tiebreak rule.
3. **Live data wins.** Uses `$setOnInsert`, so a pairing already written by a
   real check-in is never overwritten by inferred history.

## Reversibility

Cleanly reversible. The backfill only ever inserts, never updates. Delete the
inserted rows and you are back where you started.

## Schema

Matches `_store_worker_project_trade` in `backend/server.py`:

```
{ worker_id: str, project_id: str, trade: str, company: str, updated_at: date }
```

Unique compound index on `(worker_id, project_id)` — created at startup as
`worker_project_trades_worker_project_unique`.
