/**
 * GlassCard draws a card with TWO views since the aura: an outer one that places the card (and casts the iOS shadow,
 * which a clip on the same view would remove) and an inner one that keeps the clip, fill and padding. Every caller's
 * `style` is split between them by splitCardStyle. A key on the wrong side moves or resizes a card somewhere in the app,
 * so this pins the split itself: which keys place, which keys draw, and how the inner view keeps the old clip.
 *
 * Dependency-free: the function is lifted out of the source and run against a StyleSheet.flatten stand-in.
 */
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, 'GlassCard.js'), 'utf8').replace(/\r\n/g, '\n');
let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

const start = src.indexOf('const OUTER_KEYS');
const end = src.indexOf('return { outer, inner };', start);
ok(start > -1 && end > -1, 'splitCardStyle and its key lists are in GlassCard.js');
// The function's own closing brace is the first one at the start of a line after its return.
const fnClose = src.indexOf('\n}', end) + 1;
const body = src.slice(start, fnClose + 1).replace('export function', 'function');
const StyleSheet = {
  flatten: (s) => (Array.isArray(s) ? Object.assign({}, ...s.filter(Boolean).map((x) => StyleSheet.flatten(x))) : s),
};
// eslint-disable-next-line no-new-func
const splitCardStyle = new Function('StyleSheet', `${body}\nreturn splitCardStyle;`)(StyleSheet);

console.log('\n── Placement goes outside, drawing stays inside ──');
{
  const { outer, inner } = splitCardStyle({
    marginBottom: 12, width: '100%', alignSelf: 'center', padding: 16, backgroundColor: '#fff', alignItems: 'center', borderRadius: 8,
  });
  ok(outer.marginBottom === 12 && outer.width === '100%' && outer.alignSelf === 'center', 'margin, width and alignSelf place the card (outer)');
  ok(inner.padding === 16 && inner.backgroundColor === '#fff' && inner.alignItems === 'center' && inner.borderRadius === 8,
    'padding, fill, alignment and a radius override stay on the clipping view (inner)');
  ok(!('marginBottom' in inner) && !('padding' in outer), 'no key lands on both sides by accident');
  ok(!('flexGrow' in inner), 'an unsized card does not make its inner view grow');
}

console.log('\n── The clip still falls where it did ──');
{
  const { outer, inner } = splitCardStyle({ maxHeight: 300 });
  ok(outer.maxHeight === 300 && inner.maxHeight === 300, 'a numeric maxHeight is copied, so content is still clipped at 300');
}
{
  const { outer, inner } = splitCardStyle({ height: 120 });
  ok(outer.height === 120 && inner.height === 120, 'a numeric height is copied');
}
{
  const { outer, inner } = splitCardStyle({ maxHeight: '80%' });
  ok(outer.maxHeight === '80%' && inner.maxHeight === undefined, 'a percentage is NOT copied (it would be a percentage of the outer view)');
  ok(inner.flexGrow === 1 && inner.flexShrink === 1, 'instead the inner view grows and shrinks to fill the outer one');
}
{
  const { outer, inner } = splitCardStyle({ flex: 1 });
  ok(outer.flex === 1 && inner.flexGrow === 1 && inner.flexShrink === 1, 'a flexed card fills with its inner view');
}

console.log('\n── Arrays and empties ──');
{
  const { outer, inner } = splitCardStyle([{ margin: 4 }, null, false, { padding: 2 }]);
  ok(outer.margin === 4 && inner.padding === 2, 'an array style with null/false entries splits like a flat one');
}
{
  const { outer, inner } = splitCardStyle(undefined);
  ok(Object.keys(outer).length === 0 && Object.keys(inner).length === 0, 'no style gives two empty halves');
}
{
  const { outer } = splitCardStyle({ transform: [{ scale: 1.01 }], opacity: 0.5 });
  ok(Array.isArray(outer.transform) && outer.opacity === 0.5, 'transform and opacity move the whole card, shadow included (outer)');
}

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
