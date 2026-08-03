import AsyncStorage from '@react-native-async-storage/async-storage';

/**
 * P1 — project-selection offline cache.
 *
 * The project list + detail were server-only: index.jsx calls
 * projectsAPI.getAll() and project/[id].jsx calls projectsAPI.getById(), whose
 * only "offline fallback" was a WatermelonDB query (the dormant store nothing
 * populates), so a CP offline couldn't even reach a project's logbooks.
 *
 * Same pure-AsyncStorage write-through pattern as useCpProfile / logbookDrafts:
 * cache on every successful server read, read the cache when offline. No native
 * module, no WatermelonDB — OTA-deliverable.
 */

const LIST_KEY = 'bv_projects_cache';
const PROJ_PREFIX = 'bv_project:';

const idOf = (p) => (p && (p.id || p._id)) || null;

/** Cache the full project list AND each project individually (for detail reads). */
export async function cacheProjectList(projects) {
  if (!Array.isArray(projects)) return;
  try {
    await AsyncStorage.setItem(LIST_KEY, JSON.stringify(projects));
    await Promise.all(
      projects
        .map((p) => {
          const id = idOf(p);
          return id ? AsyncStorage.setItem(`${PROJ_PREFIX}${id}`, JSON.stringify(p)) : null;
        })
        .filter(Boolean),
    );
  } catch (_e) { /* non-fatal — the network read still succeeded */ }
}

export async function readCachedProjectList() {
  try {
    const raw = await AsyncStorage.getItem(LIST_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch (_e) {
    return [];
  }
}

/** Cache a single project (call after a successful getById). */
export async function cacheProject(project) {
  const id = idOf(project);
  if (!id) return;
  try {
    await AsyncStorage.setItem(`${PROJ_PREFIX}${id}`, JSON.stringify(project));
  } catch (_e) { /* non-fatal */ }
}

/** Read a single project from cache (the offline fallback for the detail screen). */
export async function readCachedProject(projectId) {
  try {
    const raw = await AsyncStorage.getItem(`${PROJ_PREFIX}${projectId}`);
    return raw ? JSON.parse(raw) : null;
  } catch (_e) {
    return null;
  }
}
