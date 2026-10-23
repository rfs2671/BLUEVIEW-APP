/**
 * Progressive offline cache for the web viewer: the Cache Storage API, keyed by a
 * synthetic same-origin-looking request (never a URL with a token in it). A tile
 * seen once is never fetched again, and a changed drawing (a new build) clears the
 * old build's entries. Everything is best effort: no Cache Storage (private mode,
 * insecure origin) or a full quota just means the network is used.
 */
const CACHE = 'bv-sheet-tiles-v1';
const ORIGIN = 'https://sheet-cache.invalid/';
const purged = new Set();

const open = async () => (typeof caches !== 'undefined' && caches.open ? caches.open(CACHE) : null);
const req = (fileId, build, name) => new Request(`${ORIGIN}${encodeURIComponent(fileId)}/${encodeURIComponent(build)}/${name}`);

async function purgeOtherBuilds(c, fileId, build) {
  const k = `${fileId}/${build}`;
  if (purged.has(k)) return;
  purged.add(k);
  try {
    const mine = `${ORIGIN}${encodeURIComponent(fileId)}/`;
    const keep = `${mine}${encodeURIComponent(build)}/`;
    for (const r of await c.keys()) {
      if (r.url.startsWith(mine) && !r.url.startsWith(keep)) await c.delete(r);
    }
  } catch (_e) { /* best effort */ }
}

export const tileDisk = {
  async getTile(fileId, build, desc) {
    try {
      const c = await open();
      const hit = c && (await c.match(req(fileId, build, desc.key)));
      return hit ? new Uint8Array(await hit.arrayBuffer()) : null;
    } catch (_e) { return null; }
  },
  async putTile(fileId, build, desc, bytes) {
    try {
      const c = await open();
      if (!c) return;
      await purgeOtherBuilds(c, fileId, build);
      await c.put(req(fileId, build, desc.key), new Response(bytes, { headers: { 'Content-Type': 'image/webp' } }));
    } catch (_e) { /* quota: fine */ }
  },
  async getJson(fileId, build, name) {
    try {
      const c = await open();
      const hit = c && (await c.match(req(fileId, build, `${name}.json`)));
      return hit ? await hit.json() : null;
    } catch (_e) { return null; }
  },
  async putJson(fileId, build, name, value) {
    try {
      const c = await open();
      if (!c) return;
      await c.put(req(fileId, build, `${name}.json`), new Response(JSON.stringify(value), { headers: { 'Content-Type': 'application/json' } }));
    } catch (_e) { /* quota: fine */ }
  },
};
export default tileDisk;
