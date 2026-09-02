import React, { createContext, useContext, useEffect, useState, useCallback } from 'react';
import { readCachedProjectList } from '../utils/projectCache';
import { getToken, getStoredUser } from '../utils/api';
import { useAuth } from './AuthContext';

/**
 * PROJECT-CACHE HYDRATION, HOISTED TO THE PARENT LAYOUT.
 *
 * Every cached read in this app used to be screen-local: app/index.jsx and
 * app/logbooks/index.jsx each awaited readCachedProjectList() inside their own
 * fetch handler. A hydration that runs only where the operator happens to land
 * cannot serve a screen reached DIRECTLY — and the gate tablet is exactly the
 * device where someone opens Log Books and never touches a dashboard. So it
 * runs here, once, above the Stack, and it is as available as the nav is.
 *
 * ── WHAT THIS IS NOT ───────────────────────────────────────────────────────
 *
 * IT IS NOT A REPLACEMENT FOR A SCREEN'S FETCH, and that distinction is the
 * whole safety argument. Three screens deliberately want a FAILED read rather
 * than a cached one:
 *
 *   project/[id]/trades.jsx          readOnly = fetchState !== 'ok'
 *   project/[id]/report-settings.jsx readOnly = fetchState !== 'ok'
 *   workers/[id].jsx                 edit button hidden unless detailState==='ok'
 *
 * All three derive that gate from the STATUS OF THEIR OWN REQUEST, never from
 * the provenance of the data on screen — `setFetchState(r.status)` sits beside
 * `data = await readCachedProject(...)`, not inside it. That is why hoisting is
 * safe, and it is also the line that must not be crossed: this provider never
 * mints a fetch status, so cached data arriving earlier can never be mistaken
 * for a read that succeeded. Screens keep their own settleFetch, their own
 * fetchState, their OfflineNotice, their failure-only cache reads and their
 * write-refusals. This adds availability, and nothing else.
 *
 * ── WHY IT DOES NOT WAIT FOR AUTH ──────────────────────────────────────────
 *
 * Cold boot, no network, on the gate tablet, before this:
 *
 *   AuthProvider mounts with isLoading=true and renders children immediately
 *   -> the screen mounts with loading=true and paints "Loading log books…"
 *   -> the screen's fetch is gated on isAuthenticated, so it does NOT run
 *   -> validateSession() reads token + stored user from AsyncStorage (~ms)
 *   -> then awaits the /auth/me round trip, which offline rejects — instantly
 *      on airplane mode, but up to the 25s DEFAULT_TIMEOUT_MS in a dead zone
 *      where the socket connects and never answers
 *   -> only THEN does isAuthenticated flip and the screen read its cache
 *
 * Nothing flashes an error (the /login redirect is guarded on !authLoading),
 * but the cached list sat readable in AsyncStorage the entire time, behind a
 * network call, on a device with no network. Hydration is therefore keyed on
 * the STORED session — a token plus a stored user, both present in
 * milliseconds — rather than on the VALIDATED one. AuthContext already extends
 * exactly this trust to storedUser when validation fails offline; this is the
 * same trust, for a strictly smaller purpose (what to paint, never what to
 * permit). The server remains authoritative for every write.
 *
 * ── WHY A SESSION IS REQUIRED AT ALL ───────────────────────────────────────
 *
 * bv_projects_cache is ONE GLOBAL KEY and clearAuth() removes only the token
 * and the stored user — the project list outlives the logout that should have
 * ended it. Hydrating on a device with no session would show one man's jobs to
 * whoever picked the tablet up next. So: no stored session, no hydration, and
 * the state is dropped again the moment auth settles to logged-out.
 *
 * Scoping WITHIN a session stays where it already lives: the screens' own
 * filterVisibleProjects(), which narrows a CP to assigned_projects and re-runs
 * against the live user. This provider hands over the raw cached list and the
 * stored user; it does not invent a second, competing authorization rule.
 */

const ProjectCacheContext = createContext(null);

const EMPTY = Object.freeze({ projects: [], hydrated: false, source: null, user: null });
const NO_SESSION = Object.freeze({ projects: [], hydrated: true, source: null, user: null });

/**
 * Read the device's cached project list, if and only if this device holds a
 * stored session.
 *
 * Returns { projects, hydrated, source, user }. `source` is 'cache' when a read
 * was actually performed and null when it was not — a consumer can always tell
 * where what it is holding came from.
 *
 * NEVER THROWS AND NEVER AWAITS THE NETWORK. It runs on the root layout, so a
 * throw here would take the ErrorBoundary — and the whole app — down on first
 * paint, and an await on anything network-shaped would reintroduce the very
 * stall it exists to remove.
 */
export async function hydrateProjectCache() {
  // The "I did not look" result, written out rather than referenced: this
  // function is extracted and executed verbatim by
  // src/utils/projectCacheHydration.test.cjs, so every name it uses beyond its
  // three injected dependencies is harness drift waiting to happen.
  const noSession = { projects: [], hydrated: true, source: null, user: null };

  let token = null;
  let user = null;
  try {
    token = await getToken();
    user = await getStoredUser();
  } catch (_e) {
    // An unreadable session store is not a session.
    return noSession;
  }

  // Both halves, or nothing. A token with no stored user is a half-cleared
  // logout, not a session to hydrate for.
  if (!token || !user) return noSession;

  let projects = [];
  try {
    const list = await readCachedProjectList();
    projects = Array.isArray(list) ? list : [];
  } catch (_e) {
    // readCachedProjectList already swallows its own errors, but this runs on
    // the layout and must be safe even if that ever changes.
    projects = [];
  }

  // An empty cache is still a completed hydration, and it is still cache-shaped
  // provenance — "I looked, and there was nothing saved" is a different fact
  // from "I did not look", and only the second is source: null.
  return { projects, hydrated: true, source: 'cache', user };
}

export function ProjectCacheProvider({ children }) {
  const { isAuthenticated, isLoading, user } = useAuth();
  const [state, setState] = useState(EMPTY);

  const rehydrate = useCallback(async () => {
    const next = await hydrateProjectCache();
    setState(next);
    return next;
  }, []);

  // AT MOUNT — not after auth resolves. This is the point of the whole file.
  useEffect(() => { rehydrate(); }, [rehydrate]);

  // Auth settled to logged-out: drop the list. The AsyncStorage key survives
  // clearAuth(), so without this the next person to pick the tablet up would
  // still be holding the last user's projects in memory.
  useEffect(() => {
    if (!isLoading && !isAuthenticated) setState({ ...NO_SESSION });
  }, [isLoading, isAuthenticated]);

  // A fresh login (or a different user on the same device) re-reads the cache,
  // which by then is whatever that user's screens have written through.
  const userId = user?.id || user?._id || null;
  useEffect(() => {
    if (isAuthenticated) rehydrate();
  }, [isAuthenticated, userId, rehydrate]);

  /** A single cached project out of the already-hydrated list, or null. Saves
   *  a screen an AsyncStorage round trip for the common case; the per-id
   *  readCachedProject() fallback in the detail screens is unaffected and
   *  stays the authority for a project that was never in this list. */
  const getCachedProject = useCallback(
    (projectId) => {
      if (!projectId) return null;
      const want = String(projectId);
      return state.projects.find((p) => String(p?.id ?? p?._id) === want) || null;
    },
    [state.projects],
  );

  const value = {
    cachedProjects: state.projects,
    hydrated: state.hydrated,
    // 'cache' | null — provenance, carried so no consumer has to assume.
    source: state.source,
    storedUser: state.user,
    getCachedProject,
    rehydrate,
  };

  return (
    <ProjectCacheContext.Provider value={value}>
      {children}
    </ProjectCacheContext.Provider>
  );
}

/**
 * Returns a safe, inert value rather than throwing when the provider is
 * missing. Same rule useToast() had to adopt: a hook that throws in one branch
 * is a conditional-hook footprint, and this one is called from screens that
 * also render in harnesses where no layout is mounted.
 */
const FALLBACK = {
  cachedProjects: [],
  hydrated: false,
  source: null,
  storedUser: null,
  getCachedProject: () => null,
  rehydrate: async () => ({ ...NO_SESSION }),
};

export function useProjectCache() {
  return useContext(ProjectCacheContext) || FALLBACK;
}

export default ProjectCacheContext;
