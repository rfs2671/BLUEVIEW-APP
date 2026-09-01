/**
 * CP_NAV_CLEARANCE — the derivation, and the prop that keeps it honest.
 *
 * THE BUG THIS REPLACED did not look like a bug. Three CP screens cleared the
 * floating nav with a hardcoded paddingBottom — 120 on /logbooks and
 * /documents, 140 on /settings — and none of the three was a measurement
 * against the nav. 120 is the app's house-wide bottom scroll padding, used on
 * ~34 screens most of which carry no nav at all; /settings was 110 until an
 * unrelated react-native-web scroll fix bumped it to 140. The numbers happened
 * to be roughly right on gesture navigation and were WRONG on 3-button, where
 * the safe-area inset is ~48 rather than ~24 and the pill covered the last row
 * of every list. A screenshot looked fine, because the pill is ~90% opaque and
 * a covered row is still faintly visible — it is just not tappable.
 *
 * So the clearance is now DERIVED from the nav's own style tokens, and the
 * inset is added by the screen at render because this module cannot see it.
 *
 * Same harness as the other .test.cjs files here: this repo has no JS test
 * runner and CpNav.js cannot be imported under bare node (react, react-native,
 * expo-blur at module top), so the REAL source is read and the shipped
 * declarations are evaluated. Nothing below is a hand-copy of a value.
 *
 * Run:  node src/components/CpNav.clearance.test.cjs
 */

const fs = require('fs');
const path = require('path');

const SRC = fs.readFileSync(path.join(__dirname, 'CpNav.js'), 'utf8');
const THEME = fs.readFileSync(path.join(__dirname, '..', 'styles', 'theme.js'), 'utf8');

// `spacing` verbatim from theme.js, so a change there flows through here.
const spacingSrc = THEME.match(/export const spacing = \{[\s\S]*?\};/);
if (!spacingSrc) throw new Error('spacing not found in theme.js');

/**
 * Comment-free source, for the declaration lifts only.
 *
 * `decl` matches up to the first line ENDING IN `;`, which is a statement
 * boundary in code and nothing at all in prose. CP_NAV_ITEMS carries the note
 *
 *     // "Check-In", not "Check-In QR". The QR is how it happens to work today;
 *
 * and the lift stopped there, handing `new Function` half an array literal.
 * It failed loudly here, which is the good case — but the same shape silently
 * truncates any declaration whose comments happen to end a line with `;`.
 *
 * The raw SRC is still what the assertions below read: several of them check
 * that a REASON is written down, and those need the prose.
 */
const CODE = SRC
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/(?<!:)\/\/[^\n]*/g, '');

function decl(name) {
  const m = CODE.match(new RegExp(`^(?:export )?const ${name} =[\\s\\S]*?;$`, 'm'));
  if (!m) throw new Error(`${name} declaration not found in CpNav.js`);
  return m[0].replace(/^export /, '');
}

const { spacing, NAV_ICON_SIZE, CP_NAV_BOTTOM_OFFSET, CP_NAV_PILL_HEIGHT, CP_NAV_CLEARANCE } =
  // eslint-disable-next-line no-new-func
  new Function(`
    ${spacingSrc[0].replace('export const', 'const')}
    ${decl('NAV_ICON_SIZE')}
    ${decl('CP_NAV_BOTTOM_OFFSET')}
    ${decl('CP_NAV_PILL_HEIGHT')}
    ${decl('CP_NAV_BREATHING_ROOM')}
    ${decl('CP_NAV_CLEARANCE')}
    return { spacing, NAV_ICON_SIZE, CP_NAV_BOTTOM_OFFSET, CP_NAV_PILL_HEIGHT, CP_NAV_CLEARANCE };
  `)();

let passed = 0, failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

// ── The derivation matches the device ────────────────────────────────────────
// 58 was measured on the rendered component at 375pt AND 320pt, three items.
// If a spacing token moves, this fails — and it SHOULD: the pill really did
// change size and someone has to re-measure rather than trust the arithmetic.
ok(CP_NAV_PILL_HEIGHT === 58,
   `derived pill height matches the measured 58 (got ${CP_NAV_PILL_HEIGHT})`);
ok(CP_NAV_CLEARANCE === CP_NAV_BOTTOM_OFFSET + CP_NAV_PILL_HEIGHT + spacing.lg,
   'clearance = offset + pill + breathing room');
ok(CP_NAV_CLEARANCE === 106, `clearance is 106 (got ${CP_NAV_CLEARANCE})`);

// ── It is DERIVED, not written down ─────────────────────────────────────────
ok(/spacing\.sm \* 2 \+ \(spacing\.sm \+ 4\) \* 2 \+ NAV_ICON_SIZE/.test(SRC),
   'the pill height is composed from the same tokens the styles use');
ok(!/CP_NAV_PILL_HEIGHT = \d+/.test(SRC),
   'the pill height is never a bare literal');

// ── The component renders what the constants claim ──────────────────────────
ok(SRC.includes('<Icon size={NAV_ICON_SIZE}'),
   'the icon renders at the size the derivation assumes');
ok(SRC.includes('bottom: insets.bottom + CP_NAV_BOTTOM_OFFSET'),
   'the pill floats at the offset the clearance assumes');
ok(SRC.includes('paddingVertical: spacing.sm, paddingHorizontal: spacing.sm'),
   "blurContent's padding is the term the derivation uses");
ok(SRC.includes('paddingVertical: spacing.sm + 4'),
   "navItem's padding is the term the derivation uses");

// ── numberOfLines is what keeps the height true ─────────────────────────────
// Without it a squeezed label wraps, the item is two lines tall, the pill
// grows and this constant silently understates the clearance — on exactly the
// narrow phones where it is already tightest. Measured at 320pt, three items:
// with the prop 58, without it 70.
ok(SRC.includes('numberOfLines={1}'),
   'the nav label is single-line, so the derived height stays true');
ok(/DECOUPLED FROM ITEM COUNT ON PURPOSE/.test(SRC),
   'the reason is recorded, not just the prop');
ok(/pill 70/.test(SRC),
   'the measurement is recorded, so the next reader need not re-derive it');

// ── THE NAV STAYS AT THREE, AND THAT IS THE MEASUREMENT HOLDING ─────────────
//
// The superintendent log was briefly a FOURTH item. It is now a SUBSTITUTION:
// a principal who is the registered CS sees it in place of Check-In, and
// everyone else sees the nav unchanged.
//
// WHY THAT MATTERS HERE. Four items was structurally safe — CP_NAV_PILL_HEIGHT
// carries no item-count term, so it provably could not move — but the 58 above
// was measured at THREE, and at four every label drops from ~1/3 to ~1/4 of
// the pill. "Dashboard" had ONE POINT of headroom at three. numberOfLines
// turns that into an ellipsis rather than a wrap, which protects this constant
// and not the reading. Three items keeps the measurement above a measurement
// rather than an argument.
{
  const items = SRC.match(/^\s*\{ path: /gm) || [];
  ok(items.length === 3,
     `the nav ships three items (got ${items.length}) — the superintendent log `
     + 'REPLACES one, it does not append');

  // ── RUN IT, DO NOT READ IT ─────────────────────────────────────────────
  // The claim "the nav stays at three" is the one the clearance above rests
  // on, so it is EXECUTED rather than pattern-matched. A regex asserting the
  // shape of the map passes any refactor that keeps the shape and changes the
  // result, and "the branch exists" is exactly what was true of the required-
  // logbooks wiring the whole time it did nothing.
  //
  // cpNavItems touches no react-native import, so it lifts cleanly; the icon
  // identifiers are stubbed because only the PATHS are under test here.
  const { cpNavItems, CHECKIN_QR_ACTION } =
    // eslint-disable-next-line no-new-func
    new Function(`
      const LayoutDashboard = 'i', QrCode = 'i', Settings = 'i', HardHat = 'i';
      ${decl('CHECKIN_QR_ACTION')}
      ${decl('CP_NAV_ITEMS')}
      ${decl('SUPERINTENDENT_ITEM')}
      ${CODE.match(/export function cpNavItems[\s\S]*?\n\}/)[0].replace('export ', '')}
      return { cpNavItems, CHECKIN_QR_ACTION };
    `)();

  const plain = cpNavItems(undefined);
  const swapped = cpNavItems(['p1']);

  ok(plain.length === 3 && swapped.length === 3,
     `THREE EITHER WAY (${plain.length} / ${swapped.length}) — the capability `
     + 'changes WHICH items, never HOW MANY, which is what keeps the measured '
     + 'pill height above a measurement');
  ok(plain.map((i) => i.path).includes(CHECKIN_QR_ACTION),
     'a principal without the capability keeps Check-In');
  ok(!swapped.map((i) => i.path).includes(CHECKIN_QR_ACTION),
     'and a superintendent does NOT — it is replaced, not joined');
  ok(swapped.map((i) => i.path).includes('/logbooks/site_superintendent_log'),
     'by the superintendent log');
  ok(plain[0].path === swapped[0].path
     && plain[2].path === swapped[2].path,
  'Dashboard and Settings do not move — only the middle slot changes, so '
  + 'muscle memory for the other two survives');

  for (const empty of [undefined, null, [], 'superintendent', 0, {}]) {
    ok(cpNavItems(empty).map((i) => i.path).includes(CHECKIN_QR_ACTION),
      `${JSON.stringify(empty)} is NOT a capability — an absent or malformed `
      + 'field must never read as a yes');
  }

  const pill = decl('CP_NAV_PILL_HEIGHT');
  ok(!/CP_NAV_ITEMS|\.length|label/.test(pill),
     'the pill height still names no item count, no list and no label');
  ok(CP_NAV_PILL_HEIGHT === 58 && CP_NAV_CLEARANCE === 106,
     'pill 58, clearance 106 — the measured values, at the measured item count');

  ok(/navItem: \{[\s\S]*?flex: 1/.test(SRC),
     'items still share the width equally');
  ok(SRC.includes('numberOfLines={1}'),
     'and the label is still single-line');

  ok(/path: '\/logbooks\/site_superintendent_log'/.test(SRC),
     'the superintendent item points at the LOG TYPE path — the dashboard '
     + 'routes by log_type and the two must not diverge');
  ok(/A SUBSTITUTION, NOT A FOURTH ITEM/.test(SRC),
     'and the reason the nav stayed at three is recorded, so the next person '
     + 'to want a slot reads why appending was rejected');
}

// ── THE GATE IS THE CAPABILITY, NOT THE ROLE ────────────────────────────────
//
// THE CASE THAT DECIDES IT: the superintendent on 588 Thomas holds a `cp`
// account. A role test would hide his own statutory log from him and offer it
// to every CP who is not a superintendent — failing in both directions at
// once, and failing SILENTLY, because a missing nav item looks like a nav
// without that feature.
{
  ok(/superintendent_projects/.test(SRC),
     'the gate reads the server-computed capability');
  ok(!/role\s*===\s*'superintendent'|role\s*===\s*"superintendent"/.test(SRC),
     'and NEVER the role — the one man who needs this holds a cp account');
  ok(/Array\.isArray\(superintendentProjects\)\s*\n?\s*&& superintendentProjects\.length > 0/.test(SRC),
     'a non-array or empty list is NOT capable — an absent field must not '
     + 'read as a yes');
  ok(/length === 1/.test(SRC) && /'\/logbooks'/.test(SRC),
     'exactly one project goes straight in; more than one goes to the picker '
     + 'rather than the nav guessing which site he is standing on');
}

// ── The screens consume it ──────────────────────────────────────────────────
// The inset is the term the old hardcoded numbers were missing entirely, and
// it is the one that differs between gesture and 3-button navigation.
const SCREENS = [
  ['app/logbooks/index.jsx', '../../app/logbooks/index.jsx'],
  ['app/documents.jsx',      '../../app/documents.jsx'],
  ['app/settings.jsx',       '../../app/settings.jsx'],
];
for (const [label, rel] of SCREENS) {
  const src = fs.readFileSync(path.join(__dirname, rel), 'utf8');
  ok(src.includes('insets.bottom + CP_NAV_CLEARANCE'),
     `${label} clears the nav from the token plus the inset`);
  ok(!/paddingBottom: (120|140)\b/.test(src),
     `${label} no longer hardcodes a clearance`);
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
