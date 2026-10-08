#!/usr/bin/env node
/**
 * THE ACTION ROW ON A USER CARD, AT THE NARROWEST WIDTH THE OPERATOR USES.
 *
 * ── WHAT THIS MEASURES AND WHY A GREP CANNOT ────────────────────────────────
 *
 * TWO THINGS, AND THEY ARE BOTH ABOUT THE SAME ROW:
 *
 *   1. WHICH BUTTONS A ROLE GETS. Operator ruling: a superintendent's projects
 *      are his active registrations, so his card carries Registration, Edit and
 *      Delete and NO Assign — Assign would be a second writer of a set that now
 *      has an owner. CP and PM keep Assign and have no Registration, because
 *      they hold no DOB licence for it to write.
 *
 *   2. THAT NO LABEL WRAPS AT 443px. "Registration" is twelve characters where
 *      "Assign" was six, in a flex row that also holds Edit and a delete icon.
 *      Whether that fits is the product of the font, the icon, the gap, the
 *      padding and the card's own width — not a fact any source-text check can
 *      reach.
 *
 * ── "WRAPS" IS TWO FAILURES, AND ONLY ONE OF THEM IS WRAPPING ───────────────
 *
 * THE FIRST VERSION OF THIS CHECK COULD NOT FAIL, and narrowing the viewport to
 * 240px is what proved it: "Registration" in a 66px button reported clean. It
 * had not wrapped. GlassButton's content row centres a <Text> with no
 * flexShrink, so a label too long for its button does not take a second line —
 * IT SPILLS OUT THE SIDES, over the border and under its neighbour, at exactly
 * one line the whole time.
 *
 * So both are measured, and the OVERFLOW one is the one that fires here. The
 * wrap check stays because it is the failure a future `flexShrink: 1` or
 * `numberOfLines` would produce instead, and a check that only knows today's
 * layout is a check that goes quiet the day the layout changes.
 *
 * Ask of any instrument what reading would prove it broken. For this one:
 * run it at --width 240 and it must FAIL. It does.
 *
 * 443px IS THE OPERATOR'S WINDOW, not a guess: it is the width his browser
 * pane sits at, and it is the width the sheets gate uses. Narrow enough that a
 * three-button row is genuinely tight, wide enough that it is not the phone
 * breakpoint.
 *
 * ── WRAPPING IS MEASURED WITH A RANGE, NOT WITH A HEIGHT ────────────────────
 *
 * `getClientRects()` over a Range spanning the text node returns ONE RECT PER
 * LINE BOX. Two rects is two lines, at any font size, in any locale, without
 * this check carrying a copy of the line height it would otherwise have to
 * compare against — a number that goes stale the day theme.js changes and
 * takes the check silently with it.
 *
 *   node scripts/admin-users-card-actions.cjs --dist dist --port 5812
 *
 * Exit 1 on a wrapped label or a role holding the wrong buttons, so it gates
 * CI. It reuses the dist and the Chromium the mount-smoke job already
 * installed, like touch-targets.cjs beside it.
 */
const http = require('http');
const fs = require('fs');
const path = require('path');

const arg = (n, d) => {
  const i = process.argv.indexOf(`--${n}`);
  return i > -1 ? process.argv[i + 1] : d;
};
const DIST = path.resolve(arg('dist', 'dist'));
const PORT = Number(arg('port', 5812));
const WIDTH = Number(arg('width', 443));

// THE SCREEN'S OWN TAP FLOOR, READ FROM theme.js AND NOT COPIED HERE. 56 is
// `touchTarget.min` and theme.js says why in its own words — outdoors, gloved,
// one-handed. A literal in this file would be a second copy of the number and
// would go stale silently the day the token moves, which is the shape
// touch-targets.cjs beside this one warns about. A theme that cannot be read is
// a refusal, not a default: a fallback would let this check pass on a number
// nobody set.
const TOUCH_MIN = (() => {
  const src = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'styles', 'theme.js'), 'utf8');
  const m = src.match(/touchTarget\s*=\s*\{[^}]*?\bmin:\s*(\d+)/s);
  if (!m) throw new Error('no touchTarget.min found in src/styles/theme.js');
  return Number(m[1]);
})();

let chromium;
try {
  ({ chromium } = require(process.env.PW_CORE || 'playwright-core'));
} catch (e) {
  console.error('playwright-core is not resolvable; set PW_CORE.');
  process.exit(1);
}

const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.png': 'image/png', '.ico': 'image/x-icon', '.svg': 'image/svg+xml', '.ttf': 'font/ttf', '.woff': 'font/woff', '.woff2': 'font/woff2', '.map': 'application/json' };
const server = http.createServer((req, res) => {
  const p = decodeURIComponent(req.url.split('?')[0]);
  let fp = path.join(DIST, p);
  if (!fs.existsSync(fp) || fs.statSync(fp).isDirectory()) {
    const h = path.join(DIST, `${p}.html`);
    fp = fs.existsSync(h) ? h : path.join(DIST, 'index.html');
  }
  try {
    res.writeHead(200, { 'Content-Type': MIME[path.extname(fp)] || 'application/octet-stream' });
    res.end(fs.readFileSync(fp));
  } catch (e) { res.writeHead(404); res.end('nf'); }
});

const b64 = (o) => Buffer.from(JSON.stringify(o)).toString('base64url');
const JWT = `${b64({ alg: 'HS256', typ: 'JWT' })}.${b64({ exp: 4102444800, sub: 'a1' })}.x`;

// THE PRINCIPAL IS A COMPANY ADMIN, not the platform operator. That is the
// account the ruling is about and the one whose picker loses "Admin"; running
// this as the operator would exercise the branch the customer never sees.
const ADMIN = {
  id: 'a1', _id: 'a1', email: 'admin@test.local', name: 'An Admin',
  full_name: 'An Admin', role: 'admin', company_id: 'c1',
  company_name: 'Acme', account_status: 'approved',
  is_platform_operator: false,
};

// ONE ROW PER ROLE THE LIST CAN HOLD. The names are long-ish on purpose: a
// short name leaves the row slack that a real one does not.
const ROWS = [
  {
    id: 'su1', name: 'Michael Cespedes', email: 'michael@acme-construction.com',
    role: 'superintendent', company_id: 'c1', assigned_projects: ['p1'],
    dob_superintendent_number: '32299',
    licence: {
      state: 'unreadable', expires_on: '07/212029', days_remaining: null,
      number: '32299', registered: true,
    },
  },
  {
    id: 'cp1', name: 'A Competent Person', email: 'cp@acme-construction.com',
    role: 'cp', company_id: 'c1', assigned_projects: ['p1'],
  },
  {
    id: 'pm1', name: 'A Site Manager', email: 'pm@acme-construction.com',
    role: 'pm', company_id: 'c1', assigned_projects: [],
  },
];

const PROJECT = { id: 'p1', _id: 'p1', name: '588 Thomas', address: '1 Test St', company_id: 'c1', status: 'active' };

// WHAT THE PAGE IS ASKED, IN THE PAGE. Returns one entry per control on a user
// card's action row: its label, its box, and whether the label wrapped.
//
// ── THE ROWS ARE DERIVED, NOT LISTED ────────────────────────────────────────
//
// An action row is "the parent of a control labelled Edit". Every user card has
// exactly one Edit and nothing else on this screen does, so the set follows the
// cards rather than a hand-written list of selectors that goes stale the day
// the JSX is reordered. It also excludes the bottom nav and the header icons by
// construction, instead of by name.
//
// ── THE SELECTOR IS NOT `[role="button"]` ───────────────────────────────────
//
// React Native Web renders a Pressable as `<div tabindex="0">` with NO role
// attribute in this version. A check written against `[role="button"]` finds
// zero controls here and every assertion about "no label wraps" passes
// vacuously — which is exactly what this script did on its first run. Both
// selectors are accepted so a future RN Web that restores the role does not
// silently halve the population, and the count is asserted by the caller.
const READ_CARDS = () => {
  const wrapped = (el) => {
    const r = document.createRange();
    r.selectNodeContents(el);
    // One rect per line box. Rects of zero width are collapsed whitespace and
    // are not a line.
    const rects = Array.from(r.getClientRects()).filter((b) => b.width > 0.5);
    return rects.length > 1;
  };
  const controls = Array.from(
    document.querySelectorAll('[role="button"],[tabindex="0"]'),
  );
  const label = (el) => (el.innerText || el.getAttribute('aria-label') || '')
    .replace(/\s+/g, ' ').trim();

  const rows = new Set();
  for (const el of controls) {
    if (label(el) === 'Edit' && el.parentElement) rows.add(el.parentElement);
  }

  const out = [];
  let row = 0;
  for (const parent of rows) {
    row += 1;
    for (const el of controls) {
      if (el.parentElement !== parent) continue;
      const box = el.getBoundingClientRect();
      if (box.height === 0 || box.width === 0) continue;
      const text = label(el);
      // An icon-only control (the delete bin) has no label and nothing to wrap,
      // but it IS part of the row — counted, so "three controls" can be checked.
      const textEl = text
        ? (Array.from(el.querySelectorAll('div,span'))
          .find((n) => n.children.length === 0 && n.textContent.trim() === text) || el)
        : null;
      // THE LABEL'S OWN BOX AGAINST ITS CONTROL'S. A <Text> with no flexShrink
      // in a centred row does not wrap when it runs out of space — it spills
      // over the button's border in both directions. One pixel of tolerance,
      // because sub-pixel layout rounds either way and a half-pixel is not a
      // label hanging out of a button.
      const tbox = textEl ? textEl.getBoundingClientRect() : null;
      const overflows = !!tbox
        && (tbox.left < box.left - 1 || tbox.right > box.right + 1);
      out.push({
        row,
        label: text || '(icon)',
        wrapped: textEl ? wrapped(textEl) : false,
        overflows,
        overhang: tbox
          ? Math.round(Math.max(box.left - tbox.left, tbox.right - box.right))
          : 0,
        width: Math.round(box.width),
        height: Math.round(box.height),
      });
    }
  }
  return out;
};

/**
 * THE PROMOTION LINE, WHICH IS NOT IN THE ACTION ROW AND SO NOT IN READ_CARDS.
 *
 * `canBecomeSuperintendent` admits `cp` and nothing else, and the reason is the
 * confirmation copy: three of the consequences it states are false from `pm` —
 * a Site Manager's email is not already suppressed, and he holds neither the
 * WhatsApp binding nor the emergency check-in point, so two of the stated losses
 * are not losses. That scope was wrong in the first draft of the feature and
 * nothing in the suite could see it, because the only instrument that opens this
 * screen in a browser derives its population from "the parent of an Edit" and
 * this control is a SIBLING of that row.
 *
 * SO THE COUNT IS THE ASSERTION, AND THE LABELS ARE HOW IT IS CHECKED. One
 * control, on the CP's card, named after him. Offering it on the Site Manager's
 * card shows up here as two.
 *
 * AND ITS SIZE IS MEASURED LIKE EVERY OTHER TARGET ON THE SCREEN. A quiet text
 * control is still a control: the superintendent log shipped an 18-point
 * disclosure row above a 56-point checkbox and the small one was the way IN.
 * The floor is read from theme.js by the caller rather than written here twice.
 */
const READ_PROMOTIONS = () => {
  const controls = Array.from(
    document.querySelectorAll('[role="button"],[tabindex="0"]'),
  );
  const out = [];
  for (const el of controls) {
    const aria = (el.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim();
    if (!/^Make .+ a superintendent$/.test(aria)) continue;
    const box = el.getBoundingClientRect();
    // AGAINST THE CARD, NOT AGAINST ITSELF. This control has no border of its
    // own to spill over; what it can do is run past the edge of the GlassCard it
    // sits in, which is the same failure in a different frame. The card is the
    // nearest ancestor wider than the control.
    let card = el.parentElement;
    while (card && card.getBoundingClientRect().width <= box.width + 1) {
      card = card.parentElement;
    }
    const cbox = card ? card.getBoundingClientRect() : null;
    out.push({
      label: aria,
      width: Math.round(box.width),
      height: Math.round(box.height),
      overflows: !!cbox && (box.left < cbox.left - 1 || box.right > cbox.right + 1),
    });
  }
  return out;
};

(async () => {
  if (!fs.existsSync(path.join(DIST, 'index.html'))) {
    console.error(`no export at ${DIST} — run: npx expo export --platform web --output-dir dist`);
    process.exit(1);
  }
  console.log(`\nadmin/users action row at ${WIDTH}px\n`);

  await new Promise((r) => server.listen(PORT, r));
  const browser = await chromium.launch({ executablePath: process.env.CHROME || undefined });
  const ctx = await browser.newContext({ viewport: { width: WIDTH, height: 900 } });
  await ctx.route('**/api/**', (route) => {
    const u = route.request().url();
    const json = (b) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(b) });
    if (u.includes('/auth/me')) return json(ADMIN);
    if (u.includes('/admin/users')) return json(ROWS);
    if (u.includes('/projects')) return json([PROJECT]);
    if (u.includes('/version')) return json({ client_minimum_supported: null });
    return json([]);
  });
  // THE KEYS ARE THE APP'S OWN, NOT 'token'/'user'. `getToken` reads
  // `blueview_token`; seeding the wrong name lands on the login screen, which
  // has no action row and would have passed a check that only looked for
  // wrapped labels. That is why the assertions below start by demanding the
  // buttons EXIST.
  await ctx.addInitScript(([t, u]) => {
    localStorage.setItem('blueview_token', t);
    localStorage.setItem('blueview_user', u);
  }, [JWT, JSON.stringify(ADMIN)]);

  const page = await ctx.newPage();
  const consoleErrors = [];
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  await page.goto(`http://localhost:${PORT}/admin/users`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(4000);

  const controls = await page.evaluate(READ_CARDS);
  const promotions = await page.evaluate(READ_PROMOTIONS);
  await browser.close();
  server.close();

  let bad = 0;
  const say = (msg) => { bad += 1; console.log(`  FAIL  ${msg}`); };

  // ── THE INSTRUMENT PROVES IT LOOKED BEFORE IT REPORTS WHAT IT SAW ────────
  //
  // A screen that did not render has no wrapped labels either, and "no label
  // wraps" would be true of a blank page, of the login screen, and of the
  // "Admin Access Required" panel. Each of those is a way this check could
  // report clean while measuring nothing — the first run did exactly that,
  // twice, on a wrong storage key and a wrong selector. So the population is
  // asserted first: three cards, each with a row, and the right buttons on it.
  const rows = new Map();
  for (const c of controls) {
    rows.set(c.row, [...(rows.get(c.row) || []), c.label]);
  }
  if (rows.size !== ROWS.length) {
    say(`expected ${ROWS.length} user cards with an action row, found ${rows.size} `
      + '— the screen did not render the list');
  }

  const labels = controls.map((c) => c.label);
  const counts = (name) => labels.filter((l) => l === name).length;
  // ONE SUPERINTENDENT, TWO OTHERS. Registration appears once, Assign twice.
  if (counts('Registration') !== 1) {
    say(`expected 1 Registration button, found ${counts('Registration')}`);
  }
  if (counts('Assign') !== 2) {
    say(`expected 2 Assign buttons (the CP and the PM), found ${counts('Assign')}`);
  }
  // AND NEVER BOTH ON ONE CARD. That is the invariant losing its single writer:
  // Assign would set `assigned_projects` behind Registration's back.
  for (const [n, row] of rows) {
    if (row.includes('Assign') && row.includes('Registration')) {
      say(`card ${n} carries both Assign and Registration: ${row.join(', ')}`);
    }
    if (!row.includes('Edit')) say(`card ${n} has no Edit: ${row.join(', ')}`);
    if (!row.includes('(icon)')) say(`card ${n} has no delete control: ${row.join(', ')}`);
  }

  for (const c of controls) {
    if (c.wrapped) {
      say(`label wraps at ${WIDTH}px: "${c.label}" (${c.width}x${c.height})`);
    }
    if (c.overflows) {
      say(`label does not fit its button at ${WIDTH}px: "${c.label}" `
        + `spills ${c.overhang}px past a ${c.width}px control`);
    }
  }

  for (const c of controls) {
    const verdict = c.wrapped ? 'WRAP' : (c.overflows ? 'OVER' : '  ok');
    console.log(`  ${verdict}  card ${c.row}  `
      + `${String(c.width).padStart(4)}x${String(c.height).padStart(3)}  ${c.label}`);
  }
  // ── THE PROMOTION LINE ────────────────────────────────────────────────────
  //
  // ONE, ON THE CP'S CARD. `canBecomeSuperintendent` admits `cp` alone because
  // the confirmation states the consequences of promotion FROM cp — see
  // src/utils/roleVocabulary.js, which writes out which three of them are false
  // from pm. A second control here is that scope having widened without the copy
  // being re-measured, which is a confirmation that misleads an admin about a
  // change he can only partly undo.
  const expectPromote = `Make ${ROWS.find((r) => r.role === 'cp').name} a superintendent`;
  const promoteLabels = promotions.map((p) => p.label).sort();
  if (promoteLabels.length !== 1 || promoteLabels[0] !== expectPromote) {
    say(`expected exactly one promotion control, on the CP's card `
      + `("${expectPromote}"), found ${promoteLabels.length}: `
      + `${promoteLabels.join(' | ') || 'none'}`);
  }
  // THE FLOOR IS theme.js's OWN NUMBER, read rather than copied — a literal here
  // would go stale the day the token moves and take this check quietly with it.
  for (const p of promotions) {
    if (p.height < TOUCH_MIN) {
      say(`promotion control is ${p.height}px tall, under the screen's own `
        + `${TOUCH_MIN}px floor: "${p.label}"`);
    }
    if (p.overflows) {
      say(`promotion control runs past the edge of its card at ${WIDTH}px: `
        + `"${p.label}" (${p.width}px)`);
    }
    console.log(`  ${p.overflows || p.height < TOUCH_MIN ? 'OVER' : '  ok'}  promote `
      + `${String(p.width).padStart(4)}x${String(p.height).padStart(3)}  ${p.label}`);
  }

  if (consoleErrors.length) {
    for (const e of consoleErrors.slice(0, 5)) say(`console error: ${e.slice(0, 160)}`);
  }

  console.log(`\n${controls.length} control(s) on ${rows.size} card(s) measured, `
    + `${promotions.length} promotion control(s), ${bad} problem(s)`);
  if (bad) {
    console.error('\nA label that wraps or spills is a control that no longer fits '
      + 'the row it was drawn for, and a role holding the wrong buttons is the '
      + 'invariant "a superintendent\'s projects are his registrations" losing its '
      + 'single writer.');
    process.exit(1);
  }
  console.log('Every action label fits, and every role holds the buttons the ruling gives it.');
})().catch((e) => { console.error('FAILED:', e); process.exit(1); });
