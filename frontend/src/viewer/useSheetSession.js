/**
 * Opens a drawing in the tile viewer, or says it cannot.
 *
 *   const s = useSheetSession({ enabled, projectId, fileId, platform, api });
 *   s.state       'idle' | 'loading' | 'tiled' | 'legacy'
 *   s.controller  the controller when state is 'tiled'
 *
 * 'legacy' means: keep the PDF viewer. It is the answer for a file with no tiles
 * yet (the manifest call also queues the compile), a compile still running, a
 * failed one, a set too large for tiles, an old backend, no network and no cached
 * manifest, or a runtime that cannot draw tiles. A drawing is never refused
 * because of anything here. The decision is made once per open, so a viewer never
 * swaps renderers under the reader's fingers.
 */
import { useEffect, useRef, useState } from 'react';
import { createSheetController } from './sheetController';
import { manifestUsable } from './sheetApi';

export const MANIFEST_TIMEOUT_MS = 6000;
export const REFRESH_EVERY_MS = 6000;
export const REFRESH_MAX_TRIES = 200;                 // about 20 minutes of the second pass

function withTimeout(promise, ms) {
  let t;
  const timeout = new Promise((_, rej) => { t = setTimeout(() => rej(new Error('timeout')), ms); });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(t));
}

/** Resolve a manifest: the network first, the offline copy when the network fails. */
export async function resolveManifest({ api, platform, projectId, fileId, cacheVersion, timeoutMs = MANIFEST_TIMEOUT_MS }) {
  const key = `manifest-v${cacheVersion ?? 0}`;
  try {
    const m = await withTimeout(api.manifest(projectId, fileId), timeoutMs);
    if (manifestUsable(m) && platform.disk && platform.disk.putJson) {
      Promise.resolve(platform.disk.putJson(fileId, m.build, key, m)).catch(() => {});
      Promise.resolve(platform.disk.putJson(fileId, 'latest', key, m)).catch(() => {});
    }
    return { manifest: m, offline: false };
  } catch (e) {
    // a 4xx is an answer (not allowed, not found): the PDF viewer shows the real error
    if (e && e.status && e.status < 500 && e.status !== 408 && e.status !== 429) return { manifest: null, offline: false, error: e };
    if (platform.disk && platform.disk.getJson) {
      const cached = await platform.disk.getJson(fileId, 'latest', key).catch(() => null);
      if (cached) return { manifest: cached, offline: true };
    }
    return { manifest: null, offline: false, error: e };
  }
}

/**
 * Which viewer a drawing is showing: 'tiled', 'legacy' (the PDF viewer) or 'pending'
 * (the decision has not been made yet). `state` is 'idle' for the one render before the
 * session's effect has run, so an enabled-but-idle session is PENDING, not legacy:
 * treating it as legacy started a full PDF download that was never needed and could
 * later mount beside the tile viewer.
 */
export function viewerMode({ enabled, state, failed }) {
  if (!enabled || failed) return 'legacy';
  if (state === 'tiled') return 'tiled';
  if (state === 'legacy') return 'legacy';
  return 'pending';
}

export function useSheetSession({ enabled, projectId, fileId, cacheVersion, platform, api }) {
  const [session, setSession] = useState({ state: 'idle', controller: null, offline: false });
  const ctlRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    let refreshTimer = null;
    if (!enabled || !projectId || !fileId || !platform || !api) {
      setSession({ state: 'idle', controller: null, offline: false });
      return undefined;
    }
    if (!platform.available()) {
      setSession({ state: 'legacy', controller: null, offline: false, reason: 'unsupported' });
      return undefined;
    }
    setSession({ state: 'loading', controller: null, offline: false });
    (async () => {
      const { manifest, offline, error } = await resolveManifest({ api, platform, projectId, fileId, cacheVersion });
      if (cancelled) return;
      if (!manifestUsable(manifest)) {
        setSession({ state: 'legacy', controller: null, offline: false, reason: manifest ? manifest.status : 'unavailable', error });
        return;
      }
      const controller = createSheetController({
        api, projectId, fileId, manifest, decode: platform.decode, dispose: platform.dispose,
        disk: platform.disk, dpr: platform.dpr(), maxBytes: platform.maxBytes,
      });
      ctlRef.current = controller;
      // keep the offline store inside its quota; never blocks opening the drawing
      if (platform.disk && platform.disk.sweep) Promise.resolve(platform.disk.sweep({ activeFileId: fileId })).catch(() => {});
      setSession({ state: 'tiled', controller, offline, manifest });
      // Opened on the first pass ("ready"): keep asking until the deep levels are done, so
      // zoom past level 2 works in this same session without reopening the drawing.
      if (manifest.status === 'ready' && !offline) {
        let tries = 0;
        const tick = async () => {
          if (cancelled || tries >= REFRESH_MAX_TRIES) return;
          tries += 1;
          try {
            const m = await api.manifest(projectId, fileId);
            if (cancelled) return;
            if (m && m.build === manifest.build && manifestUsable(m)) {
              controller.refreshManifest(m);
              if (m.status === 'complete') return;
            } else if (m && m.status === 'failed') return;
          } catch (_e) { /* try again next time */ }
          refreshTimer = setTimeout(tick, REFRESH_EVERY_MS);
        };
        refreshTimer = setTimeout(tick, REFRESH_EVERY_MS);
      }
    })();
    return () => {
      cancelled = true;
      if (refreshTimer) clearTimeout(refreshTimer);
      if (ctlRef.current) { ctlRef.current.destroy(); ctlRef.current = null; }
    };
  }, [enabled, projectId, fileId, cacheVersion, platform, api]);

  return session;
}
