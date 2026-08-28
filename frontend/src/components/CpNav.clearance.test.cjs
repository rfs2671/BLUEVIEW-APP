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

function decl(name) {
  const m = SRC.match(new RegExp(`^(?:export )?const ${name} =[\\s\\S]*?;$`, 'm'));
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
