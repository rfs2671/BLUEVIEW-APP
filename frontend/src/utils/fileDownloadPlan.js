/**
 * HOW A DOWNLOAD IS ADDRESSED, CACHED AND NAMED — the pure half.
 *
 * Pure on purpose (no react-native, no expo import, no storage read), same as
 * pdfSrc.js, so the rules are testable without a renderer.
 *
 * THE LINK NEVER CARRIES A TOKEN.
 *   web    — the app asks /files/{id}/signed-url with its bearer header and
 *            opens the 120-second link that comes back.
 *   native — the bytes are fetched with the token in the Authorization
 *            HEADER, then handed to the share sheet as a local file.
 * The old button built `/content?token=` from window.localStorage, which a
 * phone does not have: the token was empty and the browser opened on
 * {"detail":"Not authenticated"}.
 *
 * Tests: src/utils/fileDownload.test.cjs
 */

/** How a file's bytes are reached. `stored` = in R2 behind our proxy (the
 *  record has an id and an r2_url); `dropbox` = only a Dropbox path, served by
 *  a short-lived Dropbox link; `none` = nothing to fetch. */
export function downloadSource(file) {
  const id = file?.id || file?._id;
  if (id && (file?.r2_url || file?.directUrl)) return 'stored';
  if (file?.path) return 'dropbox';
  return 'none';
}

// djb2, base36. Stable and collision-shy for a cache directory name.
function hash32(s) {
  let h = 5381;
  for (let i = 0; i < s.length; i += 1) h = ((h * 33) ^ s.charCodeAt(i)) >>> 0;
  return h.toString(36);
}

/**
 * The cache key for a downloaded copy. THE CONTENT HASH WHEN THERE IS ONE:
 * the listing carries Dropbox's hash of the bytes, so the same drawing is one
 * download however many times it is shared, and a changed drawing is a new
 * key. A direct upload has no hash, so it falls back to what identifies its
 * bytes instead: id, cache_version and size.
 */
export function downloadCacheKey(file) {
  const hash = String(file?.content_hash || '').trim();
  if (/^[A-Za-z0-9]{16,128}$/.test(hash)) return `h_${hash}`;
  const id = String(file?.id || file?._id || '');
  const seed = id
    ? `${id}.${file?.cache_version ?? 0}.${Number(file?.size) || 0}`
    : String(file?.path || '');
  if (!seed) return '';
  const safe = seed.replace(/[^A-Za-z0-9_.-]/g, '_');
  return safe.length <= 64 ? `f_${safe}` : `f_${safe.slice(-40)}_${hash32(seed)}`;
}

/**
 * The name the share sheet shows and the receiving app saves under. The
 * file's own name, with anything a filesystem refuses replaced. Never empty,
 * never a path.
 */
export function shareFileName(file) {
  const raw = String(file?.name || '').split(/[\\/]/).pop() || '';
  // eslint-disable-next-line no-control-regex
  const clean = raw.replace(/[\u0000-\u001f<>:"|?*]/g, '_').trim();
  return clean && clean !== '.' && clean !== '..' ? clean.slice(-120) : 'file';
}

const MIME_BY_EXT = {
  pdf: 'application/pdf',
  png: 'image/png',
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  heic: 'image/heic',
  doc: 'application/msword',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  xls: 'application/vnd.ms-excel',
  xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  csv: 'text/csv',
  txt: 'text/plain',
  dwg: 'application/acad',
  zip: 'application/zip',
};

export function mimeTypeFor(name) {
  const m = /\.([A-Za-z0-9]+)$/.exec(String(name || ''));
  return (m && MIME_BY_EXT[m[1].toLowerCase()]) || 'application/octet-stream';
}

/** 0..1, or null when the total is unknown (an indeterminate bar). */
export function downloadFraction(written, expected) {
  const w = Number(written);
  const e = Number(expected);
  if (!(e > 0) || !(w >= 0)) return null;
  return Math.min(1, w / e);
}

/**
 * Which message an API refusal of /signed-url maps to. Keys are in the
 * `fileDownload` i18n namespace.
 */
export function signedUrlErrorKey(error) {
  const status = error?.response?.status;
  if (status === 403) return 'noAccess';
  if (status === 404) return 'notStored';
  if (!error?.response) return 'network';
  return 'failBody';
}
