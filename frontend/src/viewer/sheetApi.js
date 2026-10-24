/**
 * The viewer's HTTP: manifest, per-page index, tiles and previews. Every request
 * carries `Authorization: Bearer`; there is no query-string token anywhere. The
 * token and base URL are injected so the same code runs on web and native and is
 * testable with a fake `fetch`.
 */
import { TileFetchError } from './tileCache';

export function createSheetApi({ apiBase, getToken, fetchImpl }) {
  const doFetch = fetchImpl || ((...a) => fetch(...a));
  const base = String(apiBase || '').replace(/\/+$/, '');

  async function request(path, { signal, timeoutMs = 20000 } = {}) {
    const token = await getToken();
    if (!token) throw new TileFetchError(401, 'not signed in');
    const ctl = new AbortController();
    const onAbort = () => ctl.abort();
    if (signal) {
      if (signal.aborted) ctl.abort(); else signal.addEventListener('abort', onAbort, { once: true });
    }
    const timer = setTimeout(() => ctl.abort(), timeoutMs);
    try {
      const res = await doFetch(`${base}${path}`, { headers: { Authorization: `Bearer ${token}` }, signal: ctl.signal });
      if (!res.ok) throw new TileFetchError(res.status);
      return res;
    } finally {
      clearTimeout(timer);
      if (signal) signal.removeEventListener('abort', onAbort);
    }
  }

  const fileBase = (projectId, fileId) =>
    `/api/projects/${encodeURIComponent(projectId)}/files/${encodeURIComponent(fileId)}/sheets`;

  return {
    async manifest(projectId, fileId, opts) {
      return (await request(fileBase(projectId, fileId), opts)).json();
    },
    async index(projectId, fileId, page, build, opts) {
      return (await request(`${fileBase(projectId, fileId)}/${page}/index?b=${encodeURIComponent(build)}`, opts)).json();
    },
    async tile(projectId, fileId, build, desc, signal) {
      const path = `${fileBase(projectId, fileId)}/${desc.page}/tiles/${desc.z}/${desc.x}/${desc.y}?b=${encodeURIComponent(build)}`;
      return (await request(path, { signal })).arrayBuffer();
    },
    async preview(projectId, fileId, build, page, signal) {
      const path = `${fileBase(projectId, fileId)}/${page}/preview?b=${encodeURIComponent(build)}`;
      return (await request(path, { signal })).arrayBuffer();
    },
  };
}

/** The viewer shows tiles only for a finished first pass; anything else keeps the PDF viewer. */
export function manifestUsable(m) {
  return Boolean(m && (m.status === 'ready' || m.status === 'complete') && Array.isArray(m.pages)
    && m.pages.length > 0 && m.pages.some((p) => p.ready));
}
