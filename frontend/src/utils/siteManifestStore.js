import NetInfo from '@react-native-community/netinfo';
import { AppState } from 'react-native';
import apiClient from './api';
import {
  cacheDocList,
  readCachedDocList,
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

    const prevFiles = await readCachedDocList(scopes.files);
    const prevLogs = await readCachedDocList(scopes.logbooks);
    const nextFiles = mergeRows(prevFiles, manifest.files, manifest.complete);
    const nextLogs = mergeRows(prevLogs, manifest.logbooks, manifest.complete);
    await cacheDocList(scopes.files, nextFiles);
    await cacheDocList(scopes.logbooks, nextLogs);

    // ONLY A COMPLETE ASSEMBLY MAY SWEEP. And even then the sweep is the union
    // one — it never learns which project asked.
    let swept = false;
    if (manifest.complete) {
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
      reason: null,
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
