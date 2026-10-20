/**
 * CP_NAV_CLEARANCE — the derivation, and the prop that keeps it honest.
 *
 * THE NAV IS NOW A SOLID, FULL-WIDTH BAR flush to the bottom edge (it was a
 * floating pill). Its height without the safe-area inset is
 * CP_NAV_PILL_HEIGHT (name kept: three screens and another test import or
 * read it), and the screens still owe `insets.bottom + CP_NAV_CLEARANCE`.
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

// The shipped StyleSheet, evaluated against the shipped tokens, so the bar
// height can be MEASURED from what the component renders rather than read back
// from the constants that are supposed to describe it.
const stylesSrc = CODE.match(/^const styles = StyleSheet\.create\(\{[\s\S]*?^\}\);$/m);
if (!stylesSrc) throw new Error('styles not found in CpNav.js');

const {
  spacing, NAV_ICON_SIZE, NAV_ITEM_HEIGHT, CP_NAV_BOTTOM_OFFSET, CP_NAV_PILL_HEIGHT,
  CP_NAV_BREATHING_ROOM, CP_NAV_CLEARANCE, styles,
} =
  // eslint-disable-next-line no-new-func
  new Function(`
    ${spacingSrc[0].replace('export const', 'const')}
    ${decl('NAV_ICON_SIZE')}
    ${decl('NAV_ITEM_RULE')}
    ${decl('NAV_ITEM_PAD_TOP')}
    ${decl('NAV_ITEM_GAP')}
    ${decl('NAV_LABEL_LINE_HEIGHT')}
    ${decl('NAV_ITEM_PAD_BOTTOM')}
    ${decl('NAV_ITEM_HEIGHT')}
    ${decl('CP_NAV_BOTTOM_OFFSET')}
    ${decl('CP_NAV_PILL_HEIGHT')}
    ${decl('CP_NAV_BREATHING_ROOM')}
    ${decl('CP_NAV_CLEARANCE')}
    const StyleSheet = { create: (o) => o };
    ${stylesSrc[0]}
    return { spacing, NAV_ICON_SIZE, NAV_ITEM_HEIGHT, CP_NAV_BOTTOM_OFFSET, CP_NAV_PILL_HEIGHT,
             CP_NAV_BREATHING_ROOM, CP_NAV_CLEARANCE, styles };
  `)();

let passed = 0, failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

// ── The derivation matches what the styles render ───────────────────────────
// The bar's height WITHOUT the inset, MEASURED from the shipped stylesheet:
// the container's top and bottom padding + the item's rule, top padding, icon,
// gap, one label line and bottom padding. If a style token moves, this and the
// derived constant disagree and the test fails — the bar really did change
// size and someone has to look, rather than trust the arithmetic.
const c = styles.container, it = styles.navItem, lbl = styles.navLabel;
const MEASURED_BAR_HEIGHT =
  c.paddingTop + c.paddingBottom
  + it.borderTopWidth + it.paddingTop + NAV_ICON_SIZE + it.gap + lbl.lineHeight
  + it.paddingBottom;
ok(MEASURED_BAR_HEIGHT === 65,
   `the bar measures 65 from its own styles (got ${MEASURED_BAR_HEIGHT})`);
ok(CP_NAV_PILL_HEIGHT === MEASURED_BAR_HEIGHT,
   `derived bar height equals the measured one (${CP_NAV_PILL_HEIGHT} vs ${MEASURED_BAR_HEIGHT})`);
ok(NAV_ITEM_HEIGHT === 49, `one item is 49 tall (got ${NAV_ITEM_HEIGHT})`);
ok(CP_NAV_CLEARANCE === CP_NAV_PILL_HEIGHT + spacing.lg && CP_NAV_BREATHING_ROOM === spacing.lg,
   'clearance = bar height + breathing room (the inset is added by the screen)');
ok(CP_NAV_CLEARANCE >= MEASURED_BAR_HEIGHT + spacing.md,
   `clearance clears the measured bar with room to spare (${CP_NAV_CLEARANCE} >= ${MEASURED_BAR_HEIGHT} + ${spacing.md})`);
ok(CP_NAV_CLEARANCE === 89, `clearance is 89 (got ${CP_NAV_CLEARANCE})`);

// The bar's bottom padding constant is the SAME 8 as its top padding, which is
// what lets the height formula count spacing.sm twice. If one drifts, the
// formula is wrong without any shape check noticing.
ok(CP_NAV_BOTTOM_OFFSET === spacing.sm && c.paddingTop === spacing.sm,
   'bottom padding constant == top padding == spacing.sm');
ok(c.bottom === 0 && c.left === 0 && c.right === 0 && c.position === 'absolute',
   'the bar is absolute, flush to the bottom edge and full width');
ok(!('borderRadius' in c) && !/BlurView/.test(CODE),
   'a flat strip: no rounded container, no blur layer');

// ── It is DERIVED, not written down ─────────────────────────────────────────
ok(/spacing\.sm \* 2 \+ NAV_ITEM_HEIGHT/.test(SRC),
   'the bar height is composed from the item height and the padding token');
ok(/NAV_ITEM_RULE \+ NAV_ITEM_PAD_TOP \+ NAV_ICON_SIZE \+ NAV_ITEM_GAP\s*\+ NAV_LABEL_LINE_HEIGHT \+ NAV_ITEM_PAD_BOTTOM/.test(SRC),
   'the item height is composed from the same tokens the styles use');
ok(!/CP_NAV_PILL_HEIGHT = \d+/.test(SRC) && !/CP_NAV_CLEARANCE = \d+/.test(SRC),
   'neither the bar height nor the clearance is ever a bare literal');
ok(/CP_NAV_CLEARANCE =\s*CP_NAV_PILL_HEIGHT \+ CP_NAV_BREATHING_ROOM/.test(SRC),
   'the clearance is derived from the bar height, not typed beside it');

// ── The component renders what the constants claim ──────────────────────────
ok(SRC.includes('<Icon size={NAV_ICON_SIZE}'),
   'the icon renders at the size the derivation assumes');
ok(SRC.includes('paddingBottom: insets.bottom + CP_NAV_BOTTOM_OFFSET'),
   'the bar pads its bottom by the inset plus the offset the clearance assumes');
ok(/paddingBottom: CP_NAV_BOTTOM_OFFSET/.test(CODE) && !/\binsets\b/.test(stylesSrc[0]),
   'and the stylesheet carries only the constant — the inset is added at render');
ok(it.borderTopWidth === 3 && it.opacity === 0.72 && lbl.fontSize === 11,
   'item: 3pt top rule, 72% inactive opacity, 11pt label');

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

// ── THE NAV IS THREE ITEMS, WHICH IS WHAT 58 WAS MEASURED AT ────────────────
//
// A superintendent slot was added here and removed. It substituted for Check-In
// rather than appending, so the count never moved and neither did the pill --
// but the count is asserted anyway, because the 58 above is a MEASUREMENT taken
// at three items and it stops being one the moment a fourth appears.
{
  const items = SRC.match(/^\s*\{ path: /gm) || [];
  ok(items.length === 3,
     `the nav ships three items (got ${items.length}) — the label-wrap `
     + 'measurements were taken at three, and a fourth makes the one-line '
     + 'assumption an argument rather than a measurement');

  const pill = decl('CP_NAV_PILL_HEIGHT');
  ok(!/CP_NAV_ITEMS|\.length|label/.test(pill),
     'the pill height names no item count, no list and no label');
  ok(CP_NAV_PILL_HEIGHT === 65 && CP_NAV_CLEARANCE === 89,
     'bar 65, clearance 89 — the derived values at three items');

  ok(/path: CHECKIN_QR_ACTION/.test(SRC),
     'Check-In holds the middle slot: it is reached at a gate with a worker '
     + 'in front of him, which a once-a-day log read from a list is not');
  // CODE, not SRC. The comment above the item list explains why the
  // superintendent slot was removed and names the screen it went back to, so a
  // raw search matches the EXPLANATION and fails on a file that is correct.
  ok(!/site_superintendent/.test(CODE),
     'and the superintendent log is NOT a nav item — it lives in the logbooks '
     + 'list, where a man looks for a log');
  ok(/WHY THERE IS NO SUPERINTENDENT SLOT/.test(SRC),
     'with the reason recorded, so the next person to want a slot reads why '
     + 'this one was removed rather than proposing it again');
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
