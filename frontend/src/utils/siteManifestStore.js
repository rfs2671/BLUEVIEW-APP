import NetInfo from '@react-native-community/netinfo';
import { AppState } from 'react-native';
import apiClient from './api';
import {
  cacheDocList,
  readCachedDocListOrNull,
  listDocListScopes,
  removeDocList,
  ensureCachedDocFile,
  listCachedDocs,
  cachedDocName,
  sweepDocCache,
  freeDiskBytes,
} from './docCache';

/**
 * SITE MANIFEST STORE — the gate tablet fills itself, and never empties itself.
 *
 * THE MACHINE THIS SERVES. A fixed Android tablet is bolted to a construction
 * gate. It is mains-powered, permanently foregrounded, and nobody prepares it:
 * it has to hold EVERYTHING the project has approved it to see — plans,
 * documents and submitted logbooks — current, filling itself completely on
 * first connection, and still opening all of it after a cold boot with the
 * network down.
 *
 * So this module polls GET /api/projects/{id}/manifest, which names the
 * complete approved set as compact rows, diffs it against what is on the
 * device, downloads what is missing or version-changed, and stops naming what
 * the manifest no longer names.
 *
 * ── THE RULE THAT MAKES THAT LAST CLAUSE SAFE ──────────────────────────────
 *
 * "Stop naming what the manifest does not name" is only safe if the manifest is
 * the WHOLE set. The read this replaces for logbooks was not:
 *
 *     GET /logbooks/project/{id}/submitted   ->  .to_list(500)
 *
 * 500 is a SILENT ceiling — a project past it returned its first 500 rows with
 * nothing in the response saying so. Against a diff-and-delete client that is
 * not a display bug, it is a cache shredder: every logbook past the cap reads
 * as withdrawn and the tablet deletes the compliance record a DOB inspector
 * asks for, offline, where it cannot be fetched back.
 *
 * The manifest therefore pages AND declares `complete`, and this module refuses
 * to shrink anything without it. The refusal is written TWICE, and the second
 * half is the one that is easy to miss:
 *
 *   1. an incomplete assembly does not call sweepDocCache; and
 *   2. an incomplete assembly does not shrink the STORED LIST either.
 *
 * (2) is not belt-and-braces. sweepDocCache's keep-set is the union of every
 * cached list and OTHER SCREENS CALL IT — the plans screen sweeps on every
 * successful list load. A shrunken list is a loaded gun: this module would not
 * fire it and the next person to open Plans would. Declining to sweep while
 * quietly dropping ids would review as correct and delete the records anyway.
 *
 * Every other failure — a dropped page, an offline poll, a server that never
 * says has_more:false — lands in the same place: download, never remove. Stale
 * is recoverable on the next poll; deleted, underground, is not.
 *
 * ── DELETION GOES THROUGH THE UNION KEEP-SET, NEVER BY ID ───────────────────
 *
 * The documents directory is FLAT and shared by every project and every
 * surface. Names are {fileId}.{cache_version}.{ext} with no project prefix, so
 * deleting by id from here would destroy another project's plans — there is a
 * prior incident of exactly that shape. This module therefore never deletes a
 * file. It rewrites its own two lists and calls sweepDocCache, which removes
 * only names that NO cached list mentions. A record still named by the site
 * screens' own lists survives until those lists drop it too; deletion is
 * delayed, never premature, which is the direction every ambiguity in this
 * cache resolves.
 *
 * SEPARATE SCOPE KEYS, for the same reason. The site logbooks screen stores
 * `[{date, logs:[...], id: day_{pid}_{date}, cache_version}]` — a shape that
 * also declares the full-day report PDF, whose name no other record on the
 * device carries. Overwriting that key with flat manifest rows would delete
 * that report on the next sweep. This module owns two keys of its own and
 * leaves every other surface's alone.
 *
 * ── NO BACKGROUND EXECUTION ────────────────────────────────────────────────
 *
 * A plain foreground interval plus a reconnect listener is correct here and is
 * not a compromise: the tablet is mains-powered and permanently foregrounded.
 * expo-task-manager would be a new native dependency, a new rebuild, and a new
 * failure mode, to schedule work that is already running.
 */

// ── scope keys ─────────────────────────────────────────────────────────────
export function manifestScopes(projectId) {
  const pid = String(projectId || '');
  return {
    files: `site_manifest_files:${pid}`,
    logbooks: `site_manifest_logs:${pid}`,
  };
}

// The tablet renders PDFs and nothing else — the site documents screen says so
// on every other type ("PDF files open on a computer"). Pulling a .docx would
// be bytes nobody on this device can read.
const DOWNLOADABLE = new Set(['pdf']);

// Leave the OS room to breathe. A device driven to zero free bytes fails in
// ways that are not this module's to recover from.
const DISK_RESERVE_BYTES = 200 * 1024 * 1024;

// Bounded so one run cannot occupy the device for ever. A run is RESUMABLE by
// construction — anything already on disk is skipped in a single directory
// read — so a first fill simply completes across the next few polls.
const DOWNLOADS_PER_RUN = 500;

// A server that never says has_more:false is a bug, and an unbounded walk
// against one never returns. Stopping short reports INCOMPLETE, which by the
// rule above means nothing is removed.
const MAX_PAGES = 200;

const FOREGROUND_INTERVAL_MS = 5 * 60 * 1000;

/**
 * The canonical stored row.
 *
 * `cache_version`, NOT `v`, AND THIS IS LOAD-BEARING. docCache's keep-set
 * builder reads `cache_version` (and updated_at/submitted_at/created_at) off
 * each record to reconstruct the on-disk name `{id}.{version}.{ext}`. A row
 * stored as `{id, v}` would make it compute `{id}.0.pdf` — a name nothing
 * bears — so the very next sweep would delete every file this module had just
 * downloaded. The wire shape is compact; the stored shape is docCache's.
 */
function toStoredRow(row) {
  return {
    id: String(row.id),
    cache_version: row.v === undefined || row.v === null ? 0 : row.v,
    s: row.s || 0,
    e: row.e || '',
  };
}

const rowKey = (r) => `${r.id}|${String(r.cache_version)}`;

/* ══════════════════════════════════════════════════════════════════════════
 * CHUNKED STORAGE — three states, because two is what loses the records.
 *
 * ── WHAT THE CEILING ACTUALLY IS ─────────────────────────────────────────
 *
 * AsyncStorage on Android is SQLite. The library sets a maximum database size
 * of 6 MB (android/config.gradle getDatabaseSize; nothing in this app raises
 * it) via SQLiteDatabase.setMaximumSize, and that ceiling is DATABASE-WIDE,
 * not per entry — every key in the app draws on the same 6 MB. Overflow is a
 * REJECTION, never a truncation: multiSet catches the SQLiteException and
 * hands JS an error, AsyncStorage.setItem turns it into a rejected promise,
 * and cacheDocList turns that into `false`. There is no silent-short-write
 * mode; a write either lands whole or does not land.
 *
 * A second, quieter ceiling applies to READS: Android's CursorWindow is 2 MB
 * PER ROW, so one enormous value can be written and then be unreadable.
 *
 * MEASURED, AND THE ANSWER IS "NOT YET". A stored manifest row is 74-110 B
 * (files are `{id, cache_version:<int>, s, e}`; logbooks carry an ISO
 * timestamp as their version, which is the fat one). Ten thousand rows is
 * 0.72-1.05 MB — about 18% of the database ceiling and half of one
 * CursorWindow. This store would need ~19,000 rows in a single scope to hit
 * the read ceiling and ~57,000 across all of them to hit the write ceiling.
 *
 * So this is not a fix for a fire. It is a bound: it keeps any single value
 * small regardless of how large a project grows, and it takes the failure of
 * a big write from "the whole list is lost" to "the previous list is still
 * there". The binding constraint on this device is somewhere else entirely —
 * app/site/logbooks.jsx caches whole submitted-logbook documents, inline
 * photo thumbnails and signature blobs and all, and that list runs 19-50 MB
 * for a 200-log project. See the note at the foot of this file.
 *
 * ── THE THREE STATES ─────────────────────────────────────────────────────
 *
 * Rows go into indexed chunk keys; a single final write COMMITS them by
 * naming the chunk count and the generation. That produces three states and
 * the reader has to tell them apart:
 *
 *   COMPLETE  a commit exists and every chunk it names is present.
 *   ABSENT    nothing is stored for this scope.
 *   PARTIAL   chunks exist that no commit names, or a commit names chunks
 *             that are not all there.
 *
 * PARTIAL IS THE STATE THIS EXISTS FOR. Returning the chunks that happen to
 * be present would hand back a SHORT list that reads as complete, and a short
 * list here is not a display bug — it is the cache shredder this module was
 * built to prevent, reached through a half-finished WRITE instead of a
 * truncated FETCH. sweepDocCache's keep-set is the union of every cached list
 * and OTHER SCREENS CALL IT; the plans screen sweeps on every successful list
 * load. So PARTIAL is reported as its own state and treated exactly like
 * ABSENT wherever a decision is made: it can never authorise a shrink.
 *
 * ── WHY CHUNKS ARE PLAIN ROW ARRAYS UNDER THE DOCLIST PREFIX ─────────────
 *
 * LOAD-BEARING, and the reason the interrupted-write case is safe at all.
 * sweepDocCache does not consult this reader; it walks the raw `bv_doclist:`
 * keys and unions every id it finds. Storing chunks as ordinary row arrays
 * under that prefix puts every id they hold into the keep-set WHETHER OR NOT
 * ANY COMMIT NAMES THEM. An orphaned half-written generation therefore keeps
 * its files alive, and a foreign sweep landing between the chunks and the
 * commit deletes nothing. Had the chunks been wrapped in an envelope object,
 * collectKeepNames would have skipped them (it ignores non-array values) and
 * the sweep would have deleted exactly the records a partial write is most
 * likely to be carrying.
 *
 * The commit record is an array too, holding one marker object with no `id`,
 * so it contributes nothing to the keep-set and cannot be mistaken for a row.
 *
 * ── ORDERING, AND WHY IT SURVIVES BEING INTERRUPTED AT ANY POINT ─────────
 *
 *   1. write the new generation's chunks     old generation still committed
 *   2. write the commit  (ONE write)         the switch-over, atomic
 *   3. remove other generations' chunks      housekeeping
 *
 * Interrupted in (1): no commit moved, so the reader still assembles the OLD
 * generation, whole. The new chunks are orphans — ignored by the reader
 * because their generation is not the committed one, and honoured by the
 * sweep because they are row arrays. Nothing shrinks.
 *
 * Interrupted in (3): the new generation is committed and complete; leftover
 * old chunks are ignored by generation and merely take space. The next
 * successful write purges every generation that is not the committed one, so
 * the leftovers are collected then. Each removal is independent, so stopping
 * anywhere is a legal state — cleanup is idempotent and resumable.
 *
 * THE GENERATION IS STAMPED INTO THE KEY, not just recorded in the commit.
 * If chunk keys were reused between writes, a half-finished SHORT write over
 * a long one would leave chunks 0-1 new and chunk 2 old, and the reader would
 * assemble a list that never existed on any server. Distinct keys per
 * generation make that unrepresentable rather than merely unlikely.
 * ═══════════════════════════════════════════════════════════════════════ */

// ~55 KB per chunk at the fattest row shape — two orders of magnitude under
// the 2 MB CursorWindow, while keeping the chunk count (and so the number of
// getItem calls a read costs) small: 10,000 rows is 20 chunks.
const CHUNK_ROWS = 500;

const COMMIT_MARK = '__manifest_gen';

/** The scope key one chunk is stored under. Exported so a test can plant a
 *  half-written generation without hard-coding the format. */
export function manifestChunkKey(scopeKey, gen, index) {
  return `${scopeKey}#g${gen}#${index}`;
}

// A generation only ever has to be UNIQUE, never ordered: the commit names the
// exact one to read, and cleanup compares for equality. So a clock that jumps
// backwards cannot cause a mix-up. The counter covers two writes inside one
// millisecond; the random tail covers a process restart inside one.
let genCounter = 0;
function nextGeneration() {
  genCounter += 1;
  return `${Date.now().toString(36)}${genCounter.toString(36)}`
    + `${Math.floor(Math.random() * 1296).toString(36)}`;
}

const isCommit = (v) =>
  Array.isArray(v) && v.length === 1 && v[0] && typeof v[0] === 'object'
  && typeof v[0][COMMIT_MARK] === 'string';

/**
 * Read a manifest scope. Returns {state, rows, gen, chunks, at}, where state is
 * 'complete' | 'partial' | 'absent'. `rows` is EMPTY for anything but
 * 'complete' — a fragment is never handed out, because every caller that
 * receives rows is entitled to treat them as the whole stored list.
 *
 * `at` is the moment a COMPLETE assembly became this device's set, or null when
 * that is not recorded (a list committed by a build older than the stamp).
 * NULL IS NOT ZERO AND IS NOT NOW: a caller that wants to show an age has to
 * handle "not recorded" as its own case, because a tablet off the network since
 * that build could be months out of date and reporting it as current would be a
 * claim made out of an absence.
 */
export async function readManifestList(scopeKey) {
  const head = await readCachedDocListOrNull(scopeKey);
  if (head === null) {
    // Nothing committed. But a half-written generation may still be sitting
    // there, and saying 'absent' when chunks exist would hide the reason.
    const orphans = await chunkKeysFor(scopeKey);
    return orphans.length > 0
      ? { state: 'partial', rows: [], gen: null, chunks: 0, at: null, reason: 'uncommitted-chunks' }
      : { state: 'absent', rows: [], gen: null, chunks: 0, at: null, reason: 'nothing-stored' };
  }

  // A LIST FROM THE PREVIOUS BUILD IS A COMPLETE LIST. Reading it as absent
  // would make the first incomplete poll after an upgrade decline to union
  // against it, and the tablet would report a shrink it did not need to.
  if (!isCommit(head)) {
    return { state: 'complete', rows: head, gen: null, chunks: 0, at: null, reason: 'unchunked' };
  }

  const gen = head[0][COMMIT_MARK];
  const chunks = head[0].__manifest_chunks;
  const declared = head[0].__manifest_rows;
  const stamped = head[0].__manifest_at;
  const at = Number.isFinite(stamped) ? stamped : null;
  if (!Number.isInteger(chunks) || chunks < 0) {
    return { state: 'partial', rows: [], gen, chunks: 0, at, reason: 'bad-commit' };
  }

  const rows = [];
  for (let i = 0; i < chunks; i += 1) {
    const part = await readCachedDocListOrNull(manifestChunkKey(scopeKey, gen, i));
    // A CHUNK THE COMMIT NAMES AND THE DEVICE DOES NOT HAVE. This is the
    // whole point: return the fragment and it reads as a complete short list.
    if (part === null) {
      return { state: 'partial', rows: [], gen, chunks, at, reason: `missing-chunk-${i}` };
    }
    for (const r of part) rows.push(r);
  }
  // The row count is recorded at commit time, so a chunk that was rewritten
  // shorter by something else is caught even though every key is present.
  if (Number.isInteger(declared) && declared !== rows.length) {
    return { state: 'partial', rows: [], gen, chunks, at, reason: 'row-count-mismatch' };
  }
  return { state: 'complete', rows, gen, chunks, at, reason: null };
}

/** Every chunk scope key currently stored for this manifest scope, with the
 *  generation each belongs to. */
async function chunkKeysFor(scopeKey) {
  const prefix = `${scopeKey}#g`;
  const all = await listDocListScopes();
  const out = [];
  for (const k of all) {
    // The `#g` separator is what keeps `...:P1` from matching `...:P11`.
    if (!k.startsWith(prefix)) continue;
    out.push({ key: k, gen: k.slice(prefix.length).split('#')[0] });
  }
  return out;
}

/**
 * Remove the chunk keys of every generation `shouldRemove(gen)` accepts.
 *
 * SAFE TO INTERRUPT AND SAFE TO REPEAT. Each removal is independent, so
 * stopping anywhere leaves a legal state: extra chunks the reader ignores by
 * generation and the sweep honours as row arrays. It NEVER reports failure —
 * a manifest that was written correctly must not be lost because tidying up
 * after it went wrong.
 */
async function purgeGenerations(scopeKey, shouldRemove) {
  let removed = 0;
  try {
    for (const { key, gen } of await chunkKeysFor(scopeKey)) {
      if (!shouldRemove(gen)) continue;
      if (await removeDocList(key)) removed += 1;
    }
  } catch (_e) { /* housekeeping only */ }
  return removed;
}

/**
 * Write a manifest scope as chunks plus one commit.
 *
 * Returns {ok, gen, chunks, reason}. On failure NOTHING is committed, so the
 * previously committed generation — if there was one — is still what the
 * reader returns, whole.
 *
 * `opts.at` IS THE AGE THE SCREENS SHOW, so it is a parameter rather than a
 * `Date.now()` taken here. This function is also called for a write that came
 * out of an INCOMPLETE walk — a union against a complete previous list, which
 * is right, because a dropped page must never shrink anything — and stamping
 * the clock on that write would make a tablet on a flaky link report itself
 * current for ever while never once seeing the whole approved set. The caller
 * passes the moment a COMPLETE assembly landed, or carries the previous one
 * forward so the age keeps growing. `null` means "not recorded".
 */
export async function writeManifestList(scopeKey, rows, opts = {}) {
  const list = Array.isArray(rows) ? rows : [];
  const size = opts.chunkRows || CHUNK_ROWS;
  const gen = nextGeneration();
  const chunks = Math.max(1, Math.ceil(list.length / size));

  // 1. CHUNKS FIRST. Until the commit lands these are orphans: invisible to
  //    the reader, visible to the sweep, and therefore harmless.
  for (let i = 0; i < chunks; i += 1) {
    const slice = list.slice(i * size, (i + 1) * size);
    if (!(await cacheDocList(manifestChunkKey(scopeKey, gen, i), slice))) {
      // ABORT WITHOUT COMMITTING, and roll back ONLY WHAT THIS RUN WROTE.
      // Not "everything except the committed generation": an older orphan is
      // still naming ids in the sweep's keep-set, and a failed write is the
      // worst possible moment to take names out of it. If the rollback cannot
      // run either, the leftovers are orphans of a generation nothing names —
      // a state the reader already reports as partial and the sweep already
      // honours.
      await purgeGenerations(scopeKey, (g) => g === gen);
      return { ok: false, gen, chunks, reason: 'chunk-write-failed' };
    }
  }

  // 2. THE COMMIT — ONE write, and the only one that changes what a reader
  //    sees. Everything before it was invisible; everything after it is
  //    housekeeping.
  const commit = [{
    [COMMIT_MARK]: gen,
    __manifest_chunks: chunks,
    __manifest_rows: list.length,
    // Still no `id`, so this record contributes nothing to the sweep's
    // keep-set and cannot be mistaken for a row.
    __manifest_at: opts.at === undefined ? Date.now()
      : (Number.isFinite(opts.at) ? opts.at : null),
  }];
  if (!(await cacheDocList(scopeKey, commit))) {
    await purgeGenerations(scopeKey, (g) => g === gen);
    return { ok: false, gen, chunks, reason: 'commit-write-failed' };
  }

  // 3. HOUSEKEEPING. Superseded generations are reclaimed — not merely
  //    ignored, because the ceiling is database-wide and every generation left
  //    behind is spent against the same 6 MB every other key draws on. This
  //    also collects orphans from earlier runs that were interrupted.
  await purgeGenerations(scopeKey, (g) => g !== gen);
  return { ok: true, gen, chunks, reason: null };
}

/**
 * What to store for a scope, given what is already stored and what the manifest
 * named. THE ONLY PLACE THE LIST IS ALLOWED TO SHRINK, so the only place the
 * completeness flag has to be honoured.
 *
 *   complete   -> the manifest IS the truth; replace, and a withdrawn record
 *                 leaves the list (and is swept once no other list names it).
 *   incomplete -> union. Every id the manifest did not name is kept, INCLUDING
 *                 the superseded version of a record whose version moved: the
 *                 old bytes are still the only copy this tablet can open until
 *                 the new ones have actually landed.
 */
export function mergeRows(prevRows, nextRows, complete) {
  const next = (Array.isArray(nextRows) ? nextRows : []).filter((r) => r && r.id);
  if (complete === true) {
    const out = new Map();
    for (const r of next) out.set(rowKey(r), r);
    return [...out.values()];
  }
  const out = new Map();
  for (const r of (Array.isArray(prevRows) ? prevRows : [])) {
    if (r && r.id) out.set(rowKey(r), r);
  }
  for (const r of next) out.set(rowKey(r), r);
  return [...out.values()];
}

/**
 * Walk every page and assemble the whole approved set.
 *
 * Returns {ok, complete, files, logbooks}. `complete` is true only when the
 * walk actually reached the end of BOTH sections — never inferred from a single
 * response, because the last page of a walk says `complete: false` (it is a
 * fragment on its own) and the first page of a truncated one says the same.
 *
 * The two sections advance independently. When one finishes its skip stops
 * moving and its rows stop being collected, so the extra pages the other
 * section still needs cannot duplicate it.
 */
export async function fetchManifest(projectId, opts = {}) {
  const limit = opts.limit || 1000;
  const maxPages = opts.maxPages || MAX_PAGES;
  const files = new Map();
  const logbooks = new Map();

  let filesSkip = 0;
  let logsSkip = 0;
  let filesDone = false;
  let logsDone = false;
  let pages = 0;

  while (!filesDone || !logsDone) {
    if (pages >= maxPages) {
      return { ok: true, complete: false, files: [...files.values()], logbooks: [...logbooks.values()] };
    }
    let body;
    try {
      const res = await apiClient.get(
        `/api/projects/${projectId}/manifest`
        + `?limit=${limit}&files_skip=${filesSkip}&logbooks_skip=${logsSkip}`,
      );
      body = res && res.data;
    } catch (_e) {
      // A DROPPED PAGE IS INCOMPLETENESS, NOT AN EMPTY SET. Whatever was
      // assembled so far is returned so the downloads can still proceed; only
      // the authority to remove is withheld.
      return { ok: pages > 0, complete: false, files: [...files.values()], logbooks: [...logbooks.values()] };
    }
    pages += 1;
    const fSec = (body && body.files) || {};
    const lSec = (body && body.logbooks) || {};

    if (!filesDone) {
      for (const row of (Array.isArray(fSec.rows) ? fSec.rows : [])) {
        if (row && row.id) { const r = toStoredRow(row); files.set(rowKey(r), r); }
      }
    }
    if (!logsDone) {
      for (const row of (Array.isArray(lSec.rows) ? lSec.rows : [])) {
        if (row && row.id) { const r = toStoredRow(row); logbooks.set(rowKey(r), r); }
      }
    }

    if (!fSec.has_more) filesDone = true; else filesSkip += limit;
    if (!lSec.has_more) logsDone = true; else logsSkip += limit;
  }

  return {
    ok: true,
    complete: filesDone && logsDone,
    files: [...files.values()],
    logbooks: [...logbooks.values()],
  };
}

// 🔒 Relative API paths only. The JWT rides in the Authorization HEADER
// (docCache does this), never in a URL — a URL-borne token leaks into history,
// crash logs and the share sheet.
const fileContentPath = (projectId, id) =>
  `/api/projects/${projectId}/files/${id}/content`;
const logbookPdfPath = (id) => `/api/reports/logbook/${id}/pdf`;

// ONE RUN AT A TIME. A reconnect that lands on a foreground event fires both
// triggers together, and a second run on top of the first would double every
// download. Set before the first await, so the guard is real.
let inFlight = false;

/**
 * One poll: fetch, write the lists, sweep if entitled to, then fill the disk.
 *
 * ORDER MATTERS. The sweep runs BEFORE the disk budget is computed, so a tablet
 * that is short of space reclaims its orphans first and then measures what it
 * can actually pull. Nothing approved is at risk in doing so: the sweep removes
 * only names that no cached list mentions.
 */
export async function syncSiteManifest(projectId, opts = {}) {
  if (!projectId) return { ok: false, reason: 'no-project', swept: false, downloaded: 0 };
  if (inFlight) return { ok: false, reason: 'busy', swept: false, downloaded: 0 };
  inFlight = true;
  try {
    const scopes = manifestScopes(projectId);
    const manifest = await fetchManifest(projectId, opts);
    if (!manifest.ok) {
      // An offline poll is not "the project approved nothing". Leave every
      // stored list exactly as it was.
      return { ok: false, complete: false, reason: 'unreachable', swept: false, downloaded: 0 };
    }

    const prevFiles = await readManifestList(scopes.files);
    const prevLogs = await readManifestList(scopes.logbooks);
    const nextFiles = mergeRows(prevFiles.rows, manifest.files, manifest.complete);
    const nextLogs = mergeRows(prevLogs.rows, manifest.logbooks, manifest.complete);

    /**
     * THE SHRINK RULE, NOW APPLIED TO THE STORED LIST AS WELL AS THE FETCH.
     *
     * mergeRows already honours an incomplete FETCH by unioning instead of
     * replacing. That union is only safe if `prev` really is everything this
     * device had. When the previous write was interrupted, prev reads as
     * PARTIAL and its rows are empty — and unioning against an empty prev
     * quietly drops every id in the chunks that are missing. The stored list
     * would shrink, this module would decline to sweep, and the next screen to
     * call sweepDocCache would delete the records anyway. That is precisely
     * the failure the incomplete-fetch rule exists to prevent, reached by a
     * different road.
     *
     * So: a replace needs a complete FETCH, and a union needs a complete PREV.
     * With neither, the right move is the one every ambiguity in this cache
     * resolves to — write nothing, leave the orphaned chunks where they are
     * (they are still naming their ids in the sweep's keep-set), and try again
     * on the next poll.
     */
    // AND THE AGE IS CARRIED, NOT REFRESHED, ON AN INCOMPLETE WALK. The union
    // write below is a legitimate write — it is how a dropped page stops being
    // able to shrink anything — but it is NOT evidence that this device has
    // seen the whole approved set. Stamping it would reset the age the site
    // screens show, and a tablet on a flaky link would then report itself
    // current for ever while quietly falling months behind. So a complete walk
    // stamps now, and an incomplete one carries the previous stamp forward so
    // the age keeps growing.
    const stampedAt = Date.now();
    const commitScope = async (scopeKey, prev, next) => {
      if (manifest.complete) return writeManifestList(scopeKey, next, { at: stampedAt });
      if (prev.state !== 'complete') {
        return { ok: false, skipped: true, reason: `partial-store:${prev.reason}` };
      }
      return writeManifestList(scopeKey, next, { at: prev.at === undefined ? null : prev.at });
    };
    const wroteFiles = await commitScope(scopes.files, prevFiles, nextFiles);
    const wroteLogs = await commitScope(scopes.logbooks, prevLogs, nextLogs);

    // ONLY A COMPLETE ASSEMBLY MAY SWEEP. And even then the sweep is the union
    // one — it never learns which project asked.
    //
    // AND ONLY IF BOTH COMMITS LANDED. A run whose commit failed left the
    // PREVIOUS generation as the one on the device, so the keep-set is no
    // longer the list this run computed. Sweeping against it would delete
    // files the new complete manifest still names — deleting against a list
    // you did not manage to write is deleting against a guess.
    let swept = false;
    if (manifest.complete && wroteFiles.ok && wroteLogs.ok) {
      const r = await sweepDocCache();
      swept = !(r && r.skipped);
    }

    // What is missing, in ONE directory read: the filename already encodes
    // {id}.{version}, so intersecting the names with the manifest gives exact
    // per-record state INCLUDING staleness.
    const onDisk = await listCachedDocs();
    const wanted = [
      ...nextFiles
        .filter((r) => DOWNLOADABLE.has(String(r.e || '').toLowerCase()))
        .map((r) => ({ ...r, url: fileContentPath(projectId, r.id) })),
      // Newest first, best effort: the manifest is ordered by record id, so the
      // most recent logs are at the end. An inspector asks for the recent ones.
      ...[...nextLogs].reverse().map((r) => ({ ...r, url: logbookPdfPath(r.id) })),
    ].filter((r) => !onDisk.has(cachedDocName(r.id, r.cache_version)));

    // REFUSE BEFORE STARTING, rather than dying on file 9 with a half-filled
    // tablet and no way to know which half.
    //
    // IT IS A FLOOR, NOT AN EXACT FIGURE, and deliberately so. `s` is the
    // stored size of a project file; a logbook PDF is RENDERED on request and
    // has no size until it exists, so those rows contribute nothing here. The
    // reserve above is what covers them. Under-counting only ever means the run
    // starts and a later download fails — which is a failed download, the
    // ordinary case cacheDocFile already cleans up after. Over-counting would
    // mean refusing to fill a tablet that had room, which is the worse error.
    const needed = wanted.reduce((n, r) => n + (Number(r.s) || 0), 0);
    const free = await freeDiskBytes();
    if (free !== null && needed > Math.max(0, free - DISK_RESERVE_BYTES)) {
      return {
        ok: true, complete: manifest.complete, reason: 'no-space', swept,
        downloaded: 0, needed, free,
        files: nextFiles.length, logbooks: nextLogs.length,
      };
    }

    let downloaded = 0;
    for (const r of wanted.slice(0, opts.downloadLimit || DOWNLOADS_PER_RUN)) {
      const got = await ensureCachedDocFile({
        fileId: r.id, cacheVersion: r.cache_version, remoteUrl: r.url,
      });
      if (got) downloaded += 1;
    }

    return {
      ok: true, complete: manifest.complete, swept, downloaded,
      files: nextFiles.length, logbooks: nextLogs.length,
      // WHETHER THE LISTS ACTUALLY LANDED, reported rather than assumed. A run
      // that downloaded everything and stored no list is not a successful run,
      // and a caller reading only `ok` would never learn the difference.
      stored: wroteFiles.ok === true && wroteLogs.ok === true,
      reason: wroteFiles.ok && wroteLogs.ok
        ? null
        : (wroteFiles.reason || wroteLogs.reason || 'store-failed'),
    };
  } finally {
    inFlight = false;
  }
}

/**
 * Start the triggers. `getProjectId` is read at fire time, not captured, so a
 * device re-provisioned to another project starts syncing the new one without a
 * restart.
 *
 * Three triggers, and no fourth: startup (a tablet cold-booted with the network
 * already up must fill itself with nobody touching it), a NetInfo reconnect,
 * and foreground — plus a plain interval, which on a permanently-foregrounded
 * mains-powered device is the whole background story.
 */
export function setupSiteManifestSync(getProjectId, opts = {}) {
  const run = opts.run || ((pid) => syncSiteManifest(pid));
  const intervalMs = opts.intervalMs === undefined ? FOREGROUND_INTERVAL_MS : opts.intervalMs;

  const fire = () => {
    let pid = null;
    try { pid = getProjectId && getProjectId(); } catch (_e) { pid = null; }
    // SITE SURFACES ONLY. No project means this is not a gate tablet, and the
    // manifest is not this device's business.
    if (!pid) return;
    Promise.resolve(run(pid)).catch(() => {});
  };

  let wasOnline = true;
  const unsubNet = NetInfo.addEventListener((state) => {
    const online = state.isConnected && state.isInternetReachable !== false;
    if (online && !wasOnline) fire();
    wasOnline = online;
  });

  let lastAppState = (AppState && AppState.currentState) || 'active';
  const appSub = AppState.addEventListener('change', (next) => {
    if (next === 'active' && lastAppState !== 'active') fire();
    lastAppState = next;
  });

  const timer = intervalMs > 0 ? setInterval(fire, intervalMs) : null;

  fire();

  return () => {
    try { if (typeof unsubNet === 'function') unsubNet(); } catch (_e) {}
    try { if (appSub && typeof appSub.remove === 'function') appSub.remove(); } catch (_e) {}
    if (timer) clearInterval(timer);
  };
}

/* ══════════════════════════════════════════════════════════════════════════
 * THE NOTE PROMISED ABOVE: THIS STORE IS NOT THE BINDING CONSTRAINT.
 *
 * The chunking was built after measuring, and the measurement says these
 * compact rows were never close to the ceiling. Recorded here so the next
 * person does not re-derive it, and so the real problem keeps a name.
 *
 * WHAT THE CEILING IS. AsyncStorage 2.2.0 on Android is SQLite with
 * setMaximumSize(6 MB) — android/config.gradle getDatabaseSize — and this app
 * sets no AsyncStorage_db_size_in_MB anywhere. There is no android/ directory
 * at all: the project is CNG/prebuild, and app.json's expo-build-properties
 * block sets only SDK levels. useNextStorage defaults false and newArchEnabled
 * is false, so it is the legacy SQLite module, not the Room one.
 *
 * The ceiling is DATABASE-WIDE, not per entry: every key in the app draws on
 * the same 6 MB. Overflow REJECTS — AsyncStorageModule.multiSet catches the
 * SQLiteException, the JS setItem rejects, cacheDocList turns that into false.
 * It never truncates, so there is no silent-short-write mode to defend
 * against. A second ceiling applies only to READS: Android's CursorWindow is
 * ~2 MB per row, so one oversized value can be written and then be unreadable.
 *
 * WHAT THIS STORE WEIGHS. A stored row is 74 B (files, whose version is an
 * integer) to 110 B (logbooks, whose version is an ISO-8601 string, with UUID
 * rather than ObjectId ids):
 *
 *      500 rows   36-54 KB          3,000 rows   217-322 KB
 *    1,500 rows  108-161 KB        10,000 rows   723 KB-1.05 MB
 *
 * Ten thousand rows is ~18% of the database ceiling. It takes ~19,000 rows in
 * ONE scope to reach the CursorWindow and ~57,000 across all of them to reach
 * the database ceiling. No project is near either. What the chunking buys is
 * therefore a BOUND, not a rescue: no single value grows without limit, and a
 * failed write costs the new list rather than the old one.
 *
 * WHAT IS BINDING. app/site/logbooks.jsx caches the WHOLE submitted-logbook
 * response. GET /logbooks/project/{id}/submitted applies no projection, so
 * every inline blob in every document comes down and goes into ONE AsyncStorage
 * value. For 200 submitted logs carrying 100 photos that list measures 19 MB at
 * the low end of every estimate and 50 MB at the high end — 3x to 8x the entire
 * database ceiling, in a single key.
 *
 * AND ITS FALLBACK DOES NOT HELP. writeListThrough tries the full list, then
 * retries with stripPhotoBlobs — which removes `base64` ONLY. On a finalized
 * project the backend has already purged `base64` itself
 * (_purge_finalized_photo_base64), so the retry is byte-for-byte the same write
 * and fails identically: the tablet caches NOTHING, and an inspector offline
 * gets an empty screen. What dominates is not the photos anyway:
 *
 *   worker_signature   a 600x200 canvas.toDataURL('image/png') from
 *                      backend/checkin.html, ~5-16 KB per worker, inline on
 *                      every pre-shift sign-in log. stripPhotoBlobs does not
 *                      touch it. On a 14-worker crew this alone crosses 6 MB
 *                      at 27-73 submitted logs.
 *   thumb_base64       ~25-40 KB per photo, and server.py says plainly that it
 *                      is NEVER removed. Crosses 6 MB at ~231 logs on its own.
 *   cp_signature       {paths:[{x,y}...]} vector — SignaturePad appends a point
 *                      per PanResponder move event with no throttling and no
 *                      simplification. 47 B a point: 3.8 KB for a short
 *                      signature, 33 KB for a long one.
 *
 * With none of those three, 200 logs of pure compliance text is 888 KB and fits
 * comfortably. The blobs are the whole problem, and the fix belongs there — a
 * projection on the submitted endpoint, or a cached shape that stores ids
 * instead of inline images — not in this module.
 * ═══════════════════════════════════════════════════════════════════════ */
