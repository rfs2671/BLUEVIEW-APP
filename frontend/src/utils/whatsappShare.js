// Share a plan note via WhatsApp. Pure helpers + one injectable runner.
//
// No backend, no provider, no phone number: the user picks the chat inside
// WhatsApp. The link in the message is the app's existing short link
// (https://levelog.com/a/<annotation id>, the same one _send_annotation_emails
// puts in the email). It is NOT public and NOT tokenized: it redirects to the
// app, which asks for a login.

export const ANNOTATION_LINK_BASE = 'https://levelog.com/a/';

// wa.me/?text= is a GET URL. Browsers/WhatsApp tolerate a few thousand
// characters, but some intermediaries cut near 2000. We keep the ENCODED text
// (what actually lands in the URL) at or under this many characters.
// Percent-encoding makes emoji (~12 chars each) and newlines (3) expensive, so
// the budget is measured encoded, not in characters typed.
export const WA_MAX_ENCODED_TEXT = 1800;
export const WA_URL_PREFIX = 'https://wa.me/?text=';
// The project name and sheet label are clamped so a pathological value can
// never eat the budget that belongs to the note and the link.
export const WA_MAX_LABEL_CHARS = 80;
export const ELLIPSIS = '…';

const enc = (s) => encodeURIComponent(s);
const chars = (s) => Array.from(s); // code points: never split a surrogate pair

function clamp(value, max) {
  const s = String(value == null ? '' : value).replace(/\s+/g, ' ').trim();
  const cs = chars(s);
  return cs.length > max ? cs.slice(0, max - 1).join('').trimEnd() + ELLIPSIS : s;
}

export function annotationLink(annotationId) {
  if (annotationId == null || annotationId === '') return '';
  return ANNOTATION_LINK_BASE + enc(String(annotationId));
}

// "A-101.pdf" -> "A-101"; adds the page when the PDF has more than one.
export function sheetLabelFor(file, pageNumber) {
  const raw = (file && (file.name || file.filename || file.path)) || '';
  const base = String(raw).split('/').pop().replace(/\.pdf$/i, '');
  const page = Number(pageNumber);
  const label = clamp(base, WA_MAX_LABEL_CHARS);
  if (page > 1) return label ? `${label} (p. ${page})` : `p. ${page}`;
  return label;
}

// Truncate `note` so the WHOLE message, encoded, fits the budget. The note is
// the only part that shrinks; the link is always intact and last.
export function buildShareText({ projectName, sheetLabel, note, link, maxEncoded = WA_MAX_ENCODED_TEXT }) {
  const project = clamp(projectName, WA_MAX_LABEL_CHARS);
  const sheet = clamp(sheetLabel, WA_MAX_LABEL_CHARS);
  const body = String(note == null ? '' : note).replace(/\r\n?/g, '\n').trim();

  const head = ['Levelog plan note'];
  if (project) head.push(`Project: ${project}`);
  if (sheet) head.push(`Sheet: ${sheet}`);
  const tail = link ? `\n\nOpen in Levelog (login required):\n${link}` : '';

  const assemble = (n) => head.join('\n') + (n ? `\n\n${n}` : '') + tail;

  if (enc(assemble(body)).length <= maxEncoded) return assemble(body);
  if (!body) return assemble('');

  // Longest prefix of the note (in code points) that fits, plus an ellipsis.
  const cs = chars(body);
  const cut = (k) => cs.slice(0, k).join('').trimEnd() + ELLIPSIS;
  let lo = 0;
  let hi = cs.length;
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2);
    if (enc(assemble(cut(mid))).length <= maxEncoded) lo = mid; else hi = mid - 1;
  }
  return assemble(lo > 0 ? cut(lo) : '');
}

export function buildWaMeUrl(text) {
  return WA_URL_PREFIX + enc(text);
}

export async function dataUrlToFile(dataUrl, name = 'plan-note.jpg') {
  if (typeof dataUrl !== 'string' || !dataUrl.startsWith('data:image/')) return null;
  const blob = await (await fetch(dataUrl)).blob();
  return new File([blob], name, { type: blob.type || 'image/jpeg' });
}

const isAbort = (e) => !!e && (e.name === 'AbortError' || e.code === 20);

// Result status:
//  shared    navigator.share resolved (withImage says whether the crop went too)
//  cancelled user closed the share sheet -- NOT an error
//  opened    wa.me opened in a new tab
//  blocked   no share API and the popup was blocked; caller shows `url`
// Injectable (nav, openWindow) so it is testable without a browser.
export async function shareViaWhatsApp({ text, file = null, nav, openWindow }) {
  const n = nav === undefined ? (typeof navigator !== 'undefined' ? navigator : null) : nav;
  const open = openWindow || ((u) => (typeof window !== 'undefined' ? window.open(u, '_blank', 'noopener,noreferrer') : null));
  const url = buildWaMeUrl(text);

  if (n && typeof n.share === 'function') {
    let withFiles = false;
    try {
      withFiles = !!file && typeof n.canShare === 'function' && !!n.canShare({ files: [file] });
    } catch (_) { withFiles = false; }
    if (withFiles) {
      try {
        await n.share({ text, files: [file] });
        return { status: 'shared', withImage: true, url };
      } catch (e) {
        if (isAbort(e)) return { status: 'cancelled', url };
        // fall through: retry text-only
      }
    }
    try {
      await n.share({ text });
      return { status: 'shared', withImage: false, url };
    } catch (e) {
      if (isAbort(e)) return { status: 'cancelled', url };
      // share exists but failed (e.g. lost user activation): fall to wa.me
    }
  }

  let w = null;
  try { w = open(url); } catch (_) { w = null; }
  return w ? { status: 'opened', url } : { status: 'blocked', url };
}
