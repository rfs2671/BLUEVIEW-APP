/**
 * The Compliance cards, counted from the shipped source.
 *
 *   1. The renewal banner says "1 Permit Needs Renewal" for one permit and
 *      "N Permits Need Renewal" for more, in English and Spanish. It said
 *      "1 Permit Need Renewal" (the old `Permit{n > 1 ? 's' : ''} Need`).
 *   2. The header lists EVERY BIN the records come from -- 588 Thomas S
 *      Boyland: 3255362 and 3430621 -- read from GET /dob-logs `tracked_bins`.
 *   3. An ECB card shows the hearing date AND time on its face (not only when
 *      expanded), and a $0 penalty with the hearing pending reads "Penalty
 *      set at hearing" in a NEUTRAL colour -- not the red / amber / orange of
 *      a debt.
 *   4. A complaint / violation card leads with the stored plain line, with
 *      DOB's own text behind a "Show DOB text" toggle -- and the screen only
 *      displays the line: it never asks for one.
 *
 * The helpers (src/utils/complianceCard.js) and the catalogues
 * (src/i18n/en.js, es.js) are EVALUATED as they ship; the screen is read with
 * comments stripped.
 *
 * Run:  node src/utils/complianceCard.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
let passed = 0, failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

function loadModule(file) {
  const src = fs.readFileSync(path.join(__dirname, file), 'utf8')
    .replace(/^export (function|const) /gm, '$1 ');
  const names = [...src.matchAll(/^(?:function|const) (\w+)/gm)].map((m) => m[1]);
  // eslint-disable-next-line no-new-func
  return new Function(`${src}\nreturn { ${names.join(', ')} };`)();
}
function loadCatalogue(file) {
  const src = fs.readFileSync(path.join(FRONTEND, 'src', 'i18n', file), 'utf8')
    .replace(/^import .*$/gm, '')
    .replace(/^export default /m, 'const __default = ');
  // eslint-disable-next-line no-new-func
  return new Function(`${src}\nreturn __default;`)();
}
function stripComments(src) {
  const blank = (s) => s.replace(/[^\n]/g, '');
  return src.split('\r\n').join('\n')
    .replace(/\{\s*\/\*[\s\S]*?\*\/\s*\}/g, blank)
    .replace(/\/\*[\s\S]*?\*\//g, blank)
    .replace(/(^|[^:'"`\\])\/\/.*$/gm, '$1');
}
/** The source of `const name = (...) => { ... };` (brace-matched). */
function arrowBody(src, name) {
  const at = src.indexOf(`const ${name} = `);
  if (at < 0) return '';
  const open = src.indexOf('{', src.indexOf('=>', at));
  let d = 0;
  for (let i = open; i < src.length; i += 1) {
    if (src[i] === '{') d += 1;
    else if (src[i] === '}') { d -= 1; if (d === 0) return src.slice(at, i + 1); }
  }
  return '';
}

// A missing helper is a FAIL, not a crash: every assertion below still runs
// (against helpers that answer nothing) and reports its own reason.
let C;
try {
  C = loadModule('complianceCard.js');
  ok(true, 'src/utils/complianceCard.js loads');
} catch (e) {
  ok(false, `src/utils/complianceCard.js loads (${e.code || e.message})`);
  C = new Proxy({}, { get: () => () => undefined });
}
const EN = loadCatalogue('en.js').compliance;
const ES = loadCatalogue('es.js').compliance;
const tEn = (k) => EN[k] || k;
const tEs = (k) => ES[k] || k;
const screen = stripComments(fs.readFileSync(path.join(FRONTEND, 'app', 'project', '[id]', 'dob-logs.jsx'), 'utf8'));
const feed = stripComments(fs.readFileSync(path.join(FRONTEND, 'src', 'components', 'ActivityFeed.jsx'), 'utf8'));

// ── 1. Renewal banner, singular and plural ─────────────────────────────────
ok(C.renewalTitle(1, tEn) === '1 Permit Needs Renewal', `en 1 -> "${C.renewalTitle(1, tEn)}"`);
ok(C.renewalTitle(2, tEn) === '2 Permits Need Renewal', `en 2 -> "${C.renewalTitle(2, tEn)}"`);
ok(C.renewalTitle(1, tEs) === '1 permiso necesita renovación', `es 1 -> "${C.renewalTitle(1, tEs)}"`);
ok(C.renewalTitle(2, tEs) === '2 permisos necesitan renovación', `es 2 -> "${C.renewalTitle(2, tEs)}"`);
ok(/renewalTitle\(renewablePermits\.length, tc\)/.test(screen),
  'the banner renders renewalTitle(renewablePermits.length, tc)');
ok(!/Permit\{/.test(screen) && !/Need Renewal/.test(screen),
  'no hand-built "Permit{s} Need Renewal" left in the screen');

// ── 2. Every tracked BIN in the header ─────────────────────────────────────
ok(C.binHeaderText(['3255362', '3430621'], tEn) === 'BINs: 3255362 · 3430621',
  `two BINs -> "${C.binHeaderText(['3255362', '3430621'], tEn)}"`);
ok(C.binHeaderText(['3255362'], tEn) === 'BIN: 3255362', 'one BIN -> "BIN: 3255362"');
ok(String(C.binHeaderText(['3255362', '3430621'], tEs) || '').includes('3255362 · 3430621'), 'es lists both BINs');
ok(/data\.tracked_bins/.test(screen) && /setTrackedBins\(/.test(screen),
  'the screen reads tracked_bins from GET /dob-logs');
ok(/binHeaderText\(trackedBins\.length \? trackedBins : \[nycBin\], tc\)/.test(screen),
  'the BIN badge renders every tracked BIN (the project BIN alone only when none came back)');
ok(!/BIN: \{nycBin\}/.test(screen), 'the single-BIN "BIN: {nycBin}" header is gone');

// ── 3. ECB hearing date AND time; "Penalty set at hearing" is neutral ──────
ok(C.formatHearingTime('09:30', 'en') === '9:30 AM', `09:30 en -> "${C.formatHearingTime('09:30', 'en')}"`);
ok(C.formatHearingTime('13:00', 'en') === '1:00 PM', '13:00 en -> "1:00 PM"');
ok(C.formatHearingTime('10:30', 'es') === '10:30 a. m.', '10:30 es -> "10:30 a. m."');
ok(C.formatHearingTime('', 'en') === '' && C.formatHearingTime('25:00', 'en') === '', 'no time -> ""');
const fmt = (d) => `<${d}>`;
ok(C.hearingText({ date: '2026-11-18', time: '09:30' }, 'en', tEn, fmt) === 'Hearing <2026-11-18> at 9:30 AM',
  `hearing line carries date AND time: "${C.hearingText({ date: '2026-11-18', time: '09:30' }, 'en', tEn, fmt)}"`);
ok(C.hearingText({ date: '2026-11-18', time: null }, 'en', tEn, fmt) === 'Hearing <2026-11-18>',
  'no time -> the date alone, never a blank "at"');
ok(C.hearingText({ date: '2026-11-18', time: '09:30' }, 'es', tEs, fmt) === 'Audiencia el <2026-11-18> a las 9:30 a. m.',
  'es hearing line');
ok(C.penaltyTone({ kind: 'set_at_hearing' }) === 'neutral', 'set_at_hearing -> neutral');
ok(C.penaltyTone({ kind: 'amount', amount: '1250' }) === 'amount', 'an imposed amount -> amount');
ok(C.penaltyTone(null) === null, 'no penalty -> nothing');
ok(C.formatMoney('1250') === '$1,250', 'money formatted');
ok(EN.penaltySetAtHearing === 'Penalty set at hearing' && ES.penaltySetAtHearing,
  'en/es "Penalty set at hearing"');

const ecb = arrowBody(screen, 'renderEcbHearing');
ok(ecb.length > 0, 'renderEcbHearing found');
ok(/hearingText\(log\.ecb_hearing, locale, tc, formatDate\)/.test(ecb), 'the hearing line comes from ecb_hearing');
const neutralAt = ecb.indexOf("tone === 'neutral'");
const neutral = neutralAt >= 0 ? ecb.slice(neutralAt, ecb.indexOf(')}', ecb.indexOf("tc('penaltySetAtHearing')", neutralAt)) + 2) : '';
ok(/tc\('penaltySetAtHearing'\)/.test(neutral), 'the neutral branch says "Penalty set at hearing"');
ok(/semantic\.neutralStrong/.test(neutral) && /semantic\.neutralBg/.test(neutral),
  'the neutral branch is drawn in the neutral tokens');
ok(!/semantic\.(critical|attention)|#f97316/i.test(neutral),
  'and in no red / amber / orange');
const violation = arrowBody(screen, 'renderViolationCard');
const expandedAt = violation.indexOf('{isExpanded && (');
ok(violation.indexOf('renderEcbHearing(log)') > 0 && violation.indexOf('renderEcbHearing(log)') < expandedAt,
  'the hearing is on the card FACE, above the expanded section');
ok(!/log\.penalty_amount && subtype === 'ECB'/.test(screen),
  'the ECB "$penalty_amount" box (6bgk-3dad amount_paid, "$0") is gone');

// ── 4. The plain line leads; DOB text behind a toggle; display only ────────
const lead = arrowBody(screen, 'renderPlainLead');
ok(/plainLineFor\(log, locale\)/.test(lead), 'the lead line is the stored plain_line in the reader\'s language');
ok(/tc\('showDobText'\)/.test(lead) && /tc\('hideDobText'\)/.test(lead), 'a "Show DOB text" / "Hide DOB text" toggle');
ok(/open && !!log\.dob_text && <Text/.test(lead), 'DOB text renders only when the toggle is open');
for (const card of ['renderViolationCard', 'renderComplaintCard']) {
  const body = arrowBody(screen, card);
  const at = body.indexOf('renderPlainLead(log)');
  ok(at > 0 && at < body.indexOf('{isExpanded && ('), `${card} leads with renderPlainLead(log)`);
  ok(!/\{log\.ai_summary\}/.test(body), `${card} no longer leads with ai_summary`);
}
ok(!/plain[-_]line/i.test(screen.replace(/plain_line_source|plainLine\w*/g, '')),
  'the screen calls no plain-line endpoint (it only displays plain_line)');
ok(C.plainLineFor({ plain_line: { en: 'Work without a permit', es: 'Trabajo sin permiso' } }, 'es') === 'Trabajo sin permiso',
  'es reader gets the Spanish line');
ok(C.plainLineFor({ plain_line: { en: 'Work without a permit' } }, 'es') === 'Work without a permit',
  'English when Spanish is missing');
ok(C.plainLineFor({}, 'en') === '', 'no line -> ""');
for (const k of ['showDobText', 'hideDobText', 'plainLineAi', 'hearingAt', 'hearingOn', 'penalty',
  'penaltySetAtHearing', 'balanceDue', 'binOne', 'binMany', 'renewalOne', 'renewalMany']) {
  ok(EN[k] && ES[k] && EN[k] !== ES[k], `compliance.${k} in en and es`);
}

// ── The Activity feed's complaint / violation cards carry the same line ────
ok(/plainLineFor\(log, locale\)/.test(feed) && /styles\.cardPlainLine/.test(feed),
  'ActivityFeed shows the stored plain line on a complaint / violation signal');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed) process.exit(1);
