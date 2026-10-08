import * as FileSystem from 'expo-file-system/legacy';
import { Platform } from 'react-native';
import apiClient from './api';
import { readManifestList, writeManifestList } from './siteManifestStore';
// THE DEFERRAL PROTOCOL LIVES IN A MODULE THAT IMPORTS NOTHING, so the screen's
// renderers — which are sliced out and EXECUTED by
// logbookViewRenderers.test.cjs, a harness that cannot require a module
// touching the filesystem — can load the real `signatureMark` instead of a stub
// of it. A stubbed answer to "did he sign?" in the only test that runs the
// pre-shift roster is the defect wearing the name of the fix.
// RE-EXPORTED BELOW, so every existing import of this module is unchanged.
import {
  SIG_DEFERRED_SUFFIX, SIG_FIELDS, signatureMark, deferredSignaturePaths,
  dayHasDeferredSignatures, applySignatureImages, applyDaySignatureImages,
} from './signatureDeferral';

export {
  SIG_DEFERRED_SUFFIX, SIG_FIELDS, signatureMark, deferredSignaturePaths,
  dayHasDeferredSignatures, applySignatureImages, applyDaySignatureImages,
};

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
 *
 * ── AND THE WALK ITSELF WAS STILL THE WHOLE CORPUS ─────────────────────────
 *
 * The split above put the heavy bytes on the FILESYSTEM. It did not stop them
 * crossing the WIRE. Measured on production 2026-10-07, 588 Thomas, through the
 * real handler: `syncLogbookHistory` moved 14,363,640 bytes over five pages to
 * draw a list of 43 dates — 14,122,753 of them `data`, overwhelmingly the kiosk
 * worker-signature images on pre-shift sheets — and 3.4 s of that was the
 * server. The rest was transfer, and an inspector stood in front of it for ten
 * minutes.
 *
 * So there are now TWO reads, and the list uses the cheap one:
 *
 *   syncLogbookIndex   `view=index` — identity rows, no `data`. 39,308 bytes in
 *                      two requests for this project's whole history, 0.27% of
 *                      the documents. Same commit rules, clause for clause.
 *   ensureDayDetail    `?date=` — ONE day's whole documents, when a day is
 *                      opened, and nothing at all for a day this device already
 *                      holds at its filed version. That last clause is the one
 *                      that matters: the old walk re-downloaded all 14 MB and
 *                      rewrote all 43 days on EVERY open.
 *   backfillDayDetails the offline guarantee, moved off the render path. Same
 *                      days end up on the device; they are fetched after the
 *                      list is on screen instead of in front of it.
 *
 * `syncLogbookHistory` and `fetchSubmittedHistory` STAY, and they are reachable:
 * a server that predates `view=index` ignores the parameter and serves
 * documents, `fetchSubmittedIndex` detects that and refuses to commit, and the
 * screen falls back to this walk for however long the deploy gap lasts. Slow is
 * better than blank.
 */

// ── scope key ──────────────────────────────────────────────────────────────
export function historyScope(projectId) {
  return `site_logbook_history:${String(projectId || '')}`;
}

/**
 * One page of dates, and the reason it is TEN.
 *
 * It was sixty, sized as "the page this device is measured to survive
 * receiving — ~5.8 MB of body at the heaviest shape observed." The body grew
 * past that. Measured 2026-09-22 on 588 Thomas: sixty dates is the project's
 * WHOLE history, and it came back as 9.86 MB in one response -- 5.57 MB of it
 * pre-shift sheets, each carrying every worker's signature image inline.
 *
 * WHAT BROKE WAS THE CLOCK, NOT THE MEMORY. apiClient's default timeout is
 * 25 s. 9.86 MB in 25 s is ~3.2 Mbps sustained, more than a jobsite tablet on
 * cellular reliably gets. So the request timed out, isOfflineError read the
 * ECONNABORTED as offline, the walk returned incomplete, and -- by the rule
 * below -- nothing was committed. On a tablet with no earlier complete sync
 * the index stayed EMPTY: "No Submitted Logs" in front of an inspector, while
 * the server logged every one of those requests as 200 OK, because it finished
 * sending after the tablet had already given up.
 *
 * A PAGE IS BOUNDED BY DATES, SO IT STAYS BOUNDED AS THE HISTORY GROWS. A new
 * filing day adds a page, it never makes a page heavier. Ten dates averages
 * ~2.6 MB on this corpus and ~5 MB at the ten heaviest days observed -- both
 * under the 5.8 MB this pager was originally measured to survive, with the
 * longer per-page timeout below as the margin.
 *
 * NOT "the smaller the better". Every page is a round trip, and a first fill
 * of the server's 4000-date ceiling is 400 of them; MAX_HISTORY_PAGES is
 * derived from this number so that ceiling stays covered.
 */
export const HISTORY_PAGE_DATES = 10;

/**
 * THE IN-MEMORY WINDOW, WHICH IS NOT THE PAGE.
 *
 * These used to be the same number, because the first page WAS the window:
 * the newest sixty dates, handed back as `recent` so a recent day opens with
 * no disk read -- and on web, where nothing can be written to disk and
 * readDayDetail can never answer, the ONLY day detail the screen has.
 *
 * Splitting the page from the window is what lets the page shrink without
 * web losing fifty of its sixty days. `recent` is now filled from successive
 * pages until it holds this many dates, which is exactly the window it held
 * before -- the same memory, assembled in smaller requests.
 */
export const RECENT_WINDOW_DATES = 60;

/**
 * Per-page timeout, and why the default is not enough here.
 *
 * apiClient's own header says it: "Every endpoint that can legitimately exceed
 * 25s carries its own `timeout:` at the call site... Adding a new endpoint
 * that... carries a photo payload means adding one there." This one carries
 * signature images and never had one. Sixty seconds matches the other
 * long-payload override in api.js.
 */
export const HISTORY_PAGE_TIMEOUT_MS = 60000;

/**
 * A server that never stops naming a cursor is a bug, and an unbounded walk
 * against one never returns. Stopping short reports INCOMPLETE, which by the
 * rule above means nothing is committed and nothing is removed.
 *
 * DERIVED FROM THE PAGE SIZE, AND IT HAS TO BE. It was a literal 200, justified
 * as "200 pages at 60 dates covers the server's 4000-date ceiling three times
 * over." At ten dates that literal covers 2000 -- HALF the ceiling -- so a
 * large project would hit the cap, report incomplete, commit nothing and show
 * an empty screen: the exact failure this change exists to fix, reintroduced
 * one layer down. Three times the ceiling, whatever the page is.
 */
const SERVER_DATE_CEILING = 4000;
const MAX_HISTORY_PAGES = Math.ceil((SERVER_DATE_CEILING * 3) / HISTORY_PAGE_DATES);

/**
 * THE INDEX PAGE, AND WHY IT IS FIFTY TIMES THE DOCUMENT PAGE.
 *
 * MEASURED ON PRODUCTION 2026-10-07, 588 Thomas, through the real handler.
 * Walking this endpoint for whole documents to draw a DATE LIST cost
 * 14,363,640 bytes over five pages and 3.4 s of server time -- and 44,016 of
 * those bytes, 0.306%, were the only part the list renders from. `data` was
 * 14,122,753 of them: worker signature images on pre-shift sheets, drawn
 * nowhere on a list of dates.
 *
 * An index row is therefore ~1 KB a date rather than ~334 KB, and the page can
 * be as wide as the memory bound allows instead of as narrow as the TRANSFER
 * bound forces. 500 dates is ~500 KB of body -- a tenth of the 5.8 MB page this
 * device is measured to survive receiving -- and it covers the server's own
 * 4000-date ceiling, eleven years of daily filing, in eight requests. For this
 * project's whole 43-date history it is ONE.
 *
 * NOT "the whole history in one unbounded request". The parameter-free response
 * is the complete set BY DESIGN, so asking for it is asking for 4000 dates at
 * whatever the server has; the page is what keeps one body bounded as the
 * history grows, which is the same rule HISTORY_PAGE_DATES exists under.
 */
export const INDEX_PAGE_DATES = 500;

/**
 * AND THE FIRST INDEX PAGE IS DELIBERATELY THE SMALL ONE.
 *
 * THE DEPLOY GAP IS REAL AND IT RUNS BOTH WAYS. This screen ships over the air
 * and the API ships to Railway, so one is always ahead of the other. A server
 * that predates `view=index` does not reject the parameter -- FastAPI ignores
 * an unknown query param -- it serves WHOLE DOCUMENTS for however many dates
 * `limit` asked for. At 500 that is ~166 MB on a project at the server's
 * ceiling, into a 60 s timeout, on a tablet in front of an inspector.
 *
 * So the walk asks its FIRST page at the document page size -- exactly today's
 * risk, no more -- and reads `view` off the response. A server that echoes
 * `view: "index"` has honoured it, and every page after the first is 500 wide.
 * A server that does not is an OLD server, and the walk says so rather than
 * committing an index assembled out of bodies it did not ask for.
 *
 * THE COST OF THE PROBE IS ONE EXTRA REQUEST OF ~10 KB on this project: 43
 * dates arrive as 10 + 33 instead of 43. That is the price of not being able
 * to ask a server what it supports without asking it for something.
 */
export const INDEX_PROBE_DATES = HISTORY_PAGE_DATES;

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

/**
 * One RECORD's signature marks: `{projectId}_{logId}.{version}.sig.json`.
 *
 * THE SAME DIRECTORY AND THE SAME NAMING DISCIPLINE as the day above — the
 * project prefix `pruneDayDetails` matches on, the version in the name, and
 * the same sanitiser — because this is the second half of the same cache and
 * not a second cache. `sweepDocCache` and the manifest store are untouched by
 * it: they name PDFs, and these are not PDFs.
 *
 * PER RECORD RATHER THAN PER DAY, AND THE REASON IS A COUNT THAT WOULD
 * OTHERWISE LIE. A per-day bundle filled one sheet at a time is PARTIAL, and
 * nothing in its name says so — so a progress line reading "43 of 43 days
 * saved" would be true of a tablet holding the pre-shift images and none of
 * the orientation ones. A record's file either exists or it does not, and the
 * record's own deferred set says whether it was needed.
 *
 * VERSIONED ON THE RECORD'S OWN STAMP, which is `pdfVersion` — so an amended
 * sheet misses rather than serving the superseded ink under the current
 * record's name.
 */
export function recordSignatureName(projectId, logId, version) {
  const clean = (v) => String(v === undefined || v === null ? '' : v).replace(/[^a-zA-Z0-9_-]/g, '_');
  return `${clean(projectId)}_${clean(logId)}.${clean(version)}.sig.json`;
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
 * Put one record's signature marks on disk. Returns whether they landed.
 *
 * NEVER THROWS, for `writeDayDetail`'s reason: a record whose ink could not be
 * written is a record that says "signed, image not saved on this tablet" —
 * degraded, honest, and not worth abandoning the rest of the fill over.
 */
export async function writeRecordSignatures(projectId, logId, version, images) {
  if (!canUseFs() || !projectId || !logId) return false;
  try {
    await ensureDayDir();
    await FileSystem.writeAsStringAsync(
      DAY_DIR + recordSignatureName(projectId, logId, version),
      JSON.stringify((images && typeof images === 'object') ? images : {}),
    );
    return true;
  } catch (_e) { return false; }
}

/**
 * One record's marks, or NULL.
 *
 * NULL IS NOT "NO SIGNATURES", and the distinction is the same one
 * `readDayDetail` makes. `{}` is a record whose marks are all unsigned — a real
 * answer, which the splice correctly does nothing with. NULL is a file this
 * device does not hold, which must leave the flags standing so the screen says
 * the image is not here rather than silently drawing nothing.
 */
export async function readRecordSignatures(projectId, logId, version) {
  if (!canUseFs() || !projectId || !logId) return null;
  try {
    const raw = await FileSystem.readAsStringAsync(
      DAY_DIR + recordSignatureName(projectId, logId, version),
    );
    const parsed = JSON.parse(raw);
    return (parsed && typeof parsed === 'object' && !Array.isArray(parsed))
      ? parsed : null;
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
 *
 * ── AND THE SIGNATURE FILES ARE IN THE KEEP-SET, WHICH IS NOT OPTIONAL ─────
 *
 * This sweep deletes EVERY `{projectId}_` name the keep-set does not hold, so a
 * keep-set built from day names alone would delete every signature file on the
 * tablet on the first complete walk after one landed — and then the backfill
 * would download them all again, and the walk after that would delete them
 * again. A fill that never finishes and an inspector who never gets the ink.
 *
 * NAMED OFF THE INDEX ROWS, NOT OFF THE DETAIL ON DISK. `identityRow` keeps
 * `{id, updated_at}` per log and `updated_at` IS `pdfVersion` — the same stamp
 * `recordSignatureName` versions on — so the committed index names every
 * record's signature file without a single detail file being opened. That is
 * what keeps this a ONE directory read.
 */
export async function pruneDayDetails(projectId, rows) {
  if (!canUseFs() || !projectId) return 0;
  const keep = new Set();
  for (const r of (Array.isArray(rows) ? rows : [])) {
    if (!r || !r.date) continue;
    keep.add(dayDetailName(projectId, r.date, r.cache_version));
    for (const l of (Array.isArray(r.logs) ? r.logs : [])) {
      const id = l && (l.id || l._id);
      if (id) keep.add(recordSignatureName(projectId, id, l.updated_at));
    }
  }
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

/** The index walk's path: identity rows, no `data`. Same cursor contract. */
const indexPagePath = (projectId, limit, before) =>
  `${pagePath(projectId, limit, before)}&view=index`;

/**
 * One day's documents, TEXT ONLY — every signature mark replaced by a
 * `*_deferred` flag beside where it was. 65.8% of this corpus is those marks.
 *
 * `view=text` AND THE ECHO IS CHECKED, like `view=index` above. A server that
 * predates the parameter ignores it and serves whole documents WITH their
 * signatures, which renders correctly and costs what it costs — see
 * `ensureDayDetail`, which reports which body it got rather than assuming.
 */
export const dayDetailPath = (projectId, date) =>
  `/api/logbooks/project/${projectId}/submitted?date=${encodeURIComponent(date)}&view=text`;

/** One record's signature marks. The second half of the read above. */
export const signatureImagesPath = (logId) =>
  `/api/logbooks/${encodeURIComponent(logId)}/signature-images`;

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
  // THE NEWEST RECENT_WINDOW_DATES DATES ARE KEPT, across as many pages as
  // that takes.
  //
  // This used to keep "the first page, and only the first", which was right
  // while the first page WAS the sixty-date window. The page is now ten, so
  // keeping only the first would hand web -- where readDayDetail can never
  // answer and `recent` is the only detail there is -- ten days instead of
  // sixty. So pages are merged in until the window is full, and from then on
  // released as they are stored. The high-water mark is the same sixty dates
  // it always was; it simply arrives in smaller requests.
  let recent = null;

  for (;;) {
    if (pages >= maxPages) {
      return { ok: true, complete: false, rows, pages, recent, reason: 'page-cap', error: null };
    }
    let body;
    try {
      const res = await apiClient.get(
        pagePath(projectId, limit, before),
        // A photo-bearing payload -- see HISTORY_PAGE_TIMEOUT_MS.
        { timeout: HISTORY_PAGE_TIMEOUT_MS },
      );
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
    // Fill the window, newest first -- pages arrive in descending date order,
    // so the first dates merged are the newest. Stop adding once it is full;
    // a date already in the window is never overwritten by a later page.
    if (recent === null) recent = {};
    for (const date of Object.keys(dates)) {
      if (Object.keys(recent).length >= RECENT_WINDOW_DATES) break;
      if (!(date in recent)) recent[date] = dates[date];
    }
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

// ── the index walk: the same rules, 0.3% of the bytes ──────────────────────

/**
 * Walk every page of the submitted-history INDEX, newest date first.
 *
 * Returns {ok, complete, rows, pages, reason, error} — the same contract as
 * `fetchSubmittedHistory`, and deliberately so: the completeness rule below is
 * the one thing a second walk is not allowed to weaken.
 *
 * THREE WAYS TO NOT BE COMPLETE, AND ALL THREE LAND IN THE SAME PLACE:
 *
 *   'unreachable'               a page never reached a server
 *   'no-completeness-contract'  a body declared neither `complete` nor
 *                               `next_before`. Reading it as the whole history
 *                               is the silent-ceiling defect relocated to the
 *                               client, and it was worth a whole fix once.
 *   'index-unsupported'         the server answered WITHOUT echoing
 *                               `view: "index"`. See INDEX_PROBE_DATES: that
 *                               is an old server serving whole documents, and
 *                               an index assembled from bodies the server did
 *                               not agree to serve is not an index this walk
 *                               may vouch for.
 *
 * `opts.onPage({pages, dates, rows})` is awaited before the next request. The
 * `rows` it hands over are a COPY and they are a FRAGMENT: the caller may draw
 * them while it is still loading, and may NOT present them as the list. That
 * is the screen's judgement to make, not this module's, which is why the raw
 * progress is reported rather than a boolean.
 */
export async function fetchSubmittedIndex(projectId, opts = {}) {
  const probeLimit = opts.probeLimit || INDEX_PROBE_DATES;
  const pageLimit = opts.limit || INDEX_PAGE_DATES;
  const onPage = opts.onPage;
  const rows = [];
  const seen = new Set();
  let before = null;
  let pages = 0;
  // DERIVED FROM THE PAGE SIZE, like MAX_HISTORY_PAGES and for the same
  // reason: a literal cap sized for one page width silently halves the history
  // it covers when the width changes, and a walk that hits its cap commits
  // nothing. Starts at the PROBE width because that is the only width page one
  // is asked at; it is raised once the probe has told us the real one.
  let maxPages = opts.maxPages || Math.ceil((SERVER_DATE_CEILING * 3) / probeLimit);

  for (;;) {
    if (pages >= maxPages) {
      return { ok: true, complete: false, rows, pages, reason: 'page-cap', error: null };
    }
    const limit = pages === 0 ? probeLimit : pageLimit;
    let body;
    try {
      const res = await apiClient.get(
        indexPagePath(projectId, limit, before),
        { timeout: HISTORY_PAGE_TIMEOUT_MS },
      );
      body = res && res.data;
    } catch (error) {
      return { ok: false, complete: false, rows, pages, reason: 'unreachable', error };
    }
    pages += 1;

    if (!body || (body.complete === undefined && body.next_before === undefined)) {
      return {
        ok: true, complete: false, rows, pages,
        reason: 'no-completeness-contract', error: null,
      };
    }
    if (body.view !== 'index') {
      return { ok: true, complete: false, rows, pages, reason: 'index-unsupported', error: null };
    }
    if (pages === 1 && !opts.maxPages) {
      maxPages = 1 + Math.ceil((SERVER_DATE_CEILING * 3) / pageLimit);
    }

    const dates = body.dates || {};
    for (const date of Object.keys(dates)) {
      if (seen.has(date)) continue;
      seen.add(date);
      rows.push(identityRow(projectId, date, dates[date]));
    }
    if (onPage) {
      try {
        await onPage({ pages, dates: rows.length, rows: rows.slice() });
      } catch (_e) { /* a progress callback may not fail a walk */ }
    }

    const next = body.next_before;
    if (next === null || next === undefined || next === '') {
      return { ok: true, complete: true, rows, pages, reason: null, error: null };
    }
    before = next;
  }
}

/**
 * One index sync: walk the index, commit it, prune detail it no longer names.
 *
 * SAME COMMIT RULES AS `syncLogbookHistory`, WORD FOR WORD, because they are
 * not about what the pages carried — they are about whether this device may
 * claim to hold the whole filed history. A replace needs a complete walk; a
 * union needs a complete prev; a walk that assembled nothing writes nothing;
 * and only a complete walk whose commit LANDED may prune.
 *
 * WHAT IT NO LONGER DOES IS WRITE DAY DETAIL. There is none in a body it asked
 * for. The detail arrives through `ensureDayDetail` when a day is opened and
 * through `backfillDayDetails` in the background, and `pruneDayDetails` is
 * unchanged by that: it deletes names this project's index does not carry, and
 * a date with no file yet simply has no name to delete.
 */
export async function syncLogbookIndex(projectId, opts = {}) {
  if (!projectId) {
    return {
      ok: false, complete: false, dates: 0, rows: [], stored: false,
      pruned: 0, pages: 0, reason: 'no-project', error: null,
    };
  }
  const scope = historyScope(projectId);
  const walk = await fetchSubmittedIndex(projectId, opts);
  const prev = await readHistoryIndex(projectId);
  const next = mergeHistoryRows(prev.rows, walk.rows, walk.complete);

  let wrote = { ok: false, reason: 'skipped' };
  if (walk.complete) {
    wrote = await writeManifestList(scope, next, { at: Date.now() });
  } else if (walk.rows.length === 0) {
    wrote = { ok: false, reason: `no-news:${walk.reason || 'incomplete'}` };
  } else if (prev.state !== 'complete') {
    wrote = { ok: false, reason: `partial-store:${prev.reason}` };
  } else {
    // The age is CARRIED, not refreshed — see syncLogbookHistory.
    wrote = await writeManifestList(scope, next, { at: prev.at === undefined ? null : prev.at });
  }

  const pruned = (walk.complete && wrote.ok) ? await pruneDayDetails(projectId, next) : 0;

  return {
    ok: walk.ok && walk.complete,
    complete: walk.complete,
    dates: next.length,
    // The committed list, so a caller that wants to BACKFILL against it does
    // not have to read the store back to find out what it just stored.
    rows: next,
    stored: wrote.ok === true,
    pruned,
    pages: walk.pages,
    reason: walk.complete ? (wrote.ok ? null : (wrote.reason || 'store-failed')) : walk.reason,
    error: walk.error || null,
  };
}

// ── day detail, fetched when it is wanted ──────────────────────────────────

/**
 * One day's whole documents: off the disk if they are there, off the server if
 * they are not, and on the disk afterwards either way.
 *
 * Returns {logs, fetched, stored, version, amended, reason, error}. `logs` is
 * NULL when the day could not be produced — never `[]`, which would draw a
 * filed day as blank to an inspector.
 *
 * THE DISK READ COMES FIRST AND IT IS THE WHOLE POINT. The version is part of
 * the file name, so a hit means "this device already holds this exact day as
 * filed" and NOTHING is transferred. That is the fault this kills: the old
 * walk re-downloaded all 14.36 MB and rewrote every day's detail on every
 * open, including the forty-three days that had not changed since the last one.
 *
 * AN EMPTY BODY FOR A DAY THE INDEX SAYS HAS RECORDS IS REFUSED. If the index
 * row carries logs and the server answers with none, the index is stale (a
 * withdrawal, a hard delete) — and writing `[]` under the index's version
 * would cache "this filed day is empty" and serve it to an inspector until the
 * index happened to be refreshed. Pass `opts.expectLogs` and it cannot happen.
 */
export async function ensureDayDetail(projectId, date, version, opts = {}) {
  if (!projectId || !date) {
    return { logs: null, fetched: false, stored: false, version: null, reason: 'no-project' };
  }
  const onDisk = await readDayDetail(projectId, date, version);
  if (Array.isArray(onDisk)) {
    return { logs: onDisk, fetched: false, stored: true, version, amended: false, reason: null };
  }
  // A CALLER THAT KNOWS IT IS OFFLINE DOES NOT SPEND 60 s FINDING OUT. The
  // screen already tracks that; this is how it says so.
  if (opts.offline === true) {
    return { logs: null, fetched: false, stored: false, version: null, reason: 'not-held' };
  }

  let body;
  try {
    const res = await apiClient.get(
      dayDetailPath(projectId, date),
      // A photo-bearing payload, like the document pages -- see
      // HISTORY_PAGE_TIMEOUT_MS. One day, not ten.
      { timeout: HISTORY_PAGE_TIMEOUT_MS },
    );
    body = res && res.data;
  } catch (error) {
    return { logs: null, fetched: false, stored: false, version: null, reason: 'unreachable', error };
  }

  const dates = (body && body.dates) || null;
  if (!dates || typeof dates !== 'object') {
    return { logs: null, fetched: true, stored: false, version: null, reason: 'no-dates' };
  }
  let logs = dates[date];
  if (!Array.isArray(logs)) {
    // The server buckets an undated log under "unknown", so the key it answers
    // with is not always the key that was asked for. One bucket, one answer.
    const keys = Object.keys(dates);
    logs = (keys.length === 1 && Array.isArray(dates[keys[0]])) ? dates[keys[0]] : null;
  }
  if (!Array.isArray(logs)) {
    return { logs: null, fetched: true, stored: false, version: null, reason: 'date-missing' };
  }
  if (logs.length === 0 && Number(opts.expectLogs) > 0) {
    return {
      logs: null, fetched: true, stored: false, version: null,
      reason: 'empty-for-a-filed-day',
    };
  }

  // NAMED ON WHAT ARRIVED, NOT ON WHAT WAS ASKED FOR. If the day was amended
  // between the index sync and this read, the version differs — and storing
  // the new documents under the OLD name is how a tablet comes to serve a
  // superseded record from a file that claims to be the current one. `amended`
  // says it happened so the caller can refresh the index.
  const fetchedVersion = dayReportVersion(logs, date);
  const stored = await writeDayDetail(projectId, date, fetchedVersion, logs);
  return {
    logs,
    fetched: true,
    stored,
    version: fetchedVersion,
    amended: version !== undefined && version !== null
      && String(fetchedVersion) !== String(version),
    // WHICH BODY THIS WAS, REPORTED AND NOT ASSUMED. `view=text` is additive,
    // so a server that predates it ignores the parameter and serves whole
    // documents WITH their signatures. That renders perfectly — the marks are
    // in hand and nothing is flagged, so `deferredSignaturePaths` is empty and
    // nothing is fetched — but the day cost what it used to cost, and the
    // screen is entitled to say so once rather than leaving a deploy gap
    // looking like a change that did not work.
    textView: !!(body && body.view === 'text'),
    reason: null,
  };
}

// ── the signature marks, fetched when a SHEET is drawn ─────────────────────

/**
 * One record's signature marks: off the disk if this tablet holds them, off
 * the server if it does not, and on the disk afterwards either way.
 *
 * Returns {images, fetched, stored, version, stale, reason, error}. `images` is
 * NULL when they could not be produced and `{}` when the record has none —
 * and those are different answers. NULL leaves the flags standing, so the
 * sheet says "signed, image not on this tablet"; `{}` is a record whose marks
 * are all genuinely unsigned, which there was never anything to fetch for.
 *
 * `stale` IS THE AMENDMENT GUARD. The server answers with the record's own
 * resolved stamp. If it does not match the version the day body was filed
 * under, the record was amended between the two reads — and splicing the new
 * ink into the old sheet, or storing it under the old sheet's name, is how a
 * tablet comes to show a corrected signature on a superseded record. Nothing
 * is spliced and nothing is written; the caller refreshes the index instead.
 *
 * THE VERSION IS PART OF THE FILE NAME for the same reason, so an amended
 * record MISSES on disk rather than serving the superseded ink.
 */
export async function ensureRecordSignatures(projectId, logId, version, opts = {}) {
  if (!projectId || !logId) {
    return { images: null, fetched: false, stored: false, version: null, reason: 'no-record' };
  }
  const onDisk = await readRecordSignatures(projectId, logId, version);
  if (onDisk) {
    return { images: onDisk, fetched: false, stored: true, version, stale: false, reason: null };
  }
  if (opts.offline === true) {
    return { images: null, fetched: false, stored: false, version: null, reason: 'not-held' };
  }

  let body;
  try {
    const res = await apiClient.get(
      signatureImagesPath(logId),
      { timeout: HISTORY_PAGE_TIMEOUT_MS },
    );
    body = res && res.data;
  } catch (error) {
    return { images: null, fetched: false, stored: false, version: null, reason: 'unreachable', error };
  }
  const images = (body && body.signatures && typeof body.signatures === 'object')
    ? body.signatures : null;
  if (!images) {
    // A SERVER THAT DOES NOT HAVE THIS ENDPOINT, or one that answered with
    // something else. Reported, never invented: the flags stay and the sheet
    // says the image is not here, which is true.
    return { images: null, fetched: true, stored: false, version: null, reason: 'no-signatures' };
  }
  const servedVersion = (body && body.version !== undefined) ? body.version : null;
  const asked = (version === undefined || version === null) ? null : String(version);
  if (asked !== null && servedVersion !== null && String(servedVersion) !== asked) {
    return {
      images: null, fetched: true, stored: false, version: servedVersion,
      stale: true, reason: 'amended',
    };
  }
  const stored = await writeRecordSignatures(projectId, logId, version, images);
  return { images, fetched: true, stored, version, stale: false, reason: null };
}

/**
 * How much of one day's ink this tablet holds. `{held, total, missing}` where
 * `missing` is the log ids still owed images.
 *
 * DERIVED FROM THE DAY'S OWN FLAGS, so a record with no marks is not counted as
 * missing and a full-document day (the deploy gap) reports `0 of 0` rather than
 * a fill that can never complete. EXACT, which a per-day bundle could not have
 * been — see `recordSignatureName`.
 */
export async function heldDaySignatures(projectId, logs) {
  const wanted = (Array.isArray(logs) ? logs : [])
    .map((l) => ({ id: (l && (l.id || l._id)) || '', version: pdfVersion(l),
                   owed: deferredSignaturePaths(l).length }))
    .filter((r) => r.id && r.owed > 0);
  if (!canUseFs() || !projectId) {
    return { held: 0, total: wanted.length, missing: wanted.map((r) => r.id), readable: false };
  }
  let names = [];
  try {
    names = await FileSystem.readDirectoryAsync(DAY_DIR);
  } catch (_e) { names = []; }
  const have = new Set(Array.isArray(names) ? names : []);
  const missing = wanted
    .filter((r) => !have.has(recordSignatureName(projectId, r.id, r.version)))
    .map((r) => r.id);
  return { held: wanted.length - missing.length, total: wanted.length, missing, readable: true };
}

/**
 * Every record of one day, spliced with whatever ink this tablet can produce.
 *
 * Returns {logs, fetched, failed, owed, amended}. ONE RECORD AT A TIME, in the
 * order given, so the sheet at the top of the screen fills first — on
 * 2026-08-28 the pre-shift tab is three sheets and 981,144 bytes, and waiting
 * for the third to draw the first is the wait this change exists to remove.
 *
 * `opts.onRecord({logs, fetched, owed})` is awaited after each record, which is
 * how the screen redraws progressively instead of at the end.
 *
 * NOTHING HERE CAN BLANK A SHEET. A record whose ink did not arrive keeps its
 * flags and renders as "signed, image not loaded"; the logs handed back are
 * always the full day.
 */
export async function fillDaySignatures(projectId, logs, opts = {}) {
  const list = Array.isArray(logs) ? logs.slice() : [];
  const owed = list.filter((l) => deferredSignaturePaths(l).length > 0).length;
  let out = list;
  let fetched = 0;
  let failed = 0;
  let amended = false;
  if (!projectId || owed === 0) {
    return { logs: out, fetched, failed, owed, amended };
  }
  for (let i = 0; i < out.length; i += 1) {
    const log = out[i];
    if (deferredSignaturePaths(log).length === 0) continue;
    if (opts.shouldStop) {
      let stop = false;
      try { stop = opts.shouldStop() === true; } catch (_e) { stop = false; }
      if (stop) break;
    }
    if (opts.beforeEach) {
      try { await opts.beforeEach(); } catch (_e) { /* a yield may not fail a fill */ }
    }
    const id = (log && (log.id || log._id)) || '';
    const r = await ensureRecordSignatures(projectId, id, pdfVersion(log), {
      offline: opts.offline === true,
    });
    if (r.stale) amended = true;
    if (r.images) {
      out = out.slice();
      out[i] = applySignatureImages(log, r.images);
      fetched += 1;
    } else {
      failed += 1;
      // THE DEAD ZONE IS DISCOVERED ONCE, NOT ONCE A SHEET. Sixteen records at
      // a 60-second timeout is sixteen minutes of a screen saying it is still
      // loading — the shape #681 removed from the day walk.
      if (r.reason === 'unreachable') break;
    }
    if (opts.onRecord) {
      try { await opts.onRecord({ logs: out, fetched, failed, owed }); } catch (_e) { /* ignored */ }
    }
  }
  return { logs: out, fetched, failed, owed, amended };
}

/**
 * How much of the filed history this device actually holds as openable detail.
 *
 * ONE DIRECTORY READ, NOT ONE STAT A DATE. The progress indicator this feeds
 * is redrawn on every step of a backfill; 43 `getInfoAsync` calls a redraw on a
 * gate tablet is the kind of measurement that becomes the thing it measures.
 *
 * `readable` IS NOT `held > 0`. On web there is no filesystem at all and
 * `readDayDetail` can never answer, so the honest report is "this surface does
 * not keep offline copies" — not "0 of 43 saved", which reads as a device
 * that is failing to save.
 */
export async function heldDayDetails(projectId, rows) {
  const list = (Array.isArray(rows) ? rows : []).filter((r) => r && r.date);
  if (!canUseFs() || !projectId) {
    return { held: 0, total: list.length, missing: list.map((r) => r.date), readable: false };
  }
  let names = [];
  try {
    names = await FileSystem.readDirectoryAsync(DAY_DIR);
  } catch (_e) {
    // No directory yet is not an error: it is a device that has filed nothing.
    names = [];
  }
  const have = new Set(Array.isArray(names) ? names : []);
  const missing = [];
  for (const r of list) {
    if (!have.has(dayDetailName(projectId, r.date, r.cache_version))) missing.push(r.date);
  }
  // `names` IS HANDED BACK, so a caller that needs a second fact about the
  // same directory does not take a second listing. `backfillDayDetails` counts
  // the signature files off this one, and `siteLogbookIndex.test.cjs` holds the
  // whole fill to a directory-read budget -- which a second read breaks.
  return { held: list.length - missing.length, total: list.length, missing,
           readable: true, names: Array.isArray(names) ? names : [] };
}

/**
 * Bounded so one run cannot occupy the device for ever, and RESUMABLE by
 * construction: what is already on disk is skipped in a single directory read,
 * so a first fill simply completes across the next few runs. Sized at a
 * calendar quarter of daily filing — more than any inspector asks for in one
 * visit, less than a project's whole history in one go.
 */
export const DETAIL_BACKFILL_PER_RUN = 60;

/**
 * Put every day's detail on the device, newest first, skipping what is there.
 *
 * THIS IS THE OFFLINE GUARANTEE, MOVED RATHER THAN REMOVED. The old walk filled
 * the device by downloading the whole corpus on the render path, which is why
 * an inspector waited ten minutes for a list. This fills it off the render
 * path: nothing here is awaited by a screen, every date it fetches is one the
 * device does not already hold, and `opts.beforeEach` is where the caller
 * yields the link back to a foreground read that started in the meantime.
 *
 * `onProgress({held, total, fetched, inkHeld, inkTotal})` IS A COUNT, NOT AN
 * ANIMATION. `held` is days whose detail file this device can open, `total` is
 * dates in the committed index, `fetched` is days this run actually
 * downloaded, and the `ink*` pair is the same two facts about SIGNATURE MARKS.
 * Every one of them is measured; none of them moves on a timer.
 *
 * IT STOPS ON THE FIRST UNREACHABLE DAY. A tablet that has gone into the dead
 * zone would otherwise spend forty-three 60-second timeouts discovering it one
 * date at a time.
 *
 * ── AND THE SIGNATURES ARE A SECOND PASS OF THE SAME FILL ──────────────────
 *
 * THE OFFLINE GUARANTEE DID NOT MOVE, ONLY THE MOMENT THE INK ARRIVES. What
 * this change alters is WHEN a signature reaches the tablet, never WHETHER: the
 * day read no longer carries the marks, so this fill fetches them, newest day
 * first, bounded by the same per-run cap, resumable off the same directory
 * read, yielding through the same `beforeEach`. A tablet that stopped carrying
 * signatures into the dead zone would be a worse record than the slow one.
 *
 * TEXT BEFORE INK, DELIBERATELY, AND THE ORDER IS THE PRIORITY. Pass one puts
 * every day's TEXT on the device; pass two puts the marks on it. A tablet
 * interrupted halfway — by the per-run cap, by the dead zone, by being carried
 * indoors — holds every day readable with "signed, image not loaded" where the
 * ink has not landed, rather than nine days complete and thirty-four with
 * nothing on them at all.
 *
 * A RECORD WITH NO MARKS GETS AN EMPTY FILE, and that is not a marker for its
 * own sake. Without it "this record is owed nothing" is indistinguishable from
 * "this record is owed something that has not arrived" without opening the
 * day's detail — so every run would re-read all 43 days' JSON to rediscover
 * that an OSHA log has never had a signature on it. With it, the steady state
 * is ONE directory read and no requests. Nothing is invented: the file is
 * written only where the stored day itself flags nothing, and `{}` spliced
 * into a record changes nothing about it.
 */
export async function backfillDayDetails(projectId, rows, opts = {}) {
  const perRun = opts.perRun || DETAIL_BACKFILL_PER_RUN;
  const onProgress = opts.onProgress;
  const list = (Array.isArray(rows) ? rows : [])
    .filter((r) => r && r.date)
    .slice()
    .sort((a, b) => String(b.date).localeCompare(String(a.date)));

  const state = await heldDayDetails(projectId, list);
  // EVERY RECORD THE INDEX NAMES, and whether its ink is already on disk. Off
  // the SAME directory listing `heldDayDetails` just took -- it hands the names
  // back for exactly this -- so the two counts this reports cost ONE read
  // between them rather than one each. `siteLogbookIndex.test.cjs` budgets the
  // reads of a whole fill, and it is right to: 43 listings a redraw on a gate
  // tablet is the kind of measurement that becomes the thing it measures.
  const onDiskNames = new Set(state.names || []);
  const inkRecords = [];
  for (const row of list) {
    for (const l of (Array.isArray(row.logs) ? row.logs : [])) {
      const id = l && (l.id || l._id);
      if (!id) continue;
      inkRecords.push({
        date: row.date,
        name: recordSignatureName(projectId, id, l.updated_at),
      });
    }
  }
  const inkTotal = inkRecords.length;
  const inkMissingDates = new Set(
    inkRecords.filter((r) => !onDiskNames.has(r.name)).map((r) => r.date),
  );

  const report = (extra) => ({
    held: state.held, total: state.total, fetched: 0, failed: 0,
    // CARRIED THROUGH, because a caller that cannot tell "this surface keeps no
    // offline copies" from "this device has saved none of them" shows a web
    // browser a progress bar that can never move.
    readable: state.readable,
    inkHeld: 0, inkTotal, inkFetched: 0,
    complete: false, reason: null, error: null, ...extra,
  });
  if (!canUseFs() || !projectId) return report({ reason: 'no-filesystem' });

  let held = state.held;
  let fetched = 0;
  let failed = 0;
  // RECORDS, NOT DAYS. One count of files that exist against files the index
  // names — the only two numbers that were both measured.
  let inkHeld = inkRecords.filter((r) => onDiskNames.has(r.name)).length;
  let inkFetched = 0;
  const tell = async () => {
    if (!onProgress) return;
    try {
      await onProgress({ held, total: state.total, fetched,
                         inkHeld, inkTotal, inkFetched });
    } catch (_e) { /* ignored */ }
  };
  await tell();

  const missing = new Set(state.missing);
  for (const row of list) {
    if (!missing.has(row.date)) continue;
    if (fetched + failed >= perRun) {
      return report({ held, fetched, failed, inkHeld, inkFetched, reason: 'per-run-cap' });
    }
    if (opts.shouldStop) {
      let stop = false;
      try { stop = opts.shouldStop() === true; } catch (_e) { stop = false; }
      if (stop) return report({ held, fetched, failed, inkHeld, inkFetched, reason: 'stopped' });
    }
    if (opts.beforeEach) {
      try { await opts.beforeEach(); } catch (_e) { /* a yield may not fail a fill */ }
    }
    const r = await ensureDayDetail(projectId, row.date, row.cache_version, {
      expectLogs: (row.logs || []).length,
    });
    if (r.stored) {
      fetched += 1;
      held += 1;
      // A DAY WHOSE TEXT JUST LANDED IS OWED ITS INK, whatever the directory
      // listing taken before the fetch said about it.
      inkMissingDates.add(row.date);
    } else {
      failed += 1;
      if (r.reason === 'unreachable') {
        return report({ held, fetched, failed, inkHeld, inkFetched,
                        reason: 'unreachable', error: r.error || null });
      }
    }
    await tell();
  }

  // ── PASS TWO: THE INK ───────────────────────────────────────────────────
  for (const row of list) {
    if (!inkMissingDates.has(row.date)) continue;
    if (fetched + failed >= perRun) {
      return report({ held, fetched, failed, inkHeld, inkFetched, reason: 'per-run-cap' });
    }
    if (opts.shouldStop) {
      let stop = false;
      try { stop = opts.shouldStop() === true; } catch (_e) { stop = false; }
      if (stop) return report({ held, fetched, failed, inkHeld, inkFetched, reason: 'stopped' });
    }
    // OFF THE DISK. The day's text is already here — that is what pass one is
    // for — so this is a file read and a parse, not a request.
    const dayLogs = await readDayDetail(projectId, row.date, row.cache_version);
    if (!Array.isArray(dayLogs)) continue;
    for (const log of dayLogs) {
      const id = (log && (log.id || log._id)) || '';
      if (!id) continue;
      const version = pdfVersion(log);
      if (onDiskNames.has(recordSignatureName(projectId, id, version))) continue;
      if (deferredSignaturePaths(log).length === 0) {
        // NOTHING IS OWED, AND IT IS WRITTEN DOWN. No request; see the header.
        if (await writeRecordSignatures(projectId, id, version, {})) {
          inkHeld += 1;
        }
        continue;
      }
      if (fetched + failed >= perRun) {
        return report({ held, fetched, failed, inkHeld, inkFetched, reason: 'per-run-cap' });
      }
      if (opts.beforeEach) {
        try { await opts.beforeEach(); } catch (_e) { /* a yield may not fail a fill */ }
      }
      const s = await ensureRecordSignatures(projectId, id, version);
      if (s.stored) {
        fetched += 1;
        inkFetched += 1;
        inkHeld += 1;
      } else {
        failed += 1;
        if (s.reason === 'unreachable') {
          return report({ held, fetched, failed, inkHeld, inkFetched,
                          reason: 'unreachable', error: s.error || null });
        }
      }
      await tell();
    }
  }

  return report({
    held, fetched, failed, inkHeld, inkFetched,
    // BOTH HALVES, because a day whose text is here and whose ink is not is
    // not a complete offline record. A `complete` that counted only the text
    // would report a finished fill to a tablet that cannot show an inspector a
    // single signature in the dead zone.
    complete: held >= state.total && inkHeld >= inkTotal,
    reason: null,
  });
}

export default {
  historyScope,
  HISTORY_PAGE_DATES,
  RECENT_WINDOW_DATES,
  HISTORY_PAGE_TIMEOUT_MS,
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
  INDEX_PAGE_DATES,
  INDEX_PROBE_DATES,
  DETAIL_BACKFILL_PER_RUN,
  dayDetailPath,
  fetchSubmittedIndex,
  syncLogbookIndex,
  ensureDayDetail,
  heldDayDetails,
  backfillDayDetails,
  // the deferral protocol — see "THREE STATES, NOT TWO"
  SIG_DEFERRED_SUFFIX,
  SIG_FIELDS,
  signatureMark,
  deferredSignaturePaths,
  dayHasDeferredSignatures,
  applySignatureImages,
  applyDaySignatureImages,
  signatureImagesPath,
  recordSignatureName,
  readRecordSignatures,
  writeRecordSignatures,
  ensureRecordSignatures,
  heldDaySignatures,
  fillDaySignatures,
};
