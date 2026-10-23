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

/**
 * Every place `query` occurs. A one-word query matches inside words ("402" finds
 * "A-402"); a phrase matches consecutive words of one line, the first as an ending,
 * the middle ones whole, the last as a beginning. Returns
 * [{page, bbox, text, boxes}] in reading order (page, then line, then position).
 */
export function searchIndexes(indexes, query) {
  const toks = queryTokens(query);
  if (!toks.length) return [];
  const out = [];
  const pages = Array.from(indexes.keys()).sort((a, b) => a - b);
  for (const page of pages) {
    const words = (indexes.get(page) || {}).words || [];
    const nw = words.map((w) => norm(w.text));
    for (let i = 0; i < words.length; i += 1) {
      if (toks.length === 1) {
        if (nw[i].includes(toks[0])) out.push({ page, bbox: words[i].bbox, text: words[i].text, boxes: [words[i].bbox] });
      } else if (nw[i].endsWith(toks[0]) && nw[i] !== '') {
        const boxes = [words[i].bbox];
        const texts = [words[i].text];
        let ok = true;
        for (let k = 1; k < toks.length; k += 1) {
          const w = words[i + k];
          const n = nw[i + k];
          if (!w || w.line !== words[i].line || !n) { ok = false; break; }
          const last = k === toks.length - 1;
          if (last ? !n.startsWith(toks[k]) : n !== toks[k]) { ok = false; break; }
          boxes.push(w.bbox);
          texts.push(w.text);
        }
        if (ok) out.push({ page, bbox: unionBox(boxes), text: texts.join(' '), boxes });
      }
      if (out.length >= MAX_MATCHES) return out;
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
