import NetInfo from '@react-native-community/netinfo';
import { AppState } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { projectsAPI } from './api';
import {
  syncSiteManifest,
  DISK_RESERVE_PHONE_BYTES,
} from './siteManifestStore';

/**
 * AN ADMIN'S PHONE FILLS ITSELF, FOR EVERY PROJECT HE IS ON.
 *
 * THE RULING THIS SERVES. Every device that can view plans holds every plan
 * for its projects, offline and complete, at all times, with no user action.
 * The scenario is an inspector arriving unannounced, or an admin in a basement
 * needing a sheet he has never opened. "Open it once while online" is not an
 * instruction that survives a jobsite.
 *
 * The gate tablet has done this since siteManifestStore shipped. An admin's
 * phone did nothing at all: the only caching it performed was
 * ensureCachedDocFile at the moment a plan was tapped, which is precisely the
 * instruction being ruled out.
 *
 * ── THE SERVER NEEDED NO CHANGE, WHICH IS WHY THIS IS SMALL ────────────────
 *
 * GET /projects/{id}/manifest is gated on require_approved +
 * require_project_access, NOT on site mode, and its subfolder visibility
 * filter only applies when the caller IS a site device. An admin already
 * receives the project's complete file set. `syncSiteManifest` is likewise
 * project-scoped and mode-agnostic. So the reusable part is the entire store,
 * and what is genuinely new is the trigger wiring and the multi-project walk.
 *
 * ── FOUR THINGS A PHONE IS NOT ────────────────────────────────────────────
 *
 * IT IS NOT ONE PROJECT. The tablet syncs the job it is bolted to; an admin
 * carries all of them. Measured today: ~100 MB across the two live sites, one
 * of which has no files at all. At that scale this is not a byte problem, and
 * "only the projects he is currently on" invites exactly the failure the
 * ruling exists to prevent — the sheet he needs is the one he never opened.
 * `aggregateBytes` exists so the day that stops being true is seen coming.
 *
 * IT IS NOT MAINS-POWERED. The tablet's five-minute interval is free on a
 * permanently-foregrounded appliance and hostile on a phone in a pocket, where
 * it would buy nothing: the app is not running. So there is NO INTERVAL here.
 * Foreground, reconnect and login are the whole trigger set, and they are the
 * moments a phone can actually act on.
 *
 * IT IS NOT ON WI-FI. Pulling a hundred megabytes of plans over a metered
 * connection is a bill somebody did not agree to, so an expensive connection
 * defers by default. `allowMetered` overrides it, and the override is a
 * deliberate act rather than a setting that decays into always-on.
 *
 * IT IS NOT DEDICATED. The tablet may run down to 200 MB free because it holds
 * this project and nothing else. A phone holds its owner's life, and a plan
 * set that consumes its last 200 MB does not degrade the viewer, it breaks the
 * phone. Hence DISK_RESERVE_PHONE_BYTES.
 *
 * ── SEQUENTIAL, AND IN THE ORDER HE IS LIKELY TO NEED THEM ────────────────
 *
 * One project at a time. Four concurrent multi-megabyte downloads on a phone
 * is how a foreground app gets killed, and the store is not written to be
 * re-entrant across projects — it holds a module-level in-flight guard.
 *
 * Most-recently-opened first, so a phone that is interrupted — signal drops,
 * app backgrounded, space runs out — holds the useful half rather than
 * whichever half the server happened to list first.
 */

// When each project's plans were last opened on this device. A small map, not
// a per-project key: it is read in full on every run to order the walk, and
// one read beats N.
const LAST_OPENED_KEY = 'plan_project_last_opened';

// Bounded so a long-lived install cannot grow this without limit. Far more
// than any admin's project count; the cap is a guard, not a policy.
const LAST_OPENED_CAP = 200;

/**
 * Note that this project's plans were opened. Called by the plan list.
 *
 * THE ONLY NEW TRACKING THIS FEATURE ADDS, and it is deliberately the cheapest
 * thing that answers "which project does he actually use": the moment he opens
 * its plans. Never throws — an ordering hint must not be able to fail a screen.
 */
export async function noteProjectOpened(projectId, now = Date.now()) {
  const pid = String(projectId || '');
  if (!pid) return false;
  try {
    const raw = await AsyncStorage.getItem(LAST_OPENED_KEY);
    const map = raw ? JSON.parse(raw) : {};
    const next = (map && typeof map === 'object') ? map : {};
    next[pid] = now;
    const entries = Object.entries(next)
      .sort((a, b) => Number(b[1]) - Number(a[1]))
      .slice(0, LAST_OPENED_CAP);
    await AsyncStorage.setItem(LAST_OPENED_KEY, JSON.stringify(
      Object.fromEntries(entries),
    ));
    return true;
  } catch (_e) {
    return false;
  }
}

/** The map, or an empty one. Never throws. */
export async function readLastOpened() {
  try {
    const raw = await AsyncStorage.getItem(LAST_OPENED_KEY);
    const map = raw ? JSON.parse(raw) : null;
    return (map && typeof map === 'object') ? map : {};
  } catch (_e) {
    return {};
  }
}

/**
 * The walk order: most-recently-opened first, then everything never opened.
 *
 * PURE, so the ordering rule is testable without a device — and it is a rule
 * worth testing, because it decides what an interrupted phone ends up holding.
 * A project never opened sorts last but is NOT dropped: the whole point of the
 * ruling is the sheet he has never looked at.
 */
export function orderProjects(projectIds, lastOpened = {}) {
  const seen = new Set();
  const ids = [];
  for (const raw of projectIds || []) {
    const id = String(raw || '');
    if (!id || seen.has(id)) continue;
    seen.add(id);
    ids.push(id);
  }
  return ids.sort((a, b) => {
    const ta = Number(lastOpened[a]) || 0;
    const tb = Number(lastOpened[b]) || 0;
    if (ta !== tb) return tb - ta;
    // Stable and reproducible for the never-opened tail, so two phones with
    // the same assignment fill in the same direction.
    return a < b ? -1 : (a > b ? 1 : 0);
  });
}

/**
 * Should this run download over the connection it has?
 *
 * UNKNOWN IS TREATED AS UNMETERED, deliberately. `isConnectionExpensive` is
 * undefined on plenty of Android builds, and refusing to fill a phone because
 * the platform declined to answer would reproduce the empty-device failure
 * this whole feature exists to remove — against a device that is probably on
 * Wi-Fi. A wrong bill is recoverable; a missing sheet in a basement is not.
 */
export function mayDownloadOn(state, allowMetered = false) {
  // ONLINE FIRST, ALWAYS. `allowMetered` says "spend his data if you must" —
  // it is not a claim that a connection exists, and checking it first made it
  // one: an offline phone with the override on reported that it could
  // download, and the walk then failed one project at a time against a network
  // that was not there.
  const online = !!(state && state.isConnected && state.isInternetReachable !== false);
  if (!online) return false;
  if (allowMetered) return true;
  const details = state.details || {};
  return details.isConnectionExpensive !== true;
}

/**
 * What this admin's phone is being asked to hold, in bytes, per project.
 *
 * REPORTED BEFORE SHIPPING SO THE DAY IT STOPS BEING SMALL IS SEEN COMING. The
 * manifest already carries every file's stored size, so this is a sum of
 * numbers the device is fetching anyway rather than a new measurement.
 */
export async function aggregateBytes(projectIds, opts = {}) {
  const fetchManifest = opts.fetchManifest;
  if (typeof fetchManifest !== 'function') return { total: 0, projects: [] };
  const projects = [];
  let total = 0;
  for (const pid of projectIds || []) {
    try {
      const m = await fetchManifest(pid);
      const rows = (m && m.files && m.files.rows) || [];
      const bytes = rows.reduce((n, r) => n + (Number(r.s) || 0), 0);
      projects.push({ projectId: pid, bytes, files: rows.length, complete: !!m.complete });
      total += bytes;
    } catch (_e) {
      projects.push({ projectId: pid, bytes: null, files: null, complete: false });
    }
  }
  return { total, projects };
}

let inFlight = false;

/**
 * One pass over every assigned project. Sequential, ordered, never throws.
 *
 * RE-ENTRANCY IS REFUSED rather than queued: the triggers below can fire
 * together (a reconnect that also foregrounds the app), and two overlapping
 * walks would fight over the store's own in-flight guard and double the
 * download pressure on the device least able to take it.
 */
export async function prefetchAssignedProjects(opts = {}) {
  if (inFlight) return { ok: false, reason: 'in-flight', projects: [] };
  inFlight = true;
  try {
    const listProjects = opts.listProjects || projectsAPI.getAll;
    const run = opts.run || syncSiteManifest;
    const netState = opts.netState || (() => NetInfo.fetch());

    const state = await netState();
    if (!mayDownloadOn(state, opts.allowMetered)) {
      return {
        ok: false,
        reason: (state && state.isConnected) ? 'metered' : 'offline',
        projects: [],
      };
    }

    let all = [];
    try {
      all = await listProjects();
    } catch (_e) {
      // No list, no walk. Offline is the ordinary case here and is not a fault
      // — the next foreground or reconnect tries again.
      return { ok: false, reason: 'no-project-list', projects: [] };
    }

    const ids = orderProjects(
      (Array.isArray(all) ? all : []).map((p) => p && (p.id || p._id)),
      await readLastOpened(),
    );

    const projects = [];
    for (const pid of ids) {
      try {
        const r = await run(pid, { reserveBytes: DISK_RESERVE_PHONE_BYTES });
        projects.push({ projectId: pid, ok: !!(r && r.ok), spaceReason: r && r.spaceReason });
      } catch (_e) {
        // ONE PROJECT'S FAILURE DOES NOT END THE WALK. The next project may be
        // the one he needs, and a phone that stopped at the first error would
        // hold nothing for it.
        projects.push({ projectId: pid, ok: false, spaceReason: null });
      }
    }
    return { ok: true, reason: null, projects };
  } finally {
    inFlight = false;
  }
}

/**
 * Start the triggers: foreground, reconnect, and the call itself (login).
 *
 * NO INTERVAL, and that is the design rather than an omission. A phone in a
 * pocket is not running this code; a timer would fire only while the app is
 * already foregrounded, which the foreground trigger already covers, and would
 * otherwise spend battery re-asking a question nothing has changed the answer
 * to. The tablet's interval is right for a mains-powered appliance and wrong
 * here.
 *
 * `enabled` is read at fire time rather than captured, so a sign-out stops the
 * walk without the caller having to unmount anything.
 */
export function setupAdminPlanPrefetch(isEnabled, opts = {}) {
  const run = opts.run || ((o) => prefetchAssignedProjects(o));

  const fire = () => {
    let on = false;
    try { on = !!(isEnabled && isEnabled()); } catch (_e) { on = false; }
    if (!on) return;
    Promise.resolve(run(opts)).catch(() => {});
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

  fire();

  return () => {
    try { if (typeof unsubNet === 'function') unsubNet(); } catch (_e) {}
    try { if (appSub && typeof appSub.remove === 'function') appSub.remove(); } catch (_e) {}
  };
}

export default setupAdminPlanPrefetch;
