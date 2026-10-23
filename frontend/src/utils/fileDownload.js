import * as FileSystem from 'expo-file-system/legacy';
import * as Sharing from 'expo-sharing';
import apiClient, { dropboxAPI, getToken } from './api';
import { getCachedDocFile } from './docCache';
import { isFirstPartyProxyUrl } from './pdfSrc';
import {
  downloadCacheKey, downloadSource, mimeTypeFor, shareFileName,
  signedUrlErrorKey,
} from './fileDownloadPlan';

/**
 * DOWNLOADING A PROJECT FILE — the side-effecting half. Rules and the reason
 * for them are in fileDownloadPlan.js.
 *
 * OTA-SAFE: expo-file-system (legacy API, already used by docCache) and
 * expo-sharing (in every binary since 1.1.2, used by the reports screens) are
 * the only native modules touched. Nothing here needs a rebuild.
 */

/** Thrown with `.code` = an i18n key in the `fileDownload` namespace. */
function downloadError(code) {
  const e = new Error(code);
  e.code = code;
  return e;
}

// ── WEB ─────────────────────────────────────────────────────────────────────

/**
 * Open a 15-minute signed link to one stored file in a new tab.
 *
 * THE TAB IS OPENED BEFORE THE AWAIT. A window.open that runs after a network
 * round trip is no longer inside the click, and popup blockers eat it; an
 * about:blank opened synchronously is pointed at the link once it arrives.
 * `attachment` adds dl=1 so the browser saves instead of displaying.
 */
export async function openSignedDownload(fileId, { attachment = false } = {}) {
  const win = typeof window !== 'undefined' ? window.open('about:blank', '_blank') : null;
  try {
    const { url } = await dropboxAPI.signedUrl(fileId);
    if (!url) throw downloadError('failBody');
    const target = attachment ? `${url}&dl=1` : url;
    if (win && !win.closed) {
      try { win.opener = null; } catch (_e) { /* cross-origin already */ }
      win.location.href = target;
      return;
    }
    // No 'noopener' feature here: with it window.open returns null even when
    // the tab DID open, which would read as blocked every time.
    const late = window.open(target, '_blank');
    if (!late) throw downloadError('popupBlocked');
    try { late.opener = null; } catch (_e) { /* ignore */ }
  } catch (e) {
    try { if (win && !win.closed) win.close(); } catch (_e) { /* ignore */ }
    if (e?.code) throw e;
    throw downloadError(signedUrlErrorKey(e));
  }
}

// ── NATIVE ──────────────────────────────────────────────────────────────────

// cacheDirectory, NOT documentDirectory: these copies exist to be handed to
// the share sheet, the OS may evict them, and a re-download is the cost. The
// offline plan cache is docCache's, in documentDirectory, and is not touched.
const DL_DIR = (FileSystem.cacheDirectory || '') + 'downloads/';

function expectedBytes(size) {
  const n = Number(size);
  return Number.isFinite(n) && n > 0 ? n : null;
}

async function isWhole(uri, want) {
  try {
    const info = await FileSystem.getInfoAsync(uri);
    return !!(info.exists && info.size > 0 && (want === null || Number(info.size) === want));
  } catch (_e) { return false; }
}

/**
 * Fetch one file to the device, then resolve `{ uri, cached }`.
 *
 * Returns `{ promise, cancel }` so the screen can show progress and stop it.
 * `onProgress(written, expected)` is called as bytes land; `expected` is null
 * when neither the server nor the listing gave a length.
 *
 * The token goes in the Authorization HEADER, and only to our own proxy; a
 * Dropbox file is fetched from the short-lived link the API hands back, with
 * no header at all. Bytes land in `{name}.part` and are renamed into place
 * only once whole, so a cancelled or dropped transfer never leaves a file
 * that looks finished.
 */
export function startNativeDownload({ file, projectId, onProgress } = {}) {
  let task = null;
  let cancelled = false;

  const cancel = async () => {
    cancelled = true;
    if (task) {
      try { await task.cancelAsync(); } catch (_e) { /* best effort */ }
    }
  };

  const promise = (async () => {
    const key = downloadCacheKey(file);
    const source = downloadSource(file);
    if (!key || source === 'none') throw downloadError('notStored');

    const name = shareFileName(file);
    const dir = `${DL_DIR}${key}/`;
    const dest = dir + name;
    const part = `${dest}.part`;
    const want = expectedBytes(file?.size);
    const scrub = async () => {
      try { await FileSystem.deleteAsync(part, { idempotent: true }); } catch (_e) { /* ignore */ }
    };

    if (await isWhole(dest, want)) return { uri: dest, cached: true };
    try { await FileSystem.makeDirectoryAsync(dir, { intermediates: true }); } catch (_e) { /* exists */ }

    // A PLAN ALREADY SAVED FOR OFFLINE IS THE SAME BYTES. Copied under its
    // real name rather than downloaded again — and this is the path that
    // still works in a cellar.
    const id = file?.id || file?._id;
    if (id && /\.pdf$/i.test(name)) {
      const saved = await getCachedDocFile(id, file?.cache_version ?? 0, 'pdf', { expectedSize: file?.size });
      if (saved) {
        try {
          await FileSystem.copyAsync({ from: saved, to: dest });
          if (await isWhole(dest, want)) return { uri: dest, cached: true };
        } catch (_e) { /* fall through to the network */ }
      }
    }

    let url = null;
    const headers = {};
    if (source === 'stored') {
      const raw = file.r2_url || file.directUrl;
      const base = apiClient?.defaults?.baseURL || '';
      url = /^https?:\/\//i.test(raw) ? raw : `${base}${raw}`;
      if (isFirstPartyProxyUrl(url, base)) {
        const token = await getToken();
        if (token) headers.Authorization = `Bearer ${token}`;
      }
    } else {
      try {
        const res = await dropboxAPI.getFileUrl(projectId, file.path);
        url = res?.url || null;
      } catch (e) {
        throw downloadError(signedUrlErrorKey(e));
      }
    }
    if (!url) throw downloadError('notStored');
    if (cancelled) throw downloadError('cancelled');

    task = FileSystem.createDownloadResumable(url, part, { headers }, (p) => {
      if (typeof onProgress !== 'function') return;
      const total = Number(p?.totalBytesExpectedToWrite);
      onProgress(Number(p?.totalBytesWritten) || 0, total > 0 ? total : want);
    });

    let res;
    try {
      res = await task.downloadAsync();
    } catch (_e) {
      await scrub();
      throw downloadError(cancelled ? 'cancelled' : 'network');
    }
    // A cancelled transfer resolves with nothing rather than rejecting.
    if (cancelled || !res) { await scrub(); throw downloadError('cancelled'); }
    if (res.status === 401 || res.status === 403) { await scrub(); throw downloadError('noAccess'); }
    if (res.status === 404) { await scrub(); throw downloadError('notStored'); }
    if (res.status !== 200) { await scrub(); throw downloadError('failBody'); }
    if (!(await isWhole(part, want))) { await scrub(); throw downloadError('network'); }

    try {
      await FileSystem.moveAsync({ from: part, to: dest });
    } catch (_e) {
      try { await FileSystem.deleteAsync(dest, { idempotent: true }); } catch (_e2) { /* ignore */ }
      await FileSystem.moveAsync({ from: part, to: dest });
    }
    return { uri: dest, cached: false };
  })();

  return { promise, cancel };
}

/** Hand a downloaded file to the OS share sheet. False when this device has
 *  no share sheet to offer. */
export async function shareDownloadedFile(uri, file) {
  if (!(await Sharing.isAvailableAsync())) return false;
  const name = shareFileName(file);
  const mimeType = mimeTypeFor(name);
  await Sharing.shareAsync(uri, {
    mimeType,
    dialogTitle: name,
    ...(mimeType === 'application/pdf' ? { UTI: 'com.adobe.pdf' } : {}),
  });
  return true;
}
