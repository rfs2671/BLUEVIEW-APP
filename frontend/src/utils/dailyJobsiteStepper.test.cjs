/**
 * The Daily Jobsite stepper's UI rules, asserted against the real screen source.
 *
 * These are the rules that exist because of WHO uses this screen: a Competent
 * Person who is older and not technical, on his own phone, outdoors, gloved,
 * one-handed. Each one below fails if the rule is broken, not merely if a
 * keyword disappears.
 *
 * The decision logic is tested separately, by EXECUTION, in
 * dailyJobsiteModel.test.cjs. This file covers what only the source can show:
 * layout, gating, tokens, and the absence of things that must stay absent.
 *
 * Run:  node src/utils/dailyJobsiteStepper.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
const SCREEN = path.join(FRONTEND, 'app', 'logbooks', 'daily_jobsite.jsx');
const src = fs.readFileSync(SCREEN, 'utf8');

// THE SCREEN IS NOW TWO FILES. Its chrome — header, pips, footer, lock bar —
// and the 51 shared style keys were extracted to src/components/logbookStepper
// so that ten forms cannot each drift. The rules below are unchanged; they are
// simply read from wherever the code they describe now lives, because this
// suite asserts SOURCE TEXT and the text moved. Nothing about what the CP sees
// changed, which is what the mount smoke and the executable model tests check.
const STEPPER_DIR = path.join(FRONTEND, 'src', 'components', 'logbookStepper');
const chromeRaw = fs.readFileSync(path.join(STEPPER_DIR, 'LogbookStepper.jsx'), 'utf8');
const primitivesRaw = fs.readFileSync(path.join(STEPPER_DIR, 'primitives.jsx'), 'utf8');
const sharedStylesRaw = fs.readFileSync(path.join(STEPPER_DIR, 'styles.js'), 'utf8');
const model = fs.readFileSync(path.join(__dirname, 'dailyJobsiteModel.js'), 'utf8');
const theme = fs.readFileSync(path.join(FRONTEND, 'src', 'styles', 'theme.js'), 'utf8');

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

/**
 * Source with comments removed.
 *
 * Every "this must NOT appear" assertion below runs against THIS, not the raw
 * file. The screen documents the bugs it fixes — it quotes the old
 * `work_description: r.trade` line, and it explains why there is no "Save
 * Draft" button — and an absence test that reads comments would fail on the
 * documentation of the very fix it is checking for. Comments describe;
 * code behaves. Only code is asserted.
 */
function stripComments(text) {
  return text
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '')
    .replace(/\s\/\/[^\n'"`]*$/gm, '');
}
const code = stripComments(src);
// Comment-stripped for the reason this file's own header gives: these modules
// DOCUMENT the patterns they ban ("no raw hex, no rgba()"), and an absence
// test that reads prose fails on the documentation of the fix it is checking.
const chromeSrc = stripComments(chromeRaw);
const primitivesSrc = stripComments(primitivesRaw);
const sharedStyles = stripComments(sharedStylesRaw);
ok(/work_description/.test(code) && !/WHY THIS IS NOT IN THE SCREEN/.test(code),
  'the comment stripper removes prose but keeps code');

/** The buildStyles() body — where every literal would hide. */
const stylesBody = (() => {
  const i = code.indexOf('function buildStyles()');
  // Both halves: the form's own keys and the shared chrome it spreads in.
  return (i === -1 ? '' : code.slice(i)) + '\n' + sharedStyles;
})();
/** Everything ABOVE buildStyles — the component itself. */
const componentBody = code.slice(0, code.indexOf('function buildStyles()'));

// ═══ TAP ONLY ════════════════════════════════════════════════════════════════
console.log('\n── Tap only: no swipe, no long-press, no hidden gesture ──');

ok(!/onLongPress/.test(code), 'no onLongPress anywhere');
ok(!/PanResponder|Swipeable|react-native-gesture-handler|GestureDetector/.test(code),
  'no gesture-handler, PanResponder or Swipeable');
ok(!/onSwipe|swipeEnabled|SwipeableRow/.test(code), 'no swipe handlers');
// A HORIZONTAL ScrollView is itself a swipe affordance. The photo strip used to
// be one, with a literal "swipe ›" hint beside it.
ok(!/<ScrollView[^>]*\shorizontal/.test(code),
  'no horizontal ScrollView — the photo strip is a wrapping grid, not a swiper');
ok(!/swipe/i.test(code), 'the word "swipe" appears nowhere in the shipped UI copy');
ok(/photoGrid/.test(src) && /flexWrap: 'wrap'/.test(stylesBody),
  'photos wrap onto multiple rows instead of scrolling sideways');

// ═══ 56pt MINIMUM TOUCH TARGETS ══════════════════════════════════════════════
console.log('\n── 56pt minimum touch targets ──');

ok(/touchTarget\s*=\s*\{[\s\S]*?min:\s*56/.test(theme),
  'theme.js defines touchTarget.min = 56');
ok(/touchTarget\.min/.test(stylesBody), 'the screen consumes touchTarget.min');
ok(!/minHeight:\s*\d/.test(stylesBody),
  'no hardcoded minHeight — every target comes from the token');

// Every style a finger actually lands on must carry a minimum.
const TAPPABLE = ['chip', 'input', 'secondaryBtn', 'primaryBtn', 'photoBtn',
  'photoBtnGhost', 'headerBack', 'toggleRow', 'lightboxClose'];
for (const name of TAPPABLE) {
  const m = stylesBody.match(new RegExp(`\\n\\s{4}${name}:\\s*\\{([\\s\\S]*?)\\n\\s{4}\\}`));
  const block = m ? m[1] : '';
  ok(/minHeight: touchTarget\.(min|primary)/.test(block)
    || /minWidth: touchTarget\.(min|primary)/.test(block),
  `${name} carries a touchTarget minimum`);
}

// ═══ ONE PRIMARY ACTION PER SCREEN ═══════════════════════════════════════════
console.log('\n── One primary action, and it is the largest thing on screen ──');

// The footer holds exactly one button: Next, or (on the last step) sign.
// lastIndexOf: the FIRST </SafeAreaView> closes the loading branch, not this one.
const footer = chromeSrc.slice(
  chromeSrc.indexOf('<View style={s.footer}>'), chromeSrc.lastIndexOf('</SafeAreaView>'));
const footerPressables = (footer.match(/<Pressable/g) || []).length;
ok(footerPressables === 2,
  `the footer renders one button per branch — Next XOR sign (got ${footerPressables} across both branches)`);
ok(/step < total \?/.test(footer),
  'the two branches are mutually exclusive, so only one is ever on screen');

const primaryBlock = stylesBody.match(/\n\s{4}primaryBtn:\s*\{([\s\S]*?)\n\s{4}\}/);
ok(primaryBlock && /touchTarget\.primary/.test(primaryBlock[1]),
  'the primary button uses the LARGER primary target, not the minimum');
const primaryText = stylesBody.match(/\n\s{4}primaryBtnText:\s*\{([\s\S]*?)\n\s{4}\}/);
ok(primaryText && /typography\.sizes\.xl/.test(primaryText[1]),
  'the primary label is the largest type on the screen');
ok(/touchTarget\s*=\s*\{[\s\S]*?primary:\s*72/.test(theme),
  'touchTarget.primary (72) is larger than touchTarget.min (56)');

// "Save Draft" is REMOVED — autosave replaces it.
ok(!/Save Draft|saveDraft|draftSavedTitle/.test(componentBody),
  'there is no "Save Draft" button — the log saves itself');

// ═══ THE CAMERA GATE ═════════════════════════════════════════════════════════
console.log('\n── The camera is unreachable before crew, activity and location ──');

ok(/cameraReady/.test(model), 'cameraReady is a real, testable rule in the model');
ok(/const ready = cameraReady\(a\)/.test(src),
  'the crew card computes readiness from the shared rule');
ok(/\{!ready \?/.test(src),
  'the photo block is NOT RENDERED until the row is ready — the button does not exist');
// And BOTH handlers refuse too, so a stale render cannot slip a capture
// through. Each function body is sliced out and checked SEPARATELY — asserting
// the guard against the whole file would pass while one of the two paths had
// lost it, which is exactly the hole that would ship an untagged photo.
function fnBody(name) {
  const start = code.indexOf(`const ${name} = async (`);
  if (start === -1) return '';
  const next = code.indexOf('\n  const ', start + 10);
  return code.slice(start, next === -1 ? code.length : next);
}
const GUARD = /if \(!cameraReady\(activities\[activityIndex\]\)\) return;/;
ok(GUARD.test(fnBody('takeActivityPhoto')),
  'takeActivityPhoto itself refuses a row that is not ready');
ok(GUARD.test(fnBody('pickActivityPhoto')),
  'pickActivityPhoto is gated identically — a gallery image is the same evidence');
ok(/cameraLockedHint/.test(src),
  'and the reason is stated rather than the button silently vanishing');
ok(/photoTaggedWith/.test(src),
  'the card shows exactly what the photo will be labelled with before the shutter');

// ═══ CHIPS ═══════════════════════════════════════════════════════════════════
console.log('\n── Chips are ranked, never pre-selected, never blocking ──');

ok(/getActivityChips/.test(src), 'the screen consumes the ranking endpoint');
// Nothing may arrive selected. Selection is only ever read from what the CP
// has tapped into activity_ids / location_ids.
ok(!/selected:\s*true/.test(code), 'no chip is ever constructed as selected');
ok(/selected=\{\(a\.activity_ids \|\| \[\]\)\.includes\(c\.id\)\}/.test(src),
  'an activity chip is selected ONLY because its id is in the row the CP built');
ok(/selected=\{\(a\.location_ids \|\| \[\]\)\.includes\(c\.id\)\}/.test(src),
  'a location chip is selected ONLY because the CP tapped it');
ok(/label=\{t\('chipOther'\)\} selected=\{false\}/.test(src),
  '"Other" is never pre-selected');
ok(/label=\{t\('locationOther'\)\} selected=\{false\}/.test(src),
  '"Somewhere else" is never pre-selected');
// "Other" is rendered inside the SUGGESTED band's wrap, before the collapsed
// catalogue, so it is reachable without scrolling past everything else.
const step2 = src.slice(src.indexOf('const renderStep2'), src.indexOf('const renderStep3'));
const otherAt = step2.indexOf("t('chipOther')");
const catalogAt = step2.indexOf("t('chipsCatalog')");
ok(otherAt > -1 && catalogAt > -1 && otherAt < catalogAt,
  '"Other" is rendered BEFORE the full catalogue — visible without scrolling');
ok(/setChipsByTrade\(\(p\) => \(\{ \.\.\.p, \[tr\]: \[\] \}\)\)/.test(src),
  'a failed chip fetch leaves an empty list — chips never block the entry');

// ── CHIPS ARE PER TRADE ──────────────────────────────────────────────────────
// An electrical crew was offered drywall because ONE list was fetched for the
// whole project and the ranking keyed off the project's prior day.
ok(/getActivityChips\(projectId, date, tr \|\| null\)/.test(code),
  'the crew trade is sent to the endpoint');
// A crew with no trade keys on '', which is the UNFILTERED list — the right
// list for a crew whose trade nobody recorded.
ok(/if \(!wanted\.includes\(''\)\) wanted\.push\(''\)/.test(code),
  'the unfiltered list is ALWAYS fetched too, so "All activities" can mean all');
ok(/const chipsFor = \(a\) => chipsByTrade\[String\(a\?\.trade \|\| ''\)\.trim\(\)\]/.test(code),
  'each crew reads its OWN trade list, keyed on its trade');
ok(/const \{ primary, always, rest, basis \} = chipBandsFor\(a\);/.test(code),
  'Step 2 renders that list, not a shared one');

// ── THE COMPOSITION MOVED INTO THE MODEL ────────────────────────────────────
//
// Device round 4, finding 11: the card offered the whole catalogue — 86 chips
// on a cold start. Four slots per crew, composed, and the composing moved into
// dailyJobsiteModel so it can be EXECUTED rather than grepped. These assertions
// followed it: the guarantees are the ones this block always made, re-pointed
// rather than dropped, and dailyJobsiteModel.test.cjs runs the behaviour end
// to end.
const step2band = code.slice(code.indexOf('const renderStep2'), code.indexOf('const renderStep3'));
ok(/\{primary\.map\(/.test(step2band),
  "the crew's four render INLINE, not behind the catalogue toggle");
// ALWAYS-AVAILABLE is outside the four AND outside the expander, by ruling.
ok(/\{always\.map\(/.test(step2band),
  'and so does the always-available band — burying "rain / no work" on a rain day is worse than a longer list');
ok(step2band.indexOf('{primary.map(') < step2band.indexOf('{always.map('),
  'the ranked four come first; always-available follows them');
// A trade list is a fine suggestion, it is just not a sequenced one.
ok(/basis === 'trade' && \(/.test(step2band) && /chipsFromTrade/.test(step2band),
  'a trade-basis list says so, rather than implying yesterday informed it');
// Only when a trade actually resolved — a crew with no trade would otherwise
// get the ENTIRE catalogue inlined onto its card.
const MODEL = fs.readFileSync(path.join(__dirname, 'dailyJobsiteModel.js'), 'utf8');
ok(/const filtered = Array\.isArray\(resolvedTrades\) && resolvedTrades\.length > 0;/.test(MODEL),
  'promotion is gated on the trade having RESOLVED, not merely being non-empty');
ok(/const tradeCatalog = filtered/.test(MODEL),
  'so an untraded crew keeps the collapsed catalogue it had');
// "All activities" must mean all of them, not the rest of this one trade.
ok(/\? allChips\.filter\(notOther\) : mine;/.test(MODEL),
  'the remainder is drawn from the UNFILTERED list');
ok(/!shown\.has\(c\.id\)/.test(MODEL),
  'and never repeats a chip already shown inline');
ok(/allChips: chipsByTrade\[''\],/.test(code),
  'and the screen actually passes that unfiltered list in');
ok(!/\bchips\.filter\(/.test(code),
  'no single project-wide chip list survives');
// One fetch per DISTINCT trade, not one per crew.
ok(/\[\.\.\.new Set\(/.test(code) && /wanted\.map/.test(code),
  'one fetch per distinct trade on site, not one per crew');
// An unassigned worker gets no activity card, so there is no crew trade to
// fetch a list for. This call was dropped once, when the helper lived only on
// an unmerged branch; it is asserted so it cannot be dropped silently again.
ok(/workRows\(rows\)\.map\(/.test(code),
  'and the unassigned workers are not fetched for at all');

// ── EVERY MODEL HELPER THE SCREEN CALLS IS IMPORTED ──────────────────────────
// Caught for real, on this change: a model helper was called in loadChips and
// never added to the import list. It throws a ReferenceError on the first
// render, INSIDE a try that swallows it, so the CP silently gets no chips at
// all and nothing on screen says why. Every other test in this file passed.
const modelExports = [...model.matchAll(/^export (?:const|function) (\w+)/gm)]
  .map((m) => m[1]);
const importBlock = (code.match(
  /import \{([^}]*)\} from '\.\.\/\.\.\/src\/utils\/dailyJobsiteModel';/,
) || [, ''])[1];
const imported = new Set(importBlock.split(',').map((x) => x.trim()).filter(Boolean));
const bodyOnly = code.replace(
  /import \{[^}]*\} from '[^']*dailyJobsiteModel';/, '',
);
const usedNotImported = modelExports.filter(
  (name) => new RegExp(`\\b${name}\\s*\\(`).test(bodyOnly) && !imported.has(name),
);
ok(modelExports.length > 10, 'the model exports were actually parsed');
ok(usedNotImported.length === 0,
  `every model helper the screen calls is imported${
    usedNotImported.length ? ` — MISSING: ${usedNotImported.join(', ')}` : ''}`);

// ═══ FINDING C ═══════════════════════════════════════════════════════════════
console.log('\n── Finding C: the app never writes the work description ──');

ok(!/work_description:\s*r\.trade/.test(code),
  'the trade auto-fill is GONE (daily_jobsite.jsx:528 on the old screen)');
ok(!/work_description:\s*[a-zA-Z_.]*trade/.test(code + stripComments(model)),
  'work_description is never assigned from a trade anywhere');
ok(/work_description: composeSelection\(/.test(src),
  'work_description is composed only from chips the CP tapped');
ok(/work_description: ''/.test(model),
  'a new row starts with an empty work description');

// ═══ AUTOSAVE ════════════════════════════════════════════════════════════════
console.log('\n── Autosave after every step ──');

ok(/const goNext = async \(\) => \{\s*await flushDraft\(\);/.test(src),
  'moving FORWARD flushes the draft before the step changes');
ok(/const goBack = async \(\) => \{\s*await flushDraft\(\);/.test(src),
  'moving BACK flushes the draft too');
ok(/const flushDraft = useCallback/.test(src), 'flushDraft is a real, stable callback');
ok(/writeDraft\(_key, \{/.test(src), 'the flush writes the whole draft body');
ok(/setTimeout\(async \(\) => \{[\s\S]{0,400}?writeDraft/.test(src),
  'a debounced autosave also runs on every change, not only at step boundaries');
ok(/cameraVisible\) return undefined;/.test(src),
  'autosave stands down while the camera is open, so the shutter path stays fast');
ok(/savedAutomatically/.test(src), 'and the CP is told the log saves itself');
// Draft survival across a kill is what readDraft-first delivers.
ok(/const draft = await readDraft\(_key\);/.test(src),
  'on load the on-device draft is read FIRST — this is what survives an app kill');
ok(/if \(draft\?\.data && Object\.keys\(draft\.data\)\.length\)/.test(src),
  'a non-empty draft short-circuits the server read, so a killed app reopens where it was');

// ═══ THE THREE THAT MUST NOT REGRESS ═════════════════════════════════════════
console.log('\n── The three that must not regress ──');

ok(/persistPhoto/.test(src) && /catch \(_e\) \{[\s\S]{0,600}?photoNotSavedTitle/.test(src),
  'persistPhoto THROWS and the throw is caught and REPORTED — the offline photo guarantee');
ok(/setActivities\(\(prev\) => dropPhoto\(prev, id\)\)/.test(src),
  'a photo that failed to persist is REMOVED, so nothing claims evidence that does not exist');
for (const fn of ['draftKey', 'readDraft', 'writeDraft', 'setDraftBackendId',
  'markPending', 'clearPending', 'markFinalized']) {
  ok(new RegExp(`\\b${fn}\\b`).test(src), `draft lifecycle: ${fn} is carried forward`);
}
ok(/compressUnderCap/.test(src), 'compressUnderCap is carried forward');
ok(/const MAX_BYTES = 150 \* 1024;/.test(
  fs.readFileSync(path.join(__dirname, 'compressPhoto.js'), 'utf8'),
), 'the 150KB cap is unchanged');

// ═══ THE REST OF THE 21 ══════════════════════════════════════════════════════
console.log('\n── The rest of the inventory ──');

const CARRIED = [
  'MAX_PHOTOS_PER_SUBCONTRACTOR', 'photoBucketKey', 'photosInBucket', 'bucketRemaining',
  'activity_id', 'subcontractor_id', 'isPurgedPhoto', 'inlinePhotoData', 'patchPhoto',
  'dropPhoto', 'photoForPayload', 'uploadCapturePhoto', 'uploadPendingActivityPhotos',
  'upload_pending', 'gateCopy', 'recordFinalizeError', 'clearFinalizeError',
  'finalizeErrorCode', 'persistActivityPhotos', 'CameraCaptureModal',
  'useCameraPrewarmPermission', 'EMPTY_OBSERVATION', 'addObservation',
  'updateObservation', 'EQUIPMENT_ITEMS', 'CHECKLIST_ITEMS', 'WEATHER_OPTIONS',
  'removeActivityPhoto', 'addActivity', 'updateActivity', 'hasPendingPhotoUploads',
  'photoNeedsUpload', 'isOfflineError', 'LogbookLockBar', 'SignaturePad',
];
for (const name of CARRIED) {
  ok(new RegExp(`\\b${name}\\b`).test(src + model), `carried forward: ${name}`);
}
ok(/fetchWeather\(fullAddress\)/.test(src),
  'weather auto-population is KEPT — it is an observed fact, not asserted work');
ok(/setProjectAddress\(fullAddress\)/.test(src),
  'address auto-population is KEPT for the same reason');
ok(/if \(!cpSignature\) \{/.test(src), 'the signature client guard stays');

// ═══ TOKENS ONLY ═════════════════════════════════════════════════════════════
console.log('\n── Every colour, size and spacing comes from the token file ──');

const hex = stylesBody.match(/#[0-9a-fA-F]{3,8}\b/g) || [];
ok(hex.length === 0, `no hex colour literals in the stylesheet${hex.length ? ` — ${JSON.stringify(hex)}` : ''}`);
const rgba = stylesBody.match(/rgba?\(/g) || [];
ok(rgba.length === 0, `no rgba() literals in the stylesheet${rgba.length ? ` — ${rgba.length} found` : ''}`);
const numericFont = stylesBody.match(/fontSize:\s*\d/g) || [];
ok(numericFont.length === 0,
  `no numeric fontSize${numericFont.length ? ` — ${JSON.stringify(numericFont)}` : ''}`);
const numericSpace = stylesBody.match(/(padding|margin|gap)[A-Za-z]*:\s*\d/g) || [];
ok(numericSpace.length === 0,
  `no numeric padding/margin/gap${numericSpace.length ? ` — ${JSON.stringify(numericSpace)}` : ''}`);
const numericRadius = stylesBody.match(/borderRadius:\s*\d/g) || [];
ok(numericRadius.length === 0,
  `no numeric borderRadius${numericRadius.length ? ` — ${JSON.stringify(numericRadius)}` : ''}`);
// And no colour literal in the JSX either (icon tints were the old leak).
const jsxHex = componentBody.match(/color="#[0-9a-fA-F]{3,8}"/g) || [];
ok(jsxHex.length === 0, `no hardcoded icon colours${jsxHex.length ? ` — ${JSON.stringify(jsxHex)}` : ''}`);

// ═══ THE APP'S LOOK ══════════════════════════════════════════════════════════
// The stepper was built against the token file and the rest of the app was not,
// so the screen that followed the design system was the one that looked
// foreign. It now wears the house look — GlassCard's light rendering, rebuilt
// from tokens because GlassCard itself is theme-aware and would go dark
// outdoors. These pin the six gaps that were measured against the reference
// screen (app/logbooks/preshift_signin.jsx).
console.log('\n── It looks like the rest of the app ──');

// 1. BACKGROUND — AnimatedBackground's blue gradient, not a flat grey.
ok(/<AnimatedBackground>/.test(chromeSrc), 'the screen still renders AnimatedBackground');
const scrollBlock = stylesBody.match(/\n\s{4}scroll:\s*\{([\s\S]*?)\n?\s{4}\},/);
ok(scrollBlock && !/backgroundColor/.test(scrollBlock[1]),
  'the scroll view paints NO background — the flat grey was hiding the gradient');

// 2. CARD FILL — a white->blue vertical gradient, not a flat white.
ok(/import \{ LinearGradient \} from 'expo-linear-gradient';/.test(primitivesRaw),
  'the card uses a real gradient');
ok(/colors=\{\[outdoor\.cardTop, outdoor\.cardBottom\]\}/.test(primitivesSrc),
  'from outdoor.cardTop to outdoor.cardBottom, the values GlassCard uses');
ok(/export function Card\(\{ s, style, children \}\)/.test(primitivesSrc),
  'and it is one Card component, so every surface matches');

// 3. CORNER RADIUS — 32, the app's card corner, not 12.
const cardFill = stylesBody.match(/\n\s{4}cardFill:\s*\{([\s\S]*?)\n\s{4}\},/);
ok(cardFill && /borderRadius: borderRadius\.xxl/.test(cardFill[1]),
  'cards round to borderRadius.xxl (32), matching GlassCard');

// 4. ELEVATION — a soft diffuse shadow.
ok(/\.\.\.outdoorShadow/.test(stylesBody),
  'cards carry the app\'s soft shadow rather than a hairline border');
const cardShadow = stylesBody.match(/\n\s{4}cardShadow:\s*\{([\s\S]*?)\n\s{4}\},/);
ok(cardShadow && /\.\.\.outdoorShadow/.test(cardShadow[1]),
  'the shadow sits on the OUTER view, away from the gradient\'s overflow clip');

// 5. PADDING — generous, matching GlassCard's spacing.xl.
ok(cardFill && /padding: spacing\.xl/.test(cardFill[1]),
  'cards pad by spacing.xl (32), the same as GlassCard');

// 6. CONTROLS — pills, and a circular back button.
const headerBack = stylesBody.match(/\n\s{4}headerBack:\s*\{([\s\S]*?)\n\s{4}\},/);
ok(headerBack && /borderRadius: borderRadius\.full/.test(headerBack[1]),
  'the back arrow sits in a circular pill, like GlassButton\'s icon variant');
for (const name of ['primaryBtn', 'secondaryBtn', 'chip', 'photoBtn', 'photoBtnGhost']) {
  const m = stylesBody.match(new RegExp(`\\n\\s{4}${name}:\\s*\\{([\\s\\S]*?)\\n\\s{4}\\},`));
  ok(m && /borderRadius: borderRadius\.full/.test(m[1]),
    `${name} is pill-shaped`);
}
const gateBadge = stylesBody.match(/\n\s{4}gateBadge:\s*\{([\s\S]*?)\n\s{4}\},/);
ok(gateBadge && /borderRadius: borderRadius\.full/.test(gateBadge[1])
  && /outdoor\.accentBg/.test(gateBadge[1]),
'status reads as a small rounded pill badge, in the app\'s accent');

// THE RESTYLE DID NOT COST THE TOUCH TARGETS. A pill is visually smaller than
// a rectangle at the same height; the floor is unchanged regardless.
for (const name of ['chip', 'input', 'secondaryBtn', 'photoBtn', 'photoBtnGhost',
  'headerBack', 'toggleRow']) {
  const m = stylesBody.match(new RegExp(`\\n\\s{4}${name}:\\s*\\{([\\s\\S]*?)\\n\\s{4}\\},`));
  ok(m && /touchTarget\.min/.test(m[1]),
    `${name} still carries the 56pt floor after the restyle`);
}
const pb = stylesBody.match(/\n\s{4}primaryBtn:\s*\{([\s\S]*?)\n\s{4}\},/);
ok(pb && /touchTarget\.primary/.test(pb[1]),
  'the primary action still carries the larger 72pt target');

// ═══ THE EASTERN DATE RULE ═══════════════════════════════════════════════════
console.log('\n── Eastern dates ──');

ok(/easternToday/.test(src), 'the screen uses the shared Eastern helper');
ok(/params\.date \|\| easternToday\(\)/.test(src),
  'a missing date defaults to the NEW YORK day, not the UTC one');
ok(!/toISOString\(\)\.split\('T'\)\[0\]/.test(code),
  'the UTC-date bug pattern appears nowhere — it shipped thirteen times already');
ok(!/new Date\(date\)\.toLocaleDateString/.test(code),
  'the log date is not parsed through the device timezone (the old screen did this)');
ok(/formatLogDate\(date\)/.test(src),
  'the header renders the date through the timezone-free formatter');

// ═══ ENGLISH, AND THE COPY BUDGET ════════════════════════════════════════════
console.log('\n── English, and short ──');

ok(!/¿|¡|á|é|í|ó|ú|ñ/.test(code), 'no Spanish on this screen — a logbook is an English record');
ok(!/const TRANSLATIONS/.test(code), 'no screen-local translation map');
ok(/useT\('dailyJobsite'\)/.test(src), 'copy comes from the i18n layer');
// The step titles are what a CP reads to know what to do. Keep them short.
const en = fs.readFileSync(path.join(FRONTEND, 'src', 'i18n', 'en.js'), 'utf8');
// SCOPED TO THE dailyJobsite NAMESPACE. This used to scan the whole catalogue,
// which was right while dailyJobsite was the only stepper form; the ported
// forms carry their own step titles (oshaLog has 2, scaffoldMaintenance 3) and
// an unscoped count picked up all ten. The assertion is unchanged — THIS
// screen has five — it is now asked of the right block.
const djBlock = en.slice(en.indexOf('\n  dailyJobsite: {'), en.indexOf('\n  oshaLog: {'));
const titles = [...djBlock.matchAll(/step[1-5]Title: '([^']+)'/g)].map((m) => m[1]);
ok(djBlock.length > 0 && titles.length === 5,
  `all five step titles exist in the dailyJobsite namespace (got ${titles.length})`);
const longTitle = titles.filter((x) => x.split(/\s+/).length > 12);
ok(longTitle.length === 0,
  `no step title exceeds twelve words${longTitle.length ? ` — ${JSON.stringify(longTitle)}` : ''}`);
ok(/stepOf: 'Step \{n\} of \{m\}'/.test(en), 'the CP always knows where he is in the sequence');

// ═══ THE ROSTER IS NEVER SHOWN AS COMPLETE WHEN IT IS NOT ════════════════════
console.log('\n── A short roster is never rendered as a complete one ──');

ok(/getCheckinsRoster/.test(src), 'the screen asks for the roster ENVELOPE, not the bare list');
ok(/setRosterPartial\(Boolean\(roster\.partial\)\)/.test(src),
  'the partial flag is carried into screen state');
ok(/if \(!roster\) \{\s*setRosterPartial\(true\);/.test(src),
  'a roster read that FAILED is treated as partial, not as an empty jobsite');
ok(/rosterPartial && \(/.test(src), 'and the warning is actually rendered');
ok(/rosterPartialTitle|rosterPartialBody/.test(src), 'with copy that says what is wrong');
ok(/rosterCollapsed > 0/.test(src),
  'a same-name collapse is surfaced too — it means the headcount may be short');

// ═══ GATE PROVENANCE — AND NO CORRECTION AFFORDANCE ══════════════════════════
console.log('\n── Gate provenance, and no company/trade assignment on this log ──');

ok(/a\.gate_sourced && \(/.test(src), 'a gate-sourced crew is visibly marked as such');
ok(/fromGate|gateLocked/.test(src), 'with copy naming the gate as the source');
ok(/gate_sourced: false/.test(src),
  'a hand-added crew is explicitly NOT marked gate-sourced');
ok(/isUnboundCrew\(a\)/.test(src) && /unboundCrew/.test(src),
  'a crew off the roster is saved and visibly flagged, never blocked');

// ASSIGNING A COMPANY OR TRADE DOES NOT BELONG HERE. A worker sets his own at
// check-in; a CP who has to fix one does it during safety orientation. The
// affordance is asserted ABSENT so it cannot drift back onto the daily log.
ok(!/applyCompanyCorrection/.test(code),
  'the company-correction rule is gone from the screen entirely');
ok(!/correctCompany/.test(code),
  'no "Wrong company?" affordance is rendered on Step 1');
ok(!/setCorrecting|commitCorrection/.test(code),
  'and no correction state or handler survives');
ok(!/company_corrected_by|company_corrected_at/.test(code + stripComments(model)),
  'the dead correction-trail keys are gone from the row');
// Provenance itself STAYS — it is set at seed time and is not a correction.
ok(/company_gate/.test(stripComments(model)),
  'company_gate is kept: it records what the gate said, independent of any edit');
ok(/correctedFrom/.test(src),
  'and it is still shown when it differs from the company of record');

// ═══ WEATHER IS OBSERVED, NOT ANSWERED ═══════════════════════════════════════
console.log('\n── Weather: read-only, and never blank on a signed record ──');

ok(/settleFetch\(\(\) => weatherAPI\.getCurrent/.test(code),
  'the weather fetch goes through the app-wide settleFetch, not a bare try/catch');
ok(/setWeatherFetchState\(r\.status\)/.test(code),
  'the outcome is recorded on EVERY result, success included');
ok(/weather_fetch_state: weatherFetchState/.test(code),
  'and it rides on the record, so a reader can tell a failure from an unasked question');

// The manual chooser is GONE. With it gone, a silent failure would leave the CP
// unable to fill the field at all — which is why the failure state came first.
//
// WEATHER LIVES ON STEP 1 NOW, with the crews and the equipment: it is a fact
// about what the day was, not a site condition the CP is asked to assess.
const step1 = code.slice(code.indexOf('const renderStep1'), code.indexOf('const renderStep2'));
const step4 = code.slice(code.indexOf('const renderStep4'), code.indexOf('const renderStep5'));
ok(!/WEATHER_OPTIONS\.map/.test(code),
  'weather is nowhere rendered as a tappable chooser');
ok(!/setWeather\(weather === w/.test(code),
  'nothing on the screen sets weather by hand');
ok(/weatherUnavailableTitle/.test(step1),
  'a failed fetch is STATED on Step 1, not left looking unanswered');
ok(/weatherUnavailableOffline/.test(step1),
  'and offline is distinguished from a server that answered badly');
ok(!/weatherUnavailableTitle/.test(step4),
  'and weather is no longer asked for on Step 4 — it moved, it was not copied');

// ═══ THE FIVE STEPS, AND WHAT IS ON EACH ═════════════════════════════════════
console.log('\n── The restructure: what was on site, and what was walked ──');

const step3code = code.slice(code.indexOf('const renderStep3'), code.indexOf('const renderStep4'));

// STEP 1 — what was on site: crews, equipment, weather.
ok(/EQUIPMENT_ITEMS\.map/.test(step1),
  'equipment is answered on Step 1 — a hoist being present is the same kind of fact as a man being present');
ok(!/EQUIPMENT_ITEMS\.map/.test(step4) && !/EQUIPMENT_ITEMS\.map/.test(step3code),
  'and it appears exactly once — it moved, it was not copied');
ok(/toggleEquipment/.test(step1) && /equipment_on_site: equipmentOnSite/.test(code),
  'the key is unchanged: both PDF renderers read equipment_on_site');

// STEP 3 — observations, plus who came onto the site who was not working on it.
ok(/sectionVisitors/.test(step3code) && !/sectionVisitors/.test(step4),
  'visitors / deliveries / inspections sits with the observations');
ok(/Visitors \/ Deliveries \/ Inspections/.test(en),
  "an INSPECTOR turning up is an arrival, and the heading says so");
ok(/visitors_deliveries: visitorsDeliveries/.test(code),
  'and that key is unchanged too');

// STEP 4 — the nine walked inspections. THE POINT: a tick could say the CP
// looked; it could never say what he found.
ok(/CHECKLIST_ITEMS\.map/.test(step4),
  'Step 4 renders the nine items');
ok(!/CHECKLIST_ITEMS\.map/.test(step1) && !/CHECKLIST_ITEMS\.map/.test(step3code),
  'and only Step 4 does');
ok(/inspectionRow\(checklistItems, it\.key\)/.test(step4),
  'each item is read through the shared rule, not re-derived on the screen');
ok(/INSPECTION_PASS/.test(step4) && /INSPECTION_FAIL/.test(step4),
  'pass and fail are both offered');
ok(!/toggleChecklist/.test(code),
  'the old tick-toggle is GONE — a tick beside "Fall Protections" reads as "fine"');

// A FAILED INSPECTION MUST SAY WHAT FAILED.
ok(/inspectionNoteRequired/.test(step4) && /phInspectionNote/.test(step4),
  'a fail opens a note field');
ok(/noteMissing && \(/.test(step4),
  'and an un-noted fail is flagged on the card itself');
ok(/const badInspections = incompleteInspections\(checklistItems\);/.test(code),
  'signing checks every inspection');
ok(/setStep\(4\);/.test(code),
  'and an un-noted fail sends the CP back to the step that has it, rather than refusing at the signature');

// NOT WALKED IS NOT A PASS — asserted on the review, which is what he signs.
const step5i = code.slice(code.indexOf('const renderStep5'));
ok(/reviewInspectionsNotWalked/.test(step5i),
  'the review names the items he did NOT walk — a missing item is not a passed one');
ok(/errorText/.test(step5i) && /inspectionFail/.test(step5i),
  'and a fail is called a fail, in red, on the screen he signs');

// ═══ THE PROGRESS PIPS SAY WHAT IS UNFINISHED ════════════════════════════════
// stepComplete was a tested pure function CALLED BY NOTHING, with a docstring
// claiming it drove these marks. The marks were purely positional, so a crew
// with no work described first surfaced as "— Nothing yet" on the review, with
// nothing before it.
console.log('\n── Progress pips: position AND completeness ──');

ok(/stepComplete/.test(code), 'the screen actually calls the rule now');
ok(/import \{[^}]*stepComplete[^}]*\} from '\.\.\/\.\.\/src\/utils\/dailyJobsiteModel'/s
  .test(code), 'and imports it from the model rather than restating the rule');
ok(/n < step && !stepComplete\(n, state\)/.test(code),
  'a step he is STANDING ON is work in progress, not an omission — n < step, not n <= step');
ok(/incompleteSteps\.includes\(n\) && s\.progressPipWarn/.test(chromeSrc),
  'the third pip state is applied');
ok(/progressPipWarn: \{ backgroundColor: outdoor\.warn \}/.test(stylesBody),
  'and it comes from the token file, not a literal');
// Order matters: the warn style is listed after progressPipOn so it wins.
// Sliced from the array's own brackets, and BOTH indexes must be real: an
// earlier version of this test sliced up to the first 'progressPipWarn', so a
// swapped array left indexOf('progressPipOn') at -1 and the assertion passed
// on the mutation it existed to catch.
const pipStart = chromeSrc.indexOf('s.progressPip,');
const pipArr = chromeSrc.slice(pipStart, chromeSrc.indexOf(']}', pipStart));
const onAt = pipArr.indexOf('progressPipOn');
const warnAt = pipArr.indexOf('progressPipWarn');
ok(onAt > -1 && warnAt > -1 && onAt < warnAt,
  'an incomplete step he walked past outranks "reached" in the style array');
// Colour alone is a weak signal outdoors in sunlight.
ok(/accessibilityRole="progressbar"/.test(chromeSrc) && /stepsIncomplete/.test(code),
  'the row says it out loud too, rather than relying on colour alone');
ok(/state = \{ activities, observations, checklistItems, cpSignature \}/.test(code),
  'and every input the rule reads is supplied — a missing one reads as complete');

const step5w = code.slice(code.indexOf('const renderStep5'));
ok(/weatherFetchState === 'ok' && weather/.test(step5w),
  'the review step shows weather only when it was actually retrieved');
ok(/weatherUnavailableTitle/.test(step5w),
  '...and says so plainly when it was not');

// ═══ THE GENERAL DESCRIPTION IS DRAFTED, NOT WRITTEN ═════════════════════════
console.log('\n── The drafted general description ──');

ok(/deriveGeneralDescription\(activities, chipTrades\)/.test(code),
  'the draft is composed from the chips the CP tapped, via the shared rule');
ok(/if \(c\.trade\) m\.set\(c\.id, c\.trade\)/.test(code),
  'using the trade newly carried on ActivityChip');
ok(/deriveGeneralDescription/.test(stripComments(model)),
  'and the rule itself lives in the model, where a test can execute it');

// It may only be drafted onto a step he is looking at, and never over his words.
ok(/if \(descriptionTouched\) return;/.test(code),
  'once the CP edits it, the app never overwrites his words again');
ok(/if \(step !== TOTAL_STEPS\) return;/.test(code),
  'and it is only drafted onto the review step, where he can see it');
ok(step5w.includes('setDescriptionTouched(true); setGeneralDescription(v);'),
  'the drafted line is EDITABLE in review — he is signing it');
ok(!/fieldGeneralDescription/.test(step4),
  'and it no longer sits on Step 4, away from the record it summarises');

// ═══ THE UNASSIGNED WORKER IS PRESENT, NOT A UNIT OF WORK ════════════════════
console.log('\n── A man with no company gets no activity card ──');

ok(/isUnassignedWorkerRow/.test(stripComments(model)),
  'the rule lives in the model, where a test can execute it');

// STEP 2 — no card at all. Not a disabled card, not an empty one.
const s2 = code.slice(code.indexOf('const renderStep2'), code.indexOf('const renderStep3'));
ok(/if \(isUnassignedWorkerRow\(a\)\) return null;/.test(s2),
  'Step 2 renders NOTHING for him — no activity, no location, no camera');
ok(/unassignedNoCard_one|unassignedNoCard_other/.test(s2),
  '...and says why, rather than silently omitting him');

// The index must stay the REAL one. Filtering the array instead of returning
// null mid-map would renumber every row, and the photo bucket, the chip
// toggles and every patch helper address rows by position.
ok(/\{activities\.map\(\(a, i\) => \{/.test(s2),
  'the map still walks the FULL activities array, so indexes stay correct');
ok(!/workRows\(activities\)\.map/.test(s2),
  'it does not map a filtered array, which would silently write to the wrong crew');

// STEP 1 — he is shown, and flagged.
const s1 = code.slice(code.indexOf('const renderStep1'), code.indexOf('const renderStep2'));
ok(/isUnassignedWorkerRow\(a\)/.test(s1), 'Step 1 still renders him');
ok(/unassignedTitle/.test(s1) && /unassignedHint/.test(s1),
  '...flagged as needing assignment');

// SOFT FLAG, NOT A GATE. Nothing about him may block the CP.
ok(!/isUnassignedWorkerRow[\s\S]{0,200}?(return;|disabled=\{true\}|toast\.(error|warning))/.test(code),
  'he never blocks a save, disables a control, or raises an error');

// STEP 5 — he stays in the record. He was on site.
const s5 = code.slice(code.indexOf('const renderStep5'));
ok(/isUnassignedWorkerRow\(a\)/.test(s5),
  'the review still lists him — dropping him would hide a man who was there');
ok(/unassignedTitle/.test(s5), '...marked as having no company rather than no work');

// ═══ OBSERVATIONS ════════════════════════════════════════════════════════════
console.log('\n── Observations ──');

ok(/observationComplete\(o\)/.test(src), 'each observation is checked against the shared rule');
ok(/incompleteObservations\(observations\)/.test(src),
  'signing checks every observation for a corrective action');
ok(/setStep\(3\)/.test(src),
  'and an incomplete one sends the CP back to the step that has it');
// Responsible party is PICKED, never typed.
const step3 = src.slice(src.indexOf('const renderStep3'), src.indexOf('const renderStep4'));
ok(/onPress=\{\(\) => updateObservation\(i, 'responsible_party', crewName\(a\)\)\}/.test(step3),
  'the responsible party is PICKED from the crews on site');
ok(!/onChangeText=\{\(v\) => updateObservation\(i, 'responsible_party'/.test(step3),
  'the responsible party can NOT be free-typed');

// COMPACT STEP 1, and the flagged worker inside it.
console.log('\n-- Step 1 is dense, and the flagged man still stands out --');

const step1c = code.slice(code.indexOf('const renderStep1'), code.indexOf('const renderStep2'));

// The crew CARD is gone. Rows, not cards.
ok(!/<Card s=\{s\} key=\{a\.activity_id/.test(step1c),
  'crews render as rows, not full cards');
ok(/style=\{\[s\.crewRow, flagged && s\.crewRowFlagged\]\}/.test(step1c),
  'and the unassigned worker gets a DISTINCT row, not a crew row');
ok(/crewRowFlagged: \{[^}]*borderLeftColor: outdoor\.warn/s.test(stylesBody),
  'he is marked with the warn token, so compaction does not bury him');
ok(/\{flagged \? t\('unassignedTitle'\) : crewName\(a\)\}/.test(step1c),
  'he is named as unassigned rather than as a crew');

// 40pt is only honest because nothing here is tappable.
ok(!/crewRow[^:]*onPress/.test(step1c), 'crew rows are NOT tappable');
const crewRowBlock = (stylesBody.match(new RegExp(`\\n\\s{4}crewRow:\\s*\\{([\\s\\S]*?)\\n\\s{4}\\}`)) || [, ''])[1];
ok(/paddingVertical: spacing\.xs/.test(crewRowBlock) && !/touchTarget/.test(crewRowBlock),
  'the row is 4pt padding on two dense lines, NOT a 56pt target');

// The gate badge shrinks but survives.
ok(/a\.gate_sourced && \(/.test(step1c) && /Lock size=\{12\}/.test(step1c),
  'the gate badge stays, smaller — it is the only thing saying this is locked');

// Equipment folds; crews never do.
ok(/setEquipmentOpen/.test(step1c), 'equipment collapses behind a summary row');
// BOUNDED to the summaryRow block. An open-ended slice runs to the end of the
// stylesheet and finds some LATER minHeight — that exact mistake let this
// mutation survive once already.
const summaryBlock = (stylesBody.match(new RegExp(`\\n\\s{4}summaryRow:\\s*\\{([\\s\\S]*?)\\n\\s{4}\\}`)) || [, ''])[1];
ok(/minHeight: touchTarget\.min/.test(summaryBlock),
  'and that summary row IS tappable, so it carries the full 56pt');
ok(/equipmentSummary/.test(step1c), 'the summary NAMES the plant');
ok(/on\.length \? on\.join\(', '\) : t\('notRecorded'\)/.test(code),
  'nothing ticked reads as NOT RECORDED, never as none');
ok(/\{activities\.map\(\(a, i\) => \{/.test(step1c) && !/activities\.slice\(/.test(step1c),
  'every crew renders — none hidden behind a "+N more", which is what Step 1 is for');

// The sentinel never reaches the screen.
ok(/tradeLabel\(a\.trade\)/.test(step1c), 'Step 1 renders the trade through the label rule');
ok(!/\{!!a\.trade &&/.test(code), 'and the raw trade render is gone everywhere');
ok((code.match(/tradeLabel\(a\.trade\)/g) || []).length === 2,
  'both surfaces that show a roster trade use it — Step 1 and the Step 2 crew line');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
