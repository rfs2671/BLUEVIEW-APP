// Share a plan-sheet note as ONE composed image through the OS share sheet.
//
// No message text is prefilled anywhere, and nothing here talks to a messaging
// provider: the user picks WhatsApp (or anything else) in the share sheet the
// operating system draws. Where the browser cannot share files (desktop), the
// same image is downloaded instead.
//
// Everything that touches the platform is injected (createCanvas, createImage,
// nav, doc) so the composition and the share decision are unit-testable
// without a browser.

export const IMAGE_WIDTH = 1080;
export const MAX_SECTION_HEIGHT = 1080; // plan crop / photo are scaled to the width, then capped
export const CAPTION_PAD = 36;
export const CAPTION_FONT_PX = 34;
export const CAPTION_LINE_PX = 46;
export const CAPTION_MAX_CONTEXT_LINES = 8;
export const MARKER_RADIUS_FRACTION = 0.035; // of the plan section width
const ELLIPSIS = '…';

const clean = (v) => String(v == null ? '' : v).replace(/\r\n?/g, '\n').trim();
const oneLine = (v) => clean(v).replace(/\s+/g, ' ');

// "A-101.pdf" -> "A-101"; adds the page when the PDF has more than one.
export function sheetLabelFor(file, pageNumber) {
  const raw = (file && (file.name || file.filename || file.path)) || '';
  const base = oneLine(String(raw).split('/').pop().replace(/\.pdf$/i, '')).slice(0, 80);
  const page = Number(pageNumber);
  if (page > 1) return base ? `${base} (p. ${page})` : `p. ${page}`;
  return base;
}

export function formatShareDate(d) {
  const dt = d instanceof Date && !Number.isNaN(d.getTime()) ? d : new Date();
  const p = (n) => String(n).padStart(2, '0');
  return `${dt.getFullYear()}-${p(dt.getMonth() + 1)}-${p(dt.getDate())}`;
}

// The caption's lines, in order. A field that is empty contributes NO line, so
// an empty context (or a missing project name) never leaves a blank row.
export function captionFields({ context, projectName, sheetLabel, date }) {
  const meta = [];
  const project = oneLine(projectName);
  const sheet = oneLine(sheetLabel);
  if (project) meta.push(project);
  if (sheet) meta.push(`Sheet ${sheet}`);
  if (date) meta.push(String(date));
  return { context: clean(context), meta };
}

// Greedy word wrap using the canvas's own measureText. A word wider than the
// line is broken by characters. Never returns an empty string as a line.
export function wrapLines(measure, text, maxWidth) {
  const out = [];
  const paragraphs = clean(text).split('\n');
  for (const para of paragraphs) {
    const words = para.split(/\s+/).filter(Boolean);
    if (!words.length) continue; // blank paragraph: no blank row
    let line = '';
    const flush = () => { if (line) out.push(line); line = ''; };
    for (const w of words) {
      const trial = line ? `${line} ${w}` : w;
      if (measure(trial) <= maxWidth) { line = trial; continue; }
      flush();
      if (measure(w) <= maxWidth) { line = w; continue; }
      let chunk = '';
      for (const ch of Array.from(w)) {
        if (measure(chunk + ch) > maxWidth && chunk) { out.push(chunk); chunk = ch; } else chunk += ch;
      }
      line = chunk;
    }
    flush();
  }
  return out;
}

function fitSection(img, width, maxHeight) {
  const iw = img.naturalWidth || img.width || 0;
  const ih = img.naturalHeight || img.height || 0;
  if (!iw || !ih) return null;
  const h = Math.min(Math.round((ih * width) / iw), maxHeight);
  const scale = Math.min(width / iw, h / ih);
  const dw = Math.round(iw * scale);
  const dh = Math.round(ih * scale);
  return { h, dw, dh, dx: Math.round((width - dw) / 2), dy: Math.round((h - dh) / 2) };
}

// planImage: the plan crop around the marker (anything drawImage accepts).
// marker:    {x, y} as fractions (0..1) of planImage. Omit when the crop
//            already carries the marker (the server-made crop does).
// photo:     optional live-site photo (anything drawImage accepts).
export function composeShareImage({
  planImage = null, marker = null, photo = null,
  context = '', projectName = '', sheetLabel = '', date = '',
  createCanvas, width = IMAGE_WIDTH,
}) {
  if (typeof createCanvas !== 'function') throw new Error('createCanvas is required');
  const fields = captionFields({ context, projectName, sheetLabel, date });

  // Measure with a scratch context so the real canvas is sized once.
  const scratch = createCanvas(width, 10).getContext('2d');
  scratch.font = `${CAPTION_FONT_PX}px sans-serif`;
  const measure = (s) => scratch.measureText(s).width;
  const textWidth = width - CAPTION_PAD * 2;
  let ctxLines = wrapLines(measure, fields.context, textWidth);
  if (ctxLines.length > CAPTION_MAX_CONTEXT_LINES) {
    ctxLines = ctxLines.slice(0, CAPTION_MAX_CONTEXT_LINES);
    ctxLines[CAPTION_MAX_CONTEXT_LINES - 1] = ctxLines[CAPTION_MAX_CONTEXT_LINES - 1].replace(/\s*\S?$/, '') + ELLIPSIS;
  }
  const metaLine = fields.meta.join('  |  ');
  const metaLines = metaLine ? wrapLines(measure, metaLine, textWidth) : [];
  const captionLines = [...ctxLines, ...metaLines];

  const plan = planImage ? fitSection(planImage, width, MAX_SECTION_HEIGHT) : null;
  const pic = photo ? fitSection(photo, width, MAX_SECTION_HEIGHT) : null;
  const captionH = captionLines.length ? CAPTION_PAD * 2 + captionLines.length * CAPTION_LINE_PX : 0;
  const height = (plan ? plan.h : 0) + (pic ? pic.h : 0) + captionH;
  if (!height) throw new Error('nothing to compose');

  const canvas = createCanvas(width, height);
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, width, height);

  let y = 0;
  if (plan) {
    ctx.drawImage(planImage, plan.dx, y + plan.dy, plan.dw, plan.dh);
    if (marker && Number.isFinite(marker.x) && Number.isFinite(marker.y)) {
      const mx = plan.dx + Math.max(0, Math.min(1, marker.x)) * plan.dw;
      const my = y + plan.dy + Math.max(0, Math.min(1, marker.y)) * plan.dh;
      const r = Math.round(width * MARKER_RADIUS_FRACTION);
      ctx.lineWidth = 6;
      ctx.strokeStyle = '#e11d48';
      ctx.beginPath();
      ctx.arc(mx, my, r, 0, Math.PI * 2);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(mx - r * 1.5, my); ctx.lineTo(mx - r * 0.5, my);
      ctx.moveTo(mx + r * 0.5, my); ctx.lineTo(mx + r * 1.5, my);
      ctx.moveTo(mx, my - r * 1.5); ctx.lineTo(mx, my - r * 0.5);
      ctx.moveTo(mx, my + r * 0.5); ctx.lineTo(mx, my + r * 1.5);
      ctx.stroke();
    }
    y += plan.h;
  }
  if (pic) {
    ctx.fillStyle = '#0f172a';
    ctx.fillRect(0, y, width, pic.h);
    ctx.drawImage(photo, pic.dx, y + pic.dy, pic.dw, pic.dh);
    y += pic.h;
  }
  if (captionLines.length) {
    ctx.fillStyle = '#0f172a';
    ctx.fillRect(0, y, width, captionH);
    ctx.fillStyle = '#ffffff';
    ctx.font = `${CAPTION_FONT_PX}px sans-serif`;
    ctx.textBaseline = 'top';
    captionLines.forEach((ln, i) => {
      if (i === ctxLines.length) ctx.fillStyle = '#E3C27A'; // meta lines in the accent colour
      ctx.fillText(ln, CAPTION_PAD, y + CAPTION_PAD + i * CAPTION_LINE_PX + 4);
    });
  }
  return { canvas, width, height, captionLines, hasPlan: !!plan, hasPhoto: !!pic };
}

export function canvasToBlob(canvas, type = 'image/jpeg', quality = 0.9) {
  return new Promise((resolve, reject) => {
    try {
      canvas.toBlob((b) => (b && b.size > 0 ? resolve(b) : reject(new Error('empty image'))), type, quality);
    } catch (e) { reject(e); }
  });
}

export function loadImage(src, createImage) {
  const make = createImage || (() => new Image());
  return new Promise((resolve, reject) => {
    const img = make();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error('image failed to load'));
    img.src = src;
  });
}

export function shareFileName(sheetLabel, date) {
  const slug = oneLine(sheetLabel).replace(/[^A-Za-z0-9._-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40);
  return `plan-note${slug ? `-${slug}` : ''}${date ? `-${date}` : ''}.jpg`;
}

export function downloadBlob(blob, filename, doc, urlApi) {
  const d = doc || (typeof document !== 'undefined' ? document : null);
  const u = urlApi || (typeof URL !== 'undefined' ? URL : null);
  if (!d || !u) throw new Error('no document to download into');
  const href = u.createObjectURL(blob);
  const a = d.createElement('a');
  a.href = href;
  a.download = filename;
  a.rel = 'noopener noreferrer';
  a.style.display = 'none';
  d.body.appendChild(a);
  a.click();
  d.body.removeChild(a);
  setTimeout(() => u.revokeObjectURL(href), 10000);
}

const isAbort = (e) => !!e && (e.name === 'AbortError' || e.code === 20);

// Result status:
//  shared     the OS share sheet took the file
//  cancelled  the user closed the share sheet -- NOT an error, nothing to show
//  downloaded no file sharing here (desktop) or sharing failed: the image was saved instead
// Only the file is passed to navigator.share: no text, no title, no url, so
// nothing is prefilled in the receiving app.
export async function shareComposedImage({ blob, filename, nav, download }) {
  const n = nav === undefined ? (typeof navigator !== 'undefined' ? navigator : null) : nav;
  const save = download || ((b, f) => downloadBlob(b, f));
  const file = new File([blob], filename, { type: blob.type || 'image/jpeg' });

  let canShareFiles = false;
  try {
    canShareFiles = !!n && typeof n.share === 'function' && typeof n.canShare === 'function' && !!n.canShare({ files: [file] });
  } catch (_) { canShareFiles = false; }

  if (canShareFiles) {
    try {
      await n.share({ files: [file] });
      return { status: 'shared' };
    } catch (e) {
      if (isAbort(e)) return { status: 'cancelled' };
      // any other failure: do not lose the work, save the image
    }
  }
  save(blob, filename);
  return { status: 'downloaded' };
}
