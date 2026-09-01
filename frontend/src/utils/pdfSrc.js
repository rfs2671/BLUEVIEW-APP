/**
 * A PDF URL CAN CARRY A BEARER TOKEN, SO IT MAY ONLY EVER POINT AT US.
 *
 * WHAT WENT WRONG. Project files are served by a PERMANENT authenticated
 * backend proxy (`/api/projects/{pid}/files/{fid}/content`). A WebView cannot
 * put an Authorization header on the document request, so the native viewer
 * appended the JWT as `?token=`. On Android it then url-ENCODED that whole
 * token-bearing url into a third party's page:
 *
 *     https://mozilla.github.io/pdf.js/web/viewer.html?file=<encoded url>
 *
 * That is not an edge case — it was the DEFAULT Android path. Every plan open
 * put a live 30-day Levelog bearer token into mozilla.github.io's request log
 * and referrer surface.
 *
 * THE TWO RULES THIS MODULE HOLDS.
 *
 *   1. A token is appended ONLY when the resolved url's ORIGIN is our own API
 *      base. The same path shape on another host gets nothing — the old check
 *      looked at the path only, so a url merely SHAPED like ours would have
 *      been handed the token.
 *
 *   2. Android is never given a remote url to render. Android's WebView has no
 *      PDF renderer, which is the whole reason a viewer was wrapped around it.
 *      Instead the bytes are fetched to disk FIRST with the JWT in the
 *      Authorization HEADER (docCache.cacheDocFile already does exactly this,
 *      and the document screens already call it on every open), and drawn by
 *      the pdf.js copy staged on the device by pdfjsViewer.js. A token in a
 *      header cannot land in anyone else's log.
 *
 * iOS keeps the direct url: WKWebView renders application/pdf through PDFKit
 * itself, so the url goes to api.levelog.com and nowhere else.
 *
 * Pure on purpose — no react-native import, no storage read — so the rules are
 * testable without a renderer. `platformOS` and `apiBase` are arguments for the
 * same reason.
 *
 * Tests: src/utils/pdfTokenOrigin.test.cjs
 */

/** The one path shape the backend proxy serves, anchored at both ends. */
const PROXY_PATH_RE = /^\/api\/projects\/[^/]+\/files\/[^/]+\/content$/;

/** True for the `file://` uris docCache and the offline staging hand back. */
export function isLocalFileUri(uri) {
  return typeof uri === 'string' && uri.startsWith('file://');
}

/** `https://host:port` of an absolute http(s) url, lowercased. '' otherwise. */
export function originOf(url) {
  const m = /^(https?:\/\/[^/?#]+)/i.exec(typeof url === 'string' ? url : '');
  return m ? m[1].toLowerCase() : '';
}

/** A relative `/api/...` resolved against the API base. Anything already
 *  absolute is returned untouched — it is not ours to rewrite. */
export function toAbsolutePdfUrl(rawUrl, apiBase) {
  if (typeof rawUrl !== 'string' || !rawUrl) return null;
  if (!rawUrl.startsWith('/')) return rawUrl;
  return `${String(apiBase || '').replace(/\/+$/, '')}${rawUrl}`;
}

/**
 * True only for OUR OWN file-content proxy: same origin as the API base AND
 * the proxy path. Origin first — that is the half the old check was missing.
 */
export function isFirstPartyProxyUrl(absUrl, apiBase) {
  const base = originOf(apiBase);
  const origin = originOf(absUrl);
  if (!base || origin !== base) return false;
  const path = String(absUrl).slice(origin.length).split(/[?#]/)[0];
  return PROXY_PATH_RE.test(path);
}

/**
 * The url a native WKWebView (or a web <iframe>) may load directly.
 *
 * The JWT rides along ONLY for our own proxy, which cannot be read any other
 * way from inside a WebView. A presigned R2/Dropbox url needs no token and is
 * returned bare; a foreign url is returned bare even if its path looks like
 * ours; a `file://` is already final and is never decorated.
 */
export function authorizedPdfUrl(rawUrl, { apiBase, token } = {}) {
  if (isLocalFileUri(rawUrl)) return rawUrl;
  const abs = toAbsolutePdfUrl(rawUrl, apiBase);
  if (!abs) return null;
  if (!token || !isFirstPartyProxyUrl(abs, apiBase)) return abs;
  return `${abs}${abs.includes('?') ? '&' : '?'}token=${encodeURIComponent(token)}`;
}

// ── How a native platform gets its bytes ───────────────────────────────────
export const PDF_SOURCE_NONE = 'none';
export const PDF_SOURCE_LOCAL = 'local';
export const PDF_SOURCE_DOWNLOAD = 'download';
export const PDF_SOURCE_DIRECT = 'direct';

/**
 * What the native viewer must do with `rawUrl` on this platform.
 *
 *   none     — nothing to show.
 *   local    — already a `file://`; hand it to the renderer as is.
 *   direct   — the platform renders a remote PDF itself. iOS ONLY.
 *   download — fetch the bytes to disk (token in the Authorization header),
 *              then render the local copy.
 *
 * iOS is named explicitly rather than Android being singled out: any platform
 * WITHOUT a native PDF renderer must download, and defaulting the unknown case
 * to `download` keeps a remote url out of a wrapped viewer no matter what
 * `Platform.OS` reports.
 */
export function pdfSourcePlan(rawUrl, platformOS) {
  if (!rawUrl) return { kind: PDF_SOURCE_NONE };
  if (isLocalFileUri(rawUrl)) return { kind: PDF_SOURCE_LOCAL, uri: rawUrl };
  if (platformOS === 'ios') return { kind: PDF_SOURCE_DIRECT };
  return { kind: PDF_SOURCE_DOWNLOAD };
}

// djb2, base36. Only needs to be stable and collision-shy for a cache name.
function hash32(s) {
  let h = 5381;
  for (let i = 0; i < s.length; i += 1) h = ((h * 33) ^ s.charCodeAt(i)) >>> 0;
  return h.toString(36);
}

/** Longest key we will build. docCache turns this into a filename, and a
 *  Dropbox path or a presigned url is far longer than a filename may be. */
const MAX_KEY = 48;

/**
 * Cache key for a document the viewer has to pull to disk itself. The record's
 * id when it has one (that is what docCache's own callers use, so the viewer
 * hits the copy they already downloaded); otherwise the Dropbox path or the
 * url, reduced to something bounded and filesystem-safe.
 */
export function pdfCacheKey(file, rawUrl) {
  const id = file?.id || file?._id;
  if (id) return String(id);
  const seed = file?.path || rawUrl || '';
  if (!seed) return '';
  const safe = String(seed).replace(/[^A-Za-z0-9_-]/g, '_');
  if (safe.length <= MAX_KEY) return safe;
  return `${safe.slice(-32)}_${hash32(String(seed))}`;
}
