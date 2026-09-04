# Sweep proposal — orphaned `document_page_index` rows and their R2 objects

**Status: PROPOSAL. Nothing has been run. Nothing may be run until the leak is
closed and the operator has read a dry run.**

Measured against production 2026-09-04, read-only.

---

## 1. Why the sweep is second, not first

`DELETE /projects/{project_id}/files/{file_id}` deleted the R2 source object and
the `project_files` row and touched nothing else, so every call left one
`document_page_index` row per page and one rendered image per page behind. A
sweep against a path that keeps producing more is a treadmill.

`fix/file-delete-leaves-no-orphans` closes it. **This proposal assumes that has
shipped.** If it has not, the counts below are a floor.

## 2. Owner

**The platform operator, and nobody else.** The same gate `hard_delete_project`
uses (`require_platform_operator`). This deletes rows an admin cannot see and
cannot restore; a project-scoped admin has no way to judge whether an orphan is
a replaced drawing or a mistake, which is exactly the judgement §5 needed.

## 3. The keep-set

The rule this codebase already uses for `sweepDocCache`, in the same direction:
**delete only what nothing names, and refuse to act on a set you could not
read.**

```
live_file_ids = { str(_id) for project_files where is_deleted != true }
orphan_rows   = document_page_index where file_id NOT IN live_file_ids
```

Three refusals, all of which mean "do nothing this run":

1. **`project_files` read failed or returned zero rows.** An empty live set
   makes every index row an orphan. That is the cache-shredder shape the
   manifest store already documents at length, and it must abort rather than
   proceed.
2. **A row whose `file_id` is unparseable as an ObjectId.** It cannot be proven
   absent, so it is kept.
3. **Any orphan whose `project_id` names a project that still exists AND whose
   `file_name` matches a LIVE `project_files` row in that project.** That is
   the replacement case (§5) and it is the one where a human should look first.

R2 objects are removed only for rows the sweep is deleting, via the existing
`_r2_delete_prefix(client, bucket, f"plans/{project_id}/{file_id}/")` — one
prefix per orphaned file, which takes derivatives nobody has enumerated.

## 4. Dry run first, and what it must print

`--dry-run` is the default; deleting requires an explicit flag. It reports,
before touching anything:

| per orphaned file | |
|---|---|
| `file_id` | |
| `file_name` as the index remembers it | |
| `project_id` and the project's current name | |
| index rows | count |
| R2 objects under the prefix | count and total bytes, from `list_objects_v2` |
| upload time | from the ObjectId |
| index window | `min(indexed_at)` → `max(indexed_at)` |
| a live file with the same name in that project? | yes/no + its id and date |

and a total. **The operator reads that output and approves before anything is
deleted.**

## 5. What the dry run will say today

**8 orphaned files, 44 index rows, 24 R2 objects, 74.6 MB** — all of the bytes
belong to one file.

| file | rows | objects | uploaded | project |
|---|---|---|---|---|
| `AR - 3.28.25.pdf` | 26 | 24 | 2026-08-27 | 588 Thomas |
| `MH - 4.16.25 (3).pdf` | 7 | 0 | 2026-04-17 | (other) |
| `SP%20-%203.26.25%20(2).pdf` | 6 | 0 | 2026-04-17 | (other) |
| `levelog_upload_test.pdf` | 1 | 0 | 2026-04-17 | (other) |
| `levelog_upload_valid.pdf` | 1 | 0 | 2026-04-17 | (other) |
| `presigned_test.pdf` | 1 | 0 | 2026-04-17 | (other) |
| `final_e2e.pdf` | 1 | 0 | 2026-04-17 | (other) |
| `test_warning_modal.pdf` | 1 | 0 | 2026-04-17 | (other) |

Seven of the eight are from 2026-04-17 and carry **no R2 objects at all** —
they predate per-page image storage. Five are named as test uploads.

### `AR - 3.28.25.pdf` — asked for by name, and it is a REPLACEMENT

| | orphan | live |
|---|---|---|
| `file_id` | `6a902d95cda47e90e7b6b1cd` | `6a90ebce1df3e1f2588018a2` |
| uploaded | **2026-08-27 12:29:09** | **2026-08-28 02:00:41** |
| indexed | 12:29:56 → 12:38:23, 26 pages | (current) |
| size | — | 31,699,779 |

**The same drawing set was uploaded on the 27th, indexed, then re-uploaded
about thirteen and a half hours later on the 28th, and the first copy deleted.**
A superseded revision, not a lost plan — the project holds a live
`AR - 3.28.25.pdf` today, and it is the one being served.

**THE DELETION DATE CANNOT BE RECOVERED, AND THE REASON IS A MISSING ACTION
RATHER THAN A MISSING LOG.** `audit_logs` is live and healthy — 559 rows, most
recent today, 2026-09-04 15:56 — and carries 16 distinct actions including
`project_delete`, `project_mark_delete`, `company_hard_delete` and `user_delete`.

**There is no file-level action among them.** Deleting a project is audited;
deleting a plan out of a project never was. Nothing in the collection references
the orphan `file_id`, so the only bound on the deletion is "after the index
finished at 12:38 on the 27th", and the re-upload at 02:00 on the 28th is the
only other marker.

`fix/file-delete-leaves-no-orphans` adds `project_file_delete`, the first
file-level action this log has had. That is what makes the question answerable
next time — and it is the reason a soft delete of the index row is not the way
to preserve the fact: the fact belongs in the audit log, not in a stale
searchable row pointing at bytes the same call destroyed.

> **How this was nearly reported wrong.** The first query counted rows in
> `db.audit_log`. The collection is `db.audit_logs`. A nonexistent collection
> returns zero, so "no audit rows exist" was about to be published on an empty
> set that proved nothing — the exact shape of the empty-set entry in
> `docs/audits/followups.md`. And the corrected query's first filter,
> `action =~ /file/i`, returned 2 — both `profile_phone_change`, because
> **pro-file** contains "file". Two ways to be wrong about the same fact
> before the real answer (enumerate the distinct actions and read them) came
> out. Substring matching over-reports; a query against the wrong name
> under-reports; neither announces itself.

Note also that this file's two remaining index rows are among the seven
`is_spec_page` pages, so the orphan overlaps the spec-page finding.

## 6. Order of operations

1. `fix/file-delete-leaves-no-orphans` merges and deploys. **Verify against
   `/api/version`, not the commit date.**
2. Dry run. Operator reads it.
3. Re-run the dry run after approval — the set may have moved — and diff it
   against the approved output. **A set that changed is not approved.**
4. Delete, one file at a time, logging each: `file_id`, rows removed, objects
   removed, bytes.
5. Re-run the dry run. It must report zero.

## 7. What is deliberately NOT in scope

- **`temp/whatsapp/{group_id}/*.jpg`.** Written on every plan-image send and
  never enumerated by any DB row. Almost certainly its own leak, unmeasured,
  and it is not this sweep's business.
- **Backfilling anything.** Nothing is reconstructed; rows are removed or kept.
- **The 20 `index_version: 1` pages.** They belong to LIVE files and are a
  re-index question, not an orphan question.
