import * as FileSystem from 'expo-file-system/legacy';
import { Platform } from 'react-native';
import apiClient from './api';
import { readManifestList, writeManifestList } from './siteManifestStore';

/**
 * EVERY FILED DATE STAYS ON THE TABLET, AND SO DOES EVERY PDF THAT NAMES ONE.
 *
 * THE MACHINE. A fixed Android tablet is bolted to a construction gate. A DOB
 * inspector arrives without warning and may ask for ANY date. The operator has
 * ruled that the device must hold everything it is approved to see, complete —
 * and that a short list must never be presented as the list.
 *
 * ── WHAT THIS REPLACES, AND WHY THE OBVIOUS FIX WAS WRONG ──────────────────
 *
 * app/site/logbooks.jsx cached the WHOLE submitted-logbook response — every
 * document, with its rendered thumbnails and its kiosk worker signatures —
 * under ONE AsyncStorage key, sliced to `CACHE_DATE_LIMIT = 60` dates. The
 * server was fixed to serve the complete set; the client discarded all but
 * sixty days of it and then DELETED the rest of the files, because
 * `datesToList` is what names each day's full-day-report PDF and sweepDocCache
 * removes every cached document that no stored list names. The slice did not
 * hide date 61, it un-named it, and the next time anybody opened Plans that
 * PDF went.
 *
 * RAISING 60 CANNOT WORK. AsyncStorage on Android is SQLite with a 6 MB
 * maximum that is DATABASE-WIDE (ReactDatabaseSupplier's default; the app is
 * CNG/prebuild with no android/ overriding it), and an overflowing write is
 * REJECTED, never truncated — so a failed write is not a missing photo, it is
 * an EMPTY SCREEN offline for the one person there to read the record.
 * Measured on the same fixture the projection work used, per date:
 *
 *     date list + tab badge counts            91 B
 *     naming every PDF for the sweep         221 B
 *     both together                          319 B
 *     the rendered day detail             95,829 B   <- 99.67% of the list
 *     ------------------------------------------------------------------
 *     60 dates, whole documents        5,768,861 B   91.7% of the ceiling
 *     4000 dates, identity rows        1,281,901 B   20.4% of the ceiling
 *
 * 4000 is the server's own ceiling — eleven years of daily filing. So complete
 * history FITS, and only in this shape. The weight was never the dates.
 *
 * ── THE SHAPE, WHICH IS THE ONE siteManifestStore ALREADY PROVED ───────────
 *
 * Compact rows in chunked AsyncStorage keys; heavy bytes on the FILESYSTEM.
 * This module writes the identity rows through that store's own chunked
 * writer rather than growing a second implementation of it, and puts each
 * day's rendered detail in a file.
 *
 * ── THE DETAIL FILES ARE NOT IN documents/, AND THAT IS LOAD-BEARING ───────
 *
 * docCache's keep-set builder emits `{id}.{version}.pdf` and ONLY that — the
 * extension is hard-coded, because a name no file bears keeps no file. A
 * `.json` sitting in that flat, shared directory would therefore be named by
 * no keep-set at all, while still matching SWEEPABLE — so the next sweep from
 * ANY surface (the plans screen sweeps on every successful list load) would
 * delete it. Giving day detail its own directory is what lets this module add
 * an entirely new class of cached bytes without touching sweepDocCache, its
 * union keep-set, or the flat directory where the prior incident happened.
 *
 * ── WHAT THE ROWS MUST CARRY, AND WHY IT IS EXACTLY THIS ───────────────────
 *
 * Three separable jobs, and only the third is heavy:
 *
 *   (a) the date list and the tab badge counts   `date` + each log's `log_type`
 *   (b) an expanded day                          the whole document — on disk
 *   (c) naming each PDF for the sweep            `{id, cache_version}` at BOTH
 *                                                levels: the day report, whose
 *                                                name nothing else on the
 *                                                device carries, and each log
 *
 * The stored row is (a) + (c) in docCache's own shape, so the names the sweep
 * keeps are the SAME names as before — there are simply no longer only sixty
 * of them. The keep-set strictly grows and can never shrink as a result of
 * this change.
 *
 * ── THE PARAMETER-FREE RESPONSE IS NOW TOO BIG TO ASK FOR ─────────────────
 *
 * `GET /logbooks/project/{id}/submitted` with no parameters is the COMPLETE
 * set by design (an installed device cannot be upgraded to read a flag). At
 * the server's 4000-date ceiling that body is ~366 MB, which no tablet can
 * receive, let alone parse. So this walk always sends `limit`, follows
 * `next_before`, and hands each page to the store before asking for the next:
 * one page is the memory high-water mark.
 *
 * ── AND IT NEVER SHRINKS ON ANYTHING LESS THAN A COMPLETE WALK ────────────
 *
 * The same rule as the manifest store, for the same reason: a shrunken list is
 * a loaded gun this module would not fire and the next person to open Plans
 * would. A dropped page, a page cap, a server that does not declare
 * completeness at all — every one of them lands in the same place: keep what
 * is here, commit nothing that claims to be the whole history.
 */

// ── scope key ──────────────────────────────────────────────────────────────
export function historyScope(projectId) {
  return `site_logbook_history:${String(projectId || '')}`;
}

/**
 * One page of dates. Sixty is not arbitrary: it is the window the current
 * screen already fetches and stores whole, so it is the page size this device
 * is measured to survive receiving — ~5.8 MB of body at the heaviest shape
 * observed. Smaller would cost round trips on a first fill; larger would
 * re-open the memory question the cap exists to close.
 */
export const HISTORY_PAGE_DATES = 60;

/**
 * A server that never stops naming a cursor is a bug, and an unbounded walk
 * against one never returns. Stopping short reports INCOMPLETE, which by the
 * rule above means nothing is committed and nothing is removed. 200 pages at
 * 60 dates covers the server's own 4000-date ceiling three times over.
 */
const MAX_HISTORY_PAGES = 200;

const DAY_DIR = (FileSystem.documentDirectory || '') + 'site_logdays/';
const canUseFs = () => Platform.OS !== 'web' && !!FileSystem.documentDirectory;

// ── identity rows ──────────────────────────────────────────────────────────

/**
 * The version a logbook PDF is cached under. Immutable once submitted, but an
 * amendment bumps `updated_at`, so keying on it re-downloads a corrected
 * record instead of serving a stale one. The precedence is docCache's and the
 * manifest endpoint's (`_manifest_version`), and all three have to agree or
 * the same file is stored twice under two names.
 */
const pdfVersion = (log) =>
  String((log && (log.updated_at || log.submitted_at || log.created_at)) || '0');

/**
 * The full-day report's cache identity.
 *
 * THIS FILE IS NAMED NOWHERE ELSE ON THE DEVICE. It is generated on the server
 * and cached under an id the site logbooks screen INVENTS, so the stored list
 * is the only thing standing between it and the sweep. The manifest store
 * names every INDIVIDUAL logbook PDF; it knows nothing about a combined day.
 */
export function dayReportId(projectId, date) {
  return projectId && date ? `day_${projectId}_${date}` : null;
}

/** Versioned on the newest log of the day, so an amendment re-downloads. A day
 *  with no logs still names its report — falling back to the date keeps the
 *  file in the keep-set rather than computing `{id}.0.pdf`, a name nothing
 *  bears. */
export function dayReportVersion(logs, date) {
  return (Array.isArray(logs) ? logs : []).map(pdfVersion).sort().pop() || date;
}

/**
 * One stored date. (a) + (c) and nothing else — 319 B against the 95,829 B a
 * whole day of documents weighs.
 *
 * `cache_version`, NOT `v`, AND AT BOTH LEVELS. docCache's keep-set builder
 * reconstructs `{id}.{version}.{ext}` off each record it finds, reading
 * `cache_version` and then `updated_at || submitted_at || created_at`. The day
 * row carries `cache_version`; each log carries `updated_at`, which is what
 * the screen's own `pdfVersion` resolves to and therefore what its PDF is
 * already named. A compact `{id, v}` row would make the sweep keep `{id}.0.pdf`
 * and delete every file on the tablet.
 *
 * `log_type` and `status` are the render half: the tab filter is
 * `l.log_type === activeTab` and its badge is a count of those, and `status`
 * decides whether a record offers its PDF at all. Both are needed to draw the
 * LIST, which is why they belong in AsyncStorage and `data` does not.
 */
export function identityRow(projectId, date, logs) {
  const list = Array.isArray(logs) ? logs : [];
  return {
    date,
    id: dayReportId(projectId, date),
    cache_version: dayReportVersion(list, date),
    logs: list.map((l) => ({
      id: (l && (l.id || l._id)) || '',
      log_type: (l && l.log_type) || '',
      status: (l && l.status) || '',
      updated_at: pdfVersion(l),
    })),
  };
}

/**
 * What to store, given what is already stored and what the walk assembled.
 * THE ONLY PLACE THE LIST MAY SHRINK, so the only place completeness matters.
 *
 *   complete   -> the walk IS the truth; a withdrawn date leaves the list and
 *                 its files are reclaimed once no other list names them.
 *   incomplete -> union, keyed on the DATE. Every date the walk did not
 *                 mention is kept.
 *
 * KEYED ON THE DATE, not on `id|cache_version` the way the manifest store
 * keys its rows. There, two versions of one record are two legitimate rows —
 * the superseded bytes are still the only copy the tablet can open until the
 * new ones land. Here a date is a position in a rendered list, and keeping
 * both versions of it would draw the same day twice.
 */
export function mergeHistoryRows(prevRows, nextRows, complete) {
  const next = (Array.isArray(nextRows) ? nextRows : []).filter((r) => r && r.date);
  const out = new Map();
  if (complete !== true) {
    for (const r of (Array.isArray(prevRows) ? prevRows : [])) {
      if (r && r.date) out.set(r.date, r);
    }
  }
  for (const r of next) out.set(r.date, r);
  return [...out.values()].sort((a, b) => String(b.date).localeCompare(String(a.date)));
}

/** The stored index: {state, rows, at}. `state` is 'complete' | 'partial' |
 *  'absent', and rows are EMPTY for anything but complete — a fragment handed
 *  to a screen reads as a complete short list, which is the one thing the
 *  operator's ruling forbids. */
export function readHistoryIndex(projectId) {
  return readManifestList(historyScope(projectId));
}

// ── day detail, on the filesystem ──────────────────────────────────────────

/** `{projectId}_{date}.{version}.json`, in this module's OWN directory.
 *  Sanitised the way docCache sanitises its own names, so a date or a
 *  timestamp cannot introduce a path separator. */
export function dayDetailName(projectId, date, version) {
  const clean = (v) => String(v === undefined || v === null ? '' : v).replace(/[^a-zA-Z0-9_-]/g, '_');
  return `${clean(projectId)}_${clean(date)}.${clean(version)}.json`;
}

async function ensureDayDir() {
  try {
    const info = await FileSystem.getInfoAsync(DAY_DIR);
    if (!info.exists) await FileSystem.makeDirectoryAsync(DAY_DIR, { intermediates: true });
  } catch (_e) { /* best effort */ }
}

/**
 * Put one day's rendered detail on disk. Returns whether it landed.
 *
 * NEVER THROWS. A day whose detail could not be written is a day that opens
 * its PDF instead of its inline card — a degraded record, not a lost one — and
 * a throw here would abandon a walk that still has the rest of the history to
 * store.
 */
export async function writeDayDetail(projectId, date, version, logs) {
  if (!canUseFs() || !projectId || !date) return false;
  try {
    await ensureDayDir();
    await FileSystem.writeAsStringAsync(
      DAY_DIR + dayDetailName(projectId, date, version),
      JSON.stringify(Array.isArray(logs) ? logs : []),
    );
    return true;
  } catch (_e) { return false; }
}

/**
 * One day's logs, or NULL.
 *
 * NULL IS NOT AN EMPTY DAY. A caller that rendered `[]` for a missing file
 * would draw an expanded date with no records under it — a filed day
 * presented as blank, to an inspector. The version is part of the name, so an
 * AMENDED day misses rather than serving the superseded record.
 */
export async function readDayDetail(projectId, date, version) {
  if (!canUseFs() || !projectId || !date) return null;
  try {
    const raw = await FileSystem.readAsStringAsync(
      DAY_DIR + dayDetailName(projectId, date, version),
    );
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : null;
  } catch (_e) { return null; }
}

/**
 * Reclaim day detail this project no longer files on.
 *
 * ONLY THIS PROJECT'S OWN FILES, matched on the `{projectId}_` prefix. This
 * directory is not shared with any other surface — that is the whole reason it
 * exists — but it can still hold the leftovers of a tablet re-provisioned to
 * another project, and deleting by id out of a directory somebody else is
 * relying on is the exact shape of the prior incident. A name this module did
 * not write is left alone for the same reason.
 *
 * Callers must have a COMPLETE walk before calling this. Stale detail is
 * recoverable on the next poll; deleted, underground, is not.
 */
export async function pruneDayDetails(projectId, rows) {
  if (!canUseFs() || !projectId) return 0;
  const keep = new Set(
    (Array.isArray(rows) ? rows : [])
      .filter((r) => r && r.date)
      .map((r) => dayDetailName(projectId, r.date, r.cache_version)),
  );
  const prefix = `${String(projectId).replace(/[^a-zA-Z0-9_-]/g, '_')}_`;
  let removed = 0;
  try {
    const names = await FileSystem.readDirectoryAsync(DAY_DIR);
    for (const name of (Array.isArray(names) ? names : [])) {
      if (!String(name).startsWith(prefix) || keep.has(name)) continue;
      try {
        await FileSystem.deleteAsync(DAY_DIR + name, { idempotent: true });
        removed += 1;
      } catch (_e) { /* it stays, which is the safe direction */ }
    }
  } catch (_e) { /* unreadable directory: delete nothing */ }
  return removed;
}

// ── the walk ───────────────────────────────────────────────────────────────

// 🔒 Relative API path only. The JWT rides in the Authorization HEADER
// (apiClient does this), never in a URL — a URL-borne token leaks into
// history, crash logs and the share sheet.
const pagePath = (projectId, limit, before) =>
  `/api/logbooks/project/${projectId}/submitted?limit=${limit}`
  + (before ? `&before=${encodeURIComponent(before)}` : '');

/**
 * Walk every page of submitted history, newest date first.
 *
 * Returns {ok, complete, rows, pages, reason, error}. `complete` is true ONLY
 * when the walk started without a cursor and followed the server's cursors to
 * a page that declared itself the end. It is never inferred from one response:
 * the first page of a multi-page walk and the only page of a truncated one
 * both say `complete: false`.
 *
 * `opts.onPage(dates)` is awaited BEFORE the next request is issued, so the
 * caller can put the heavy half on disk and let it go. That ordering is the
 * memory bound; without it this is the 366 MB body in slices.
 */
export async function fetchSubmittedHistory(projectId, opts = {}) {
  const limit = opts.limit || HISTORY_PAGE_DATES;
  const maxPages = opts.maxPages || MAX_HISTORY_PAGES;
  const onPage = opts.onPage;
  const rows = [];
  const seen = new Set();
  let before = null;
  let pages = 0;
  // THE FIRST PAGE IS KEPT, and only the first.
  //
  // It is the newest `limit` dates — the same window this screen used to hold
  // whole, so it is memory the device is already measured to survive, and it
  // is the window an inspector actually asks for. Handing it back lets the
  // caller open a recent day with no disk read at all, and it is the ONLY
  // detail available on a platform that cannot hold files (web), where
  // readDayDetail can never answer. Later pages are released as they are
  // stored, which is what keeps one page the high-water mark.
  let recent = null;

  for (;;) {
    if (pages >= maxPages) {
      return { ok: true, complete: false, rows, pages, recent, reason: 'page-cap', error: null };
    }
    let body;
    try {
      const res = await apiClient.get(pagePath(projectId, limit, before));
      body = res && res.data;
    } catch (error) {
      // A DROPPED PAGE IS INCOMPLETENESS, NOT AN EMPTY HISTORY. Whatever was
      // assembled is returned — the detail already on disk is real — but the
      // authority to commit a complete list is withheld.
      return { ok: false, complete: false, rows, pages, recent, reason: 'unreachable', error };
    }
    pages += 1;

    // A RESPONSE THAT DECLARES NEITHER IS NOT A WHOLE HISTORY. The body this
    // endpoint used to serve was `{dates}` and nothing else, capped at 500
    // logs with nothing saying so. Reading it as the complete set would take
    // the silent ceiling the server just removed and rebuild it on the client,
    // where it would authorise a shrink and delete the records.
    if (!body || (body.complete === undefined && body.next_before === undefined)) {
      return {
        ok: true, complete: false, rows, pages, recent,
        reason: 'no-completeness-contract', error: null,
      };
    }

    const dates = body.dates || {};
    if (recent === null) recent = dates;
    if (onPage) {
      const wrote = await onPage(dates);
      if (wrote === false) {
        return { ok: true, complete: false, rows, pages, recent, reason: 'page-store-failed', error: null };
      }
    }
    for (const date of Object.keys(dates)) {
      if (seen.has(date)) continue;
      seen.add(date);
      rows.push(identityRow(projectId, date, dates[date]));
    }

    const next = body.next_before;
    if (next === null || next === undefined || next === '') {
      return { ok: true, complete: true, rows, pages, recent, reason: null, error: null };
    }
    before = next;
  }
}

/**
 * One sync: walk, put every day's detail on disk, commit the index, prune.
 *
 * Returns {ok, complete, dates, stored, pruned, reason, error}.
 *
 * `ok` is about the READ — false means the screen may not treat what it has as
 * a fresh answer. `stored` is about the WRITE, reported rather than assumed: a
 * run that assembled the whole history and failed to store it is not a
 * successful run, and a caller reading only `ok` would never learn otherwise.
 */
export async function syncLogbookHistory(projectId, opts = {}) {
  if (!projectId) {
    return { ok: false, complete: false, dates: 0, stored: false, pruned: 0, recent: null, reason: 'no-project', error: null };
  }
  const scope = historyScope(projectId);

  const walk = await fetchSubmittedHistory(projectId, {
    ...opts,
    onPage: async (dates) => {
      for (const date of Object.keys(dates || {})) {
        const logs = dates[date];
        await writeDayDetail(projectId, date, dayReportVersion(logs, date), logs);
      }
      return true;
    },
  });

  const prev = await readHistoryIndex(projectId);
  const next = mergeHistoryRows(prev.rows, walk.rows, walk.complete);

  /**
   * A REPLACE NEEDS A COMPLETE WALK; A UNION NEEDS A COMPLETE PREV.
   *
   * The union is only safe if `prev` really is everything this device had.
   * When the previous write was interrupted, prev reads as PARTIAL and its
   * rows are empty — and unioning against an empty prev quietly drops every
   * date in the chunks that are missing. The stored list would shrink, this
   * module would decline to prune, and the next screen to call sweepDocCache
   * would delete the day reports anyway. With neither, write nothing: the
   * orphaned chunks are still naming their ids in the sweep's keep-set.
   *
   * AND A WALK THAT ASSEMBLED NOTHING WRITES NOTHING. An offline poll has no
   * news; rewriting the same list would churn a generation for no gain.
   */
  let wrote = { ok: false, reason: 'skipped' };
  if (walk.complete) {
    wrote = await writeManifestList(scope, next, { at: Date.now() });
  } else if (walk.rows.length === 0) {
    wrote = { ok: false, reason: `no-news:${walk.reason || 'incomplete'}` };
  } else if (prev.state !== 'complete') {
    wrote = { ok: false, reason: `partial-store:${prev.reason}` };
  } else {
    // The age is CARRIED, not refreshed. This write is legitimate — it is how
    // a dropped page stops being able to shrink anything — but it is not
    // evidence the device has seen the whole history, and stamping it would
    // let a tablet on a flaky link report itself current for ever.
    wrote = await writeManifestList(scope, next, { at: prev.at === undefined ? null : prev.at });
  }

  // ONLY A COMPLETE WALK MAY PRUNE, AND ONLY IF THE COMMIT LANDED. A run whose
  // commit failed left the PREVIOUS generation on the device, so pruning
  // against the list this run computed would reclaim detail the stored index
  // still points at.
  const pruned = (walk.complete && wrote.ok) ? await pruneDayDetails(projectId, next) : 0;

  return {
    ok: walk.ok && walk.complete,
    complete: walk.complete,
    dates: next.length,
    stored: wrote.ok === true,
    pruned,
    // The newest page, still in memory. See fetchSubmittedHistory: it is the
    // window the screen used to hold whole, and on web it is the only detail
    // there will ever be.
    recent: walk.recent || null,
    reason: walk.complete ? (wrote.ok ? null : (wrote.reason || 'store-failed')) : walk.reason,
    error: walk.error || null,
  };
}

export default {
  historyScope,
  HISTORY_PAGE_DATES,
  dayReportId,
  dayReportVersion,
  identityRow,
  mergeHistoryRows,
  readHistoryIndex,
  dayDetailName,
  writeDayDetail,
  readDayDetail,
  pruneDayDetails,
  fetchSubmittedHistory,
  syncLogbookHistory,
};
