/**
 * SEVERAL PICKED FILES, UPLOADED ONE AFTER ANOTHER.
 *
 * The pickers on the Files, Documents and photo screens returned only the
 * first file a person chose (operator, 2026-11-11: "won't let me choose more
 * than 1 at a time"). They now ask for several and hand them here.
 *
 * ONE AT A TIME, NOT ALL AT ONCE: a phone on site signal uploading twelve
 * PDFs in parallel fails most of them; one after another, each gets the line.
 * A FAILURE NEVER STOPS THE REST: the files after it are still sent, and the
 * summary names exactly which did not go, so nobody re-uploads the whole set.
 */

/**
 * @param {Array} items         what the picker returned
 * @param {(item) => Promise} uploadOne  throws on failure
 * @returns {Promise<{ok: Array, failed: Array<{item, error}>}>}
 */
export async function uploadEach(items, uploadOne) {
  const ok = [];
  const failed = [];
  for (const item of items || []) {
    try {
      await uploadOne(item);
      ok.push(item);
    } catch (error) {
      failed.push({ item, error });
    }
  }
  return { ok, failed };
}

/** The server's own words for a failed upload, else `fallback`. */
export function errorDetail(error, fallback) {
  return (
    error?.response?.data?.detail
    || error?.response?.statusText
    || error?.message
    || (typeof error === 'string' ? error : null)
    || fallback
  );
}

/**
 * The one toast for a batch: {kind, title, body}. `t` is useT('multiUpload');
 * `nameOf` reads an item's display name.
 */
export function batchSummary(t, result, nameOf) {
  const n = result.ok.length + result.failed.length;
  if (!result.failed.length) {
    return { kind: 'success', title: t('uploadedTitle'), body: t('uploadedAll').replace('{n}', String(n)) };
  }
  const names = result.failed.map((f) => nameOf(f.item)).filter(Boolean).join(', ');
  return {
    kind: result.ok.length ? 'warning' : 'error',
    title: t('someFailedTitle'),
    body: t('someFailedBody')
      .replace('{ok}', String(result.ok.length))
      .replace('{n}', String(n))
      .replace('{names}', names),
  };
}

export default { uploadEach, errorDetail, batchSummary };
