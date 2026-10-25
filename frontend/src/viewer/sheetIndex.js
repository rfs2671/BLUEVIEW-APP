/**
 * Search and hit-testing over a page's `sheet_index` (the words and callouts the
 * backend extracted), entirely in memory: no PDF is opened and nothing crosses a
 * bridge, so results appear as fast as the string compare.
 *
 * A page index is {page, words: [{text, bbox: [x0,y0,x1,y1] (0..1), line}],
 * callouts: [{label, detail, sheet, bbox, target}], detail_markers, own_sheet}.
 */

/** Lower-case letters and digits only: "A-402", "a 402" and "A402" are one string. */
export function norm(s) {
  return String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, '');
}

/** The words of a query, normalised; empty tokens dropped. */
export function queryTokens(q) {
  return String(q || '').split(/\s+/).map(norm).filter(Boolean);
}

export function unionBox(boxes) {
  let x0 = 1; let y0 = 1; let x1 = 0; let y1 = 0;
  for (const b of boxes) {
    if (b[0] < x0) x0 = b[0];
    if (b[1] < y0) y0 = b[1];
    if (b[2] > x1) x1 = b[2];
    if (b[3] > y1) y1 = b[3];
  }
  return [x0, y0, x1, y1];
}

const MAX_MATCHES = 5000;

// CAD text is often tracked out one glyph at a time ("B U L K H EA D"), so a search is
// run over each LINE as one string (letters and digits only) and a hit is mapped back to
// the words it covers. That finds "bulkhead" in spaced letters, "a402" in "A 402", and a
// phrase across words, with one rule.
const _lines = new WeakMap();
function linesOf(index) {
  let cached = _lines.get(index);
  if (cached) return cached;
  const words = (index && index.words) || [];
  const byLine = new Map();
  words.forEach((w, i) => {
    const k = w.line == null ? `w${i}` : w.line;
    if (!byLine.has(k)) byLine.set(k, []);
    byLine.get(k).push(i);
  });
  cached = [];
  for (const ids of byLine.values()) {
    ids.sort((a, b) => words[a].bbox[0] - words[b].bbox[0]);
    let text = '';
    const owner = [];
    for (const wi of ids) {
      const n = norm(words[wi].text);
      for (let c = 0; c < n.length; c += 1) owner.push(wi);
      text += n;
    }
    if (text) cached.push({ text, owner });
  }
  _lines.set(index, cached);
  return cached;
}

/**
 * Every place `query` occurs, in reading order (page, then line order of the index). A
 * hit may start or end inside a word ("402" finds "A-402") and may span words of one
 * line. Returns [{page, bbox, text, boxes}].
 */
export function searchIndexes(indexes, query) {
  const q = queryTokens(query).join('');
  if (!q) return [];
  const out = [];
  const pages = Array.from(indexes.keys()).sort((a, b) => a - b);
  for (const page of pages) {
    const index = indexes.get(page);
    if (!index || !index.words) continue;
    const words = index.words;
    for (const { text, owner } of linesOf(index)) {
      let at = text.indexOf(q);
      while (at !== -1) {
        const ids = Array.from(new Set(owner.slice(at, at + q.length)));
        const boxes = ids.map((wi) => words[wi].bbox);
        out.push({ page, bbox: unionBox(boxes), text: ids.map((wi) => words[wi].text).join(' '), boxes });
        if (out.length >= MAX_MATCHES) return out;
        at = text.indexOf(q, at + q.length);
      }
    }
  }
  return out;
}

/** "3 of 12" / "No matches" / "" for the search bar. */
export function matchLabel(total, current, query) {
  if (!norm(query)) return '';
  if (!total) return 'No matches';
  return `${current + 1} of ${total}${total >= MAX_MATCHES ? '+' : ''}`;
}

/** Step through matches, wrapping. */
export function stepIndex(current, total, dir) {
  if (!total) return 0;
  return (((current + dir) % total) + total) % total;
}

/** The callout (if any) at a normalised point on a page; a small pad forgives a finger. */
export function hitCallout(index, fx, fy, pad = 0.004) {
  const cs = (index && index.callouts) || [];
  let best = null;
  let bestArea = Infinity;
  for (const c of cs) {
    const b = c.bbox;
    if (!b || fx < b[0] - pad || fx > b[2] + pad || fy < b[1] - pad || fy > b[3] + pad) continue;
    const area = (b[2] - b[0]) * (b[3] - b[1]);
    if (area < bestArea) { best = c; bestArea = area; }              // the innermost one
  }
  return best;
}

/** The normalised box a callout's portal shows, and whether it is the real detail
 *  (the title found in the target page's text) or an estimate. */
export function portalBox(callout) {
  const t = callout && callout.target;
  if (!t) return null;
  const box = t.crop || null;
  if (!box) return { file_id: t.file_id, page: t.page, sheet: t.sheet, detail: callout.detail || null, box: null, exact: false };
  return { file_id: t.file_id, page: t.page, sheet: t.sheet, detail: callout.detail || null, box, exact: Boolean(t.crop_exact) };
}
