/**
 * SEARCH IN A PDF — the part that reads text and finds words.
 *
 * The staged pdf.js viewer (pdfjsViewer.js) includes PDF_SEARCH_SCRIPT in its
 * page, and the tests run the same string in a sandbox: Hermes keeps no
 * function source, so the page's code has to exist as a string, and a string
 * nobody runs is how a broken search would ship. Plain ES5, like the rest of
 * the page.
 *
 *   pdfSearchBuildPage(items, viewport, transform, styles)
 *       One page's text (pdf.js `getTextContent().items`), lowercased, the
 *       runs joined by a space, and where each run sits on the page — as
 *       fractions of the page, so a highlight stays put at any zoom.
 *   pdfSearchFind(page, query)   every [start, end) of the query in the page
 *   pdfSearchRects(page, a, b, measure)
 *       the boxes, in page fractions, of [a, b). Where in a run a word
 *       starts is MEASURED (`measure(text, fontFamily)`, a canvas in the
 *       page) in the run's own font family: a footer line is one run, and
 *       counting characters put the box a word early.
 *   pdfSearchNorm(text)          lowercased, whitespace collapsed
 *
 * Text only: a scanned sheet with no text layer has nothing to find, and the
 * viewer says so rather than "no matches".
 */

export const PDF_SEARCH_SCRIPT = [
  'function pdfSearchNorm(s){',
  '  return String(s == null ? "" : s).replace(/\\s+/g, " ").toLowerCase().replace(/^ +| +$/g, "");',
  '}',
  'function pdfSearchBuildPage(items, vp, transform, styles){',
  '  var text = "", spans = [], W = vp.width || 1, H = vp.height || 1, sc = vp.scale || 1;',
  '  var list = items || [];',
  '  for (var i = 0; i < list.length; i++) {',
  '    var it = list[i];',
  '    if (!it || typeof it.str !== "string") continue;',
  '    var raw = it.str.replace(/\\s+/g, " ");',
  '    var s = raw.toLowerCase();',
  '    if (s && s !== " ") {',
  '      if (text && text.charAt(text.length - 1) !== " " && s.charAt(0) !== " ") text += " ";',
  '      var start = text.length;',
  '      text += s;',
  '      var tx = transform(vp.transform, it.transform);',
  '      var len = Math.sqrt(tx[0] * tx[0] + tx[1] * tx[1]) || 1;',
  '      var adv = (it.width || 0) * sc;',
  // The run as a quad: its baseline origin, the advance along it, and the
  // glyph's up vector (the transformed y axis, as long as the font is tall).
  // Any rotation reads right this way, including vertical text on a sheet.
  '      var st = styles && it.fontName ? styles[it.fontName] : null;',
  '      spans.push({ start: start, end: text.length, raw: raw, font: (st && st.fontFamily) || "",',
  '        ox: tx[4] / W, oy: tx[5] / H,',
  '        ax: (tx[0] / len) * adv / W, ay: (tx[1] / len) * adv / H,',
  '        ux: tx[2] / W, uy: tx[3] / H });',
  '    }',
  '    if (it.hasEOL && text && text.charAt(text.length - 1) !== " ") text += " ";',
  '  }',
  '  return { text: text, spans: spans };',
  '}',
  'function pdfSearchFind(page, q){',
  '  var out = [];',
  '  if (!page || !q) return out;',
  '  var i = page.text.indexOf(q);',
  '  while (i >= 0) {',
  '    out.push([i, i + q.length]);',
  '    i = page.text.indexOf(q, i + q.length);',
  '  }',
  '  return out;',
  '}',
  'function pdfSearchRects(page, a, b, measure){',
  '  var rects = [];',
  '  if (!page) return rects;',
  '  for (var i = 0; i < page.spans.length; i++) {',
  '    var sp = page.spans[i];',
  '    var s = Math.max(a, sp.start), e = Math.min(b, sp.end);',
  '    if (e <= s) continue;',
  '    var n = (sp.end - sp.start) || 1;',
  '    var fa = (s - sp.start) / n, fb = (e - sp.start) / n;',
  '    if (measure && sp.raw && sp.raw.length === n) {',
  '      var all = measure(sp.raw, sp.font);',
  '      if (all > 0) {',
  '        fa = measure(sp.raw.slice(0, s - sp.start), sp.font) / all;',
  '        fb = measure(sp.raw.slice(0, e - sp.start), sp.font) / all;',
  '      }',
  '    }',
  '    var x0 = sp.ox + sp.ax * fa, y0 = sp.oy + sp.ay * fa;',
  '    var x1 = sp.ox + sp.ax * fb, y1 = sp.oy + sp.ay * fb;',
  '    var xs = [x0, x1, x0 + sp.ux, x1 + sp.ux], ys = [y0, y1, y0 + sp.uy, y1 + sp.uy];',
  '    var minX = Math.min.apply(null, xs), maxX = Math.max.apply(null, xs);',
  '    var minY = Math.min.apply(null, ys), maxY = Math.max.apply(null, ys);',
  '    minX = Math.max(0, minX); minY = Math.max(0, minY);',
  '    maxX = Math.min(1, maxX); maxY = Math.min(1, maxY);',
  '    if (maxX > minX && maxY > minY) rects.push({ x: minX, y: minY, w: maxX - minX, h: maxY - minY });',
  '  }',
  '  return rects;',
  '}',
].join('\n');

/**
 * What the search bar says, from the page's last `pdf-search` message:
 * "Searching…", "3 of 12", "No matches", "No searchable text in this PDF".
 */
export function searchStatusLabel(res, query) {
  const q = String(query || '').trim();
  if (!q || !res) return '';
  if (res.total > 0) {
    const more = res.done ? '' : '+';
    return `${Math.max(1, res.current || 1)} of ${res.total}${more}`;
  }
  if (!res.done) return 'Searching…';
  if (!res.hasText) return 'No searchable text in this PDF';
  return 'No matches';
}

/** The query as the page compares it (pdfSearchNorm): lowercased, spaces
 *  collapsed, trimmed — so the app can tell its own reply from a stale one. */
export function searchQueryNorm(text) {
  return String(text == null ? '' : text).replace(/\s+/g, ' ').toLowerCase().trim();
}
