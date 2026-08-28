/**
 * The Dropbox tree, as one shape shared by every screen that renders it.
 *
 * Plans and documents were two screens because they were two lists. They are
 * one tree: `/api/projects/{id}/dropbox-files` returns a FLAT array whose rows
 * each carry a `path`, and the folder structure is already in those paths. The
 * grouping below is the only thing that was ever missing, and app/site/
 * documents.jsx had been carrying a private copy of it.
 *
 * ── THE COUNTS DESCRIBE WHAT IS ON SCREEN, AND COME FROM ONE LIST ──────────
 *
 * `POST /sync-dropbox` returns a `file_count` taken from a recursive Dropbox
 * listing, and the screens use it for the "N files" line after a sync (#242).
 * That number is CORRECT for what Dropbox holds and WRONG for what the tree is
 * showing, because the background copy into project_files has not finished —
 * that is the same gap that once produced "3 files synced" on a folder of 15.
 *
 * So a headline reading "412 files in 9 folders" must take BOTH numbers from
 * the file list it is sitting above, never one from the list and one from the
 * sync response. Half a sentence from each source is a sentence that is true
 * of nothing. The count climbing as rows arrive is the honest behaviour: it
 * describes the tree, and the tree is what the reader is looking at.
 *
 * ── THE TREE MUST NOT ASSERT THAT TWO FILES ARE TWO FILES ──────────────────
 *
 * The sync writes R2 under `{company_id}/{project_id}/{filename}` from a
 * RECURSIVE listing (server.py, _sync_project_to_r2). The folder a file came
 * from is not in that key. So `Plans/A/plan.pdf` and `Plans/B/plan.pdf` are two
 * rows in project_files over ONE object in R2, and opening either one opens
 * whichever was copied last.
 *
 * A flat list hid this. A tree renders them side by side in two folders, which
 * is a stronger claim than the data supports. `collidingNames` finds them so
 * the screen can say what is actually true instead. The fix is the R2 key's,
 * and it is a backend change; until then the rule here is: do not assert
 * distinctness.
 */

export const UNFILED = '__unfiled__';

/**
 * The folder a file sits in, as a full path relative to the listing root.
 *
 * FULL PATH, not the immediate parent name. `Approved/Plans` and
 * `Superseded/Plans` are two different folders and collapsing both to "Plans"
 * merges them into one group that belongs to neither.
 */
export function folderPathOf(file) {
  const raw = String((file && file.path) || '');
  const parts = raw.split('/').filter(Boolean);
  parts.pop(); // drop the filename
  return parts.length ? parts.join('/') : UNFILED;
}

/** The last segment, for display when the full path is too long to show. */
export function folderLabel(folderPath) {
  if (folderPath === UNFILED) return 'Project root';
  const parts = String(folderPath).split('/').filter(Boolean);
  return parts.length ? parts[parts.length - 1] : 'Project root';
}

/**
 * Group a flat file list into [folderPath, files[]] pairs.
 *
 * Folders alphabetical, root-level files last; files alphabetical within a
 * folder. Deterministic order matters here — a tree that reshuffles between
 * renders is one the reader cannot learn.
 */
export function groupByFolder(files) {
  const list = Array.isArray(files) ? files : [];
  const byFolder = new Map();
  for (const f of list) {
    const key = folderPathOf(f);
    if (!byFolder.has(key)) byFolder.set(key, []);
    byFolder.get(key).push(f);
  }
  return [...byFolder.entries()]
    .sort(([a], [b]) => {
      if (a === UNFILED) return 1;
      if (b === UNFILED) return -1;
      return a.localeCompare(b);
    })
    .map(([folder, items]) => [
      folder,
      [...items].sort((x, y) =>
        String((x && x.name) || '').localeCompare(String((y && y.name) || ''))),
    ]);
}

/**
 * Both numbers, from one list.
 *
 * `folders` counts the GROUPS THIS TREE RENDERS, root-level files included as
 * one. It is a description of what is on screen, which is the only count that
 * can be checked by looking.
 */
export function treeCounts(files) {
  const groups = groupByFolder(files);
  return {
    files: groups.reduce((n, [, items]) => n + items.length, 0),
    folders: groups.length,
  };
}

/**
 * Basenames held by more than one row.
 *
 * Returns a Set of lowercased names. Case-insensitive because R2 keys are
 * built from the Dropbox `name` while Dropbox itself matches case-insensitively
 * — `Plan.pdf` and `plan.pdf` in two folders are the same collision.
 */
export function collidingNames(files) {
  const list = Array.isArray(files) ? files : [];
  const seen = new Map();
  for (const f of list) {
    const n = String((f && f.name) || '').toLowerCase();
    if (!n) continue;
    seen.set(n, (seen.get(n) || 0) + 1);
  }
  const out = new Set();
  for (const [n, count] of seen) if (count > 1) out.add(n);
  return out;
}

/** True when this row shares its filename with another row in the tree. */
export function isColliding(file, colliding) {
  const n = String((file && file.name) || '').toLowerCase();
  return Boolean(n && colliding && colliding.has(n));
}

/**
 * What to say about a colliding row. States the consequence, not the cause —
 * the reader cannot act on an R2 key, but he can act on "these open the same
 * document".
 */
export const COLLISION_NOTE =
  'Another file in this project has this name. The app stores one copy per '
  + 'filename, so both entries open the same document.';

/** "3:04 PM", or null when there is nothing to format. */
export function formatSyncedAt(value) {
  if (!value) return null;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
}

/**
 * "412 files in 9 folders · last synced 3:04 PM".
 *
 * NEVER a bare count under an ambiguous label: the sentence names both
 * quantities and what the timestamp refers to. When the folder has never been
 * synced it says so rather than omitting the clause, because a missing clause
 * reads as "synced, time unknown".
 */
export function treeHeadline(files, lastSynced) {
  const { files: fileCount, folders } = treeCounts(files);
  const when = formatSyncedAt(lastSynced);
  const counts =
    `${fileCount} file${fileCount === 1 ? '' : 's'} in `
    + `${folders} folder${folders === 1 ? '' : 's'}`;
  return `${counts} · ${when ? `last synced ${when}` : 'never synced'}`;
}
