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
ok(/work_description/.test(code) && !/WHY THIS IS NOT IN THE SCREEN/.test(code),
  'the comment stripper removes prose but keeps code');

/** The buildStyles() body — where every literal would hide. */
const stylesBody = (() => {
  const i = code.indexOf('function buildStyles()');
  return i === -1 ? '' : code.slice(i);
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
const footer = code.slice(code.indexOf('<View style={s.footer}>'), code.lastIndexOf('</SafeAreaView>'));
const footerPressables = (footer.match(/<Pressable/g) || []).length;
ok(footerPressables === 2,
  `the footer renders one button per branch — Next XOR sign (got ${footerPressables} across both branches)`);
ok(/step < TOTAL_STEPS \?/.test(footer),
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
ok(/setChips\(\[\]\)/.test(src),
  'a failed chip fetch leaves an empty list — chips never block the entry');

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
const titles = [...en.matchAll(/step[1-5]Title: '([^']+)'/g)].map((m) => m[1]);
ok(titles.length === 5, `all five step titles exist (got ${titles.length})`);
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

// ═══ GATE PROVENANCE AND THE CORRECTION TRAIL ════════════════════════════════
console.log('\n── Gate provenance, and corrections that keep both values ──');

ok(/a\.gate_sourced && \(/.test(src), 'a gate-sourced crew is visibly marked as such');
ok(/fromGate|gateLocked/.test(src), 'with copy naming the gate as the source');
ok(/applyCompanyCorrection/.test(src), 'the correction goes through the shared rule');
ok(/company_gate/.test(src) && /correctedFrom/.test(src),
  'and the ORIGINAL gate value is displayed alongside the correction');
ok(/gate_sourced: false/.test(src),
  'a hand-added crew is explicitly NOT marked gate-sourced');
ok(/isUnboundCrew\(a\)/.test(src) && /unboundCrew/.test(src),
  'a crew off the roster is saved and visibly flagged, never blocked');

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

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
