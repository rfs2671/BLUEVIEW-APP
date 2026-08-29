/**
 * The i18n layer replaced two hand-rolled string maps:
 *   app/logbooks/review.jsx    TRANSLATIONS, 47 keys per locale
 *   src/components/SignaturePad.js  SIG_STRINGS, 5 keys per locale
 *
 * Two things can silently go wrong with a migration like that, and neither
 * would crash the app:
 *   1. A key is dropped or renamed. The lookup falls back to the key NAME, so
 *      the screen renders "offlineWriteHint" instead of a sentence.
 *   2. A key is added to en.js and forgotten in es.js. Spanish silently serves
 *      English and nobody notices.
 * Both are asserted below against the REAL screen source, so the tests track
 * the components rather than a hand-copied list.
 *
 * It also guards the thing this work exists to fix: SignaturePad's Spanish was
 * unreachable because its locale arrived as a `lang` prop that all 13 render
 * sites leave unset. The fix routes it through the module-level locale
 * instead, so the test asserts BOTH that no call site passes `lang` AND that
 * the component no longer defaults it to 'en'.
 *
 * No test runner in this repo (see RiskScoreCircle.bandFor.test.cjs); the ESM
 * modules are read, stripped and evaluated with tiny React hook stubs so the
 * real shipped store and translator run for real.
 *
 * Run:  node src/i18n/i18n.test.cjs
 */
const fs = require('fs');
const path = require('path');

const I18N = __dirname;
const FRONTEND = path.join(__dirname, '..', '..');

let passed = 0, failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

// ── Load the i18n module under bare node ─────────────────────────────────────
// React is stubbed rather than imported: useState/useEffect/useCallback are the
// only three used, and stubbing them lets useT() actually run here.
function loadI18n() {
  const strip = (f) => fs.readFileSync(path.join(I18N, f), 'utf8')
    .replace(/^import .*$/gm, '')
    .replace(/^export default /m, 'const __default = ');
  const en = strip('en.js');
  const es = strip('es.js');
  const idx = fs.readFileSync(path.join(I18N, 'index.js'), 'utf8')
    .replace(/^import .*$/gm, '')
    .replace(/^export (const|function) /gm, '$1 ')
    .replace(/^export default \{[\s\S]*?\};$/m, '');

  const preamble = `
    const __subs = [];
    const useState = (init) => [typeof init === 'function' ? init() : init, () => {}];
    const useEffect = (fn) => { const c = fn(); if (typeof c === 'function') __subs.push(c); };
    const useCallback = (fn) => fn;
  `;
  // eslint-disable-next-line no-new-func
  return new Function(`
    ${preamble}
    const en = (() => { ${en} return __default; })();
    const es = (() => { ${es} return __default; })();
    ${idx}
    return { CATALOGUES, LOCALES, DEFAULT_LOCALE, getLocale, setLocale,
             subscribeLocale, translate, useLocale, useT, __cleanup: __subs };
  `)();
}
const I = loadI18n();

const reviewSrc = fs.readFileSync(path.join(FRONTEND, 'app', 'logbooks', 'review.jsx'), 'utf8');
const padSrc = fs.readFileSync(path.join(FRONTEND, 'src', 'components', 'SignaturePad.js'), 'utf8');

// ── No new dependency ────────────────────────────────────────────────────────
// expo-localization / i18n-js / react-i18next would each add a package, and
// expo-localization specifically carries a native module -> native rebuild.
const pkg = JSON.parse(fs.readFileSync(path.join(FRONTEND, 'package.json'), 'utf8'));
const deps = Object.keys({ ...pkg.dependencies, ...pkg.devDependencies });
const i18nDeps = deps.filter((d) => /i18n|localiz|globalize|polyglot|lingui/i.test(d));
ok(i18nDeps.length === 0,
  `no i18n package was added to package.json${i18nDeps.length ? ` — ${JSON.stringify(i18nDeps)}` : ''}`);
const idxImports = [...fs.readFileSync(path.join(I18N, 'index.js'), 'utf8')
  .matchAll(/^import .*? from '([^']+)';$/gm)].map((m) => m[1]);
ok(idxImports.every((m) => m === 'react' || m.startsWith('.')),
  `src/i18n/index.js imports only react + local files (${JSON.stringify(idxImports)})`);

// ── Catalogue integrity ──────────────────────────────────────────────────────
//
// EN-ONLY NAMESPACES. A logbook is a legal record filed with the DOB, so it is
// written in English. Spanish belongs where a WORKER has to understand what he
// is signing: the gate, and any worker signature or acknowledgment line inside
// a logbook. A namespace that is entirely CP-facing is therefore English-only.
//
// This is an ALLOWLIST, not a relaxation. A namespace named here must be
// ABSENT from es — declaring it partially, or translating it back later,
// FAILS. Every namespace not named here keeps the full strict parity rules
// below (key-identical, no blanks, no untranslated copies). Adding a namespace
// to this list is a deliberate legal decision, not a way to skip translating.
const EN_ONLY_NAMESPACES = [
  // app/logbooks/daily_jobsite.jsx — section headers, field labels,
  // placeholders, photo/permission errors, save+submit toasts, activity-chip
  // band labels. All CP-facing; the CP signs this log, no worker does.
  'dailyJobsite',
  // app/site/logbooks.jsx — the filed-log viewer. Read by a CP or a DOB
  // inspector, and a DOB inspector reads English.
  'logbookView',
  // app/logbooks/review.jsx — the CP's approve / send-home / assign-trade
  // decisions on flagged workers.
  'review',
  // app/logbooks/osha_log.jsx — the OSHA/SST certification register. The CP
  // signs it; the certification NAMES are card identifiers and stay in
  // oshaLogModel, not here.
  'oshaLog',
  // app/logbooks/scaffold_maintenance.jsx — the DOB sidewalk-shed daily
  // inspection. The 19 question labels stay in scaffoldMaintenanceModel
  // because the filed PDF prints the same strings.
  'scaffoldMaintenance',
  // app/logbooks/toolbox_talk.jsx — the safety talk. The 24 topic labels stay
  // in toolboxTalkModel for the same reason.
  'toolboxTalk',
  // app/logbooks/concrete_operations.jsx — the pour record. The four formwork
  // item labels stay in concreteOperationsModel because the filed PDF prints
  // the same strings.
  'concreteOperations',
  // app/logbooks/crane_operations.jsx — the crane log. The fifteen
  // pre-operation check labels stay in craneOperationsModel for the same
  // reason.
  'craneOperations',
  // app/logbooks/excavation_monitoring.jsx — the adjacent-structure and
  // vibration readings. The soil types and protection systems stay in
  // excavationMonitoringModel: they are enum VALUES stored in the payload and
  // printed verbatim.
  'excavationMonitoring',
  // app/logbooks/hot_work.jsx — the burn permit. The seven precaution labels
  // and the five work types stay in hotWorkModel because the filed permit
  // prints the same strings.
  'hotWork',
  // app/logbooks/ssc_daily_safety_log.jsx — the site safety coordinator's
  // daily narrative. The five compliance labels and the three narrative
  // prompts stay in sscDailySafetyLogModel for the same reason.
  'sscDailySafetyLog',
  // src/components/LogbookLockBar.jsx and the eleven editors — lock, refusal
  // and signature prompts. CP-facing.
  'finalize',
  // app/logbooks/fall_protection.jsx — the strap log. The equipment types and
  // the three inspection results stay in fallProtectionModel because both PDF
  // renderers print those exact stored strings; `standardNotice` is here AND
  // in backend/server.py's FALL_PROTECTION_NOTICE, and the model test asserts
  // the two agree word for word.
  'fallProtection',
  // app/reports.jsx — admin only.
  'reportPreview',
];

// NOT en-only, and deliberately so. `signature` (SignaturePad's affirmation
// text) renders only on CP screens today, so strictly it would belong above. It
// is held to the normal strict rules instead because it is the component a
// WORKER would use if worker signing moves in-app — which is on the roadmap —
// and deleting its Spanish would delete the mechanism the worker-signature
// exception depends on. This assertion is the guard: adding `signature` to the
// allowlist fails here, so the decision cannot be reversed silently.
ok(!EN_ONLY_NAMESPACES.includes('signature'),
  'signature stays TRANSLATED — it is what a worker signs if worker signing moves in-app');

const nsEn = Object.keys(I.CATALOGUES.en).sort();
const nsEs = Object.keys(I.CATALOGUES.es).sort();
const expectedEs = nsEn.filter((ns) => !EN_ONLY_NAMESPACES.includes(ns)).sort();

ok(JSON.stringify(nsEs) === JSON.stringify(expectedEs),
  `es declares exactly the translated namespaces (${nsEs.join(', ')})`);

// The allowlist must not rot: a name here that no longer exists in en, or one
// that has quietly reappeared in es, is a stale rule and fails loudly.
for (const ns of EN_ONLY_NAMESPACES) {
  ok(nsEn.includes(ns), `EN_ONLY "${ns}": still exists in en (stale allowlist entry otherwise)`);
  ok(!nsEs.includes(ns),
    `EN_ONLY "${ns}": absent from es — a logbook is an English legal record`);
}

for (const ns of nsEn) {
  if (EN_ONLY_NAMESPACES.includes(ns)) {
    // Still held to the rules that do not involve a translation.
    const only = Object.keys(I.CATALOGUES.en[ns]);
    const blankEn = only.filter((k) => !String(I.CATALOGUES.en[ns][k]).trim());
    ok(blankEn.length === 0,
      `${ns} (en-only): no blank strings${blankEn.length ? ` — ${JSON.stringify(blankEn)}` : ''}`);
    continue;
  }
  const a = Object.keys(I.CATALOGUES.en[ns]).sort();
  const b = Object.keys(I.CATALOGUES.es[ns]).sort();
  const missingEs = a.filter((k) => !b.includes(k));
  const missingEn = b.filter((k) => !a.includes(k));
  ok(missingEs.length === 0 && missingEn.length === 0,
    `${ns}: en/es are key-identical${missingEs.length ? ` — missing from es: ${JSON.stringify(missingEs)}` : ''}${missingEn.length ? ` — missing from en: ${JSON.stringify(missingEn)}` : ''}`);

  const blank = a.filter((k) => !String(I.CATALOGUES.en[ns][k]).trim()
    || !String(I.CATALOGUES.es[ns][k]).trim());
  ok(blank.length === 0, `${ns}: no blank strings${blank.length ? ` — ${JSON.stringify(blank)}` : ''}`);

  const untranslated = a.filter((k) => I.CATALOGUES.en[ns][k] === I.CATALOGUES.es[ns][k]);
  ok(untranslated.length === 0,
    `${ns}: no es value is a copy of the en value${untranslated.length ? ` — ${JSON.stringify(untranslated)}` : ''}`);
}

// An EN-only namespace must still RESOLVE under a Spanish locale — falling back
// to English, never to a blank or a raw key. This is what makes the removal
// safe rather than merely tidy.
for (const ns of EN_ONLY_NAMESPACES) {
  const keys = Object.keys(I.CATALOGUES.en[ns]);
  const bad = keys.filter((k) => I.translate(ns, k, 'es') !== I.CATALOGUES.en[ns][k]);
  ok(bad.length === 0,
    `${ns}: every key still resolves to English under the es locale${bad.length ? ` — ${JSON.stringify(bad.slice(0, 5))}` : ''}`);
}

// The two migrated maps must not have SHRUNK. `>=`, not `===`: the claim is
// that nothing was lost in the migration, and a hardcoded total additionally
// asserts that nothing may ever be ADDED -- which is not a claim anyone meant
// to make, and which failed the first time a reason code was added (48).
// Same brittleness the CI workflow already warns about in its own comment:
// "the count is deliberately not written here -- it was '26 of the 28' and was
// wrong within a day of being typed".
ok(Object.keys(I.CATALOGUES.en.review).length >= 47,
  `review namespace still carries its 47 migrated keys (got ${Object.keys(I.CATALOGUES.en.review).length})`);
ok(Object.keys(I.CATALOGUES.en.signature).length === 5,
  `signature namespace still carries all 5 migrated keys (got ${Object.keys(I.CATALOGUES.en.signature).length})`);

// ── Every key the screens ASK for must resolve, in both locales ──────────────
function usedKeys(src) {
  return [...new Set([...src.matchAll(/\bt\('([^']+)'\)/g)].map((m) => m[1]))].sort();
}
const reviewUsed = usedKeys(reviewSrc);
const padUsed = usedKeys(padSrc);
ok(reviewUsed.length === 40,
  `review.jsx calls 40 distinct literal keys (got ${reviewUsed.length})`);
ok(padUsed.length === 5, `SignaturePad calls 5 distinct keys (got ${padUsed.length})`);

// Presence is checked on the catalogue, NOT by comparing the result to the
// key: review's `by` legitimately translates to the word "by" in English, so a
// value===key test would flag a perfectly good string as missing.
const has = (ns, k, loc) =>
  Object.prototype.hasOwnProperty.call(I.CATALOGUES[loc][ns] || {}, k);
for (const [ns, used] of [['review', reviewUsed], ['signature', padUsed]]) {
  for (const loc of I.LOCALES) {
    // FLIPPED for EN-only namespaces, not dropped. `review` is now English-only
    // (a CP's approve / send-home decisions), so demanding an es ENTRY would
    // assert the rule we just reversed. The guard that actually matters is
    // unchanged and still runs against both locales: every key the component
    // asks for must RESOLVE to a real string. For an EN-only namespace that
    // means resolving to the English one through translate()'s fallback —
    // which is the difference between "deliberately English" and "missing".
    const enOnly = EN_ONLY_NAMESPACES.includes(ns);
    const unresolved = enOnly
      ? used.filter((k) => I.translate(ns, k, loc) !== I.CATALOGUES.en[ns][k])
      : used.filter((k) => !has(ns, k, loc));
    ok(unresolved.length === 0,
      `${ns}/${loc}: every key the component asks for resolves${enOnly ? ' (to English — EN-only namespace)' : ''}${unresolved.length ? ` — ${JSON.stringify(unresolved)}` : ''}`);
  }
}

// review.jsx builds reason keys dynamically: t(`reason_${code}`). Those cannot
// be found by scanning call sites, so the backend codes are checked directly.
ok(/t\(`reason_\$\{/.test(reviewSrc),
  'review.jsx still builds cert-review reason keys dynamically');
const REASON_CODES = Object.keys(I.CATALOGUES.en.review).filter((k) => k.startsWith('reason_'));
// EVERY BACKEND CODE MUST HAVE COPY -- the claim worth making, and stronger
// than a total. A code shipped without wording renders as its raw key, which
// is what the loop below catches; this asserts the five that predate
// CARD_NUMBER_FORMAT are all still here rather than freezing the count.
for (const required of ['reason_CLASS_UNVERIFIED', 'reason_EXPIRY_IMPLAUSIBLE',
  'reason_EXPIRY_UNPARSEABLE', 'reason_EXPIRY_CONFLICT', 'reason_DUPLICATE_SST',
  'reason_CARD_NUMBER_FORMAT']) {
  ok(REASON_CODES.includes(required), `${required} is mapped`);
}
for (const loc of I.LOCALES) {
  // Same flip as above: `review` is EN-only, so a dynamically built reason key
  // must resolve to the ENGLISH string under every locale. Still a real guard —
  // a backend code with no mapped copy renders as the raw key and fails here.
  const bad = REASON_CODES.filter(
    (k) => I.translate('review', k, loc) !== I.CATALOGUES.en.review[k],
  );
  ok(bad.length === 0, `review/${loc}: every reason_ code resolves (to English)`);
}

// Nothing was migrated that the screen has stopped using — and nothing is
// quietly orphaned either. `assign` and `refresh` came across from the old
// TRANSLATIONS map and have no call site; they are kept (the migration must
// not drop strings) and pinned here so the count stays honest.
const reviewAll = Object.keys(I.CATALOGUES.en.review);
const orphans = reviewAll
  .filter((k) => !reviewUsed.includes(k) && !k.startsWith('reason_')).sort();
ok(JSON.stringify(orphans) === JSON.stringify(['assign', 'refresh']),
  `review: the only unused keys are the two the old map already carried (got ${JSON.stringify(orphans)})`);

// ── translate(): fallback order is es -> en -> the key itself ────────────────
// Repointed from `review` to `signature`: review is EN-only now, so it can no
// longer demonstrate "the active locale wins" — it would pass for the wrong
// reason. signature is the namespace that still carries Spanish, so it is the
// one that can actually prove the precedence order.
ok(I.translate('signature', 'verified', 'es') === I.CATALOGUES.es.signature.verified,
  'translate: the active locale wins');
ok(I.translate('signature', 'verified', 'de') === I.CATALOGUES.en.signature.verified,
  'translate: an unknown locale falls back to the current locale (en by default)');
// And the EN-only direction: a namespace with no es entry resolves to English.
ok(I.translate('review', 'title', 'es') === I.CATALOGUES.en.review.title,
  'translate: an EN-only namespace resolves to English under es');
ok(I.translate('review', 'no_such_key', 'es') === 'no_such_key',
  'translate: a missing key returns the KEY — review.jsx detects unmapped reason codes this way');
ok(I.translate('nosuchns', 'title', 'es') === 'title',
  'translate: an unknown namespace returns the key, it does not throw');

// ── The locale store ─────────────────────────────────────────────────────────
ok(I.getLocale() === 'en', 'locale starts at en (so an unmigrated caller sees no change)');
ok(I.setLocale('es') === 'es' && I.getLocale() === 'es', 'setLocale switches');
ok(I.setLocale('klingon') === 'en' && I.getLocale() === 'en',
  'setLocale rejects an unknown locale and falls back to en');

const seen = [];
const off = I.subscribeLocale((l) => seen.push(l));
I.setLocale('es');
ok(JSON.stringify(seen) === JSON.stringify(['es']), 'subscribers are notified on change');
I.setLocale('es');
ok(seen.length === 1, 'setting the same locale twice does not re-notify');
off();
I.setLocale('en');
ok(seen.length === 1, 'unsubscribe stops notifications');

const after = [];
I.subscribeLocale(() => { throw new Error('boom'); });
const off2 = I.subscribeLocale((l) => after.push(l));
I.setLocale('es');
ok(JSON.stringify(after) === JSON.stringify(['es']),
  'a throwing subscriber does not stop the others from updating');
off2();
I.setLocale('en');

// ── useT(): namespacing + the override that keeps `lang` working ─────────────
ok(I.useT('review')('title') === I.CATALOGUES.en.review.title,
  'useT is namespaced — t("title") needs no prefix, so migrated call sites are unchanged');
ok(I.useT('signature')('verified') === I.CATALOGUES.en.signature.verified,
  'useT resolves the signature namespace independently of review');
ok(I.useT('review')('title') !== I.useT('signature')('verified'),
  'two namespaces can own different values without colliding');
ok(I.useT('signature', 'es')('verified') === I.CATALOGUES.es.signature.verified,
  'useT(ns, override) pins a locale — SignaturePad`s lang prop still works when passed');
ok(I.useT('signature', undefined)('verified') === I.CATALOGUES.en.signature.verified,
  'useT(ns, undefined) follows the app-wide locale');
I.setLocale('es');
ok(I.useT('signature')('verified') === I.CATALOGUES.es.signature.verified,
  'THE RECONNECTION: with no prop and no provider, SignaturePad`s translator follows the app locale into Spanish');
ok(I.useT('signature', 'en')('verified') === I.CATALOGUES.en.signature.verified,
  'an explicit lang override still beats the app locale');
I.setLocale('en');

// ── The wiring in the components themselves ─────────────────────────────────
ok(!/SIG_STRINGS/.test(padSrc), 'SignaturePad: the local SIG_STRINGS map is gone');
ok(/from '\.\.\/i18n'/.test(padSrc), 'SignaturePad: pulls its copy from src/i18n');
ok(/useT\('signature'/.test(padSrc), 'SignaturePad: uses the signature namespace');
ok(!/lang = 'en'/.test(padSrc),
  "SignaturePad: `lang` no longer defaults to 'en' — that default is what pinned it to English");
ok(/^\s*lang,\s*$/m.test(padSrc),
  'SignaturePad: `lang` is still accepted as an override prop (unset === follow the app)');

ok(!/const TRANSLATIONS/.test(reviewSrc), 'review.jsx: the local TRANSLATIONS map is gone');
ok(/useT\('review'\)/.test(reviewSrc), 'review.jsx: uses the review namespace');
// FLIPPED, not dropped. The toggle is GONE from review.jsx by ruling: it
// controlled nothing there once the screen became English-only, the screen
// renders no SignaturePad, and the timestamps are unconditional en-US. Its one
// real effect was remote — an app-wide setLocale changing a pad on another
// screen. That choice moved onto SignaturePad, beside the sentence being
// signed. Asserted as an ABSENCE so it cannot drift back.
ok(!/setLocale\(/.test(reviewSrc),
  'review.jsx: no language toggle — it controlled nothing on this screen');
ok(!/useLocale\(\)/.test(reviewSrc),
  'review.jsx: holds no locale state at all');
ok(!/setLang/.test(reviewSrc), 'review.jsx: the screen-local lang state is gone');
ok(/toLocaleString\('en-US'/.test(reviewSrc),
  "review.jsx: timestamps are unconditional en-US — a filed fact renders one way");

// SignaturePad owns the affirmation's language locally, so there is no session
// state to lose and nothing else in the app changes with it.
ok(/const \[padLang, setPadLang\] = useState\(lang\)/.test(padSrc),
  'SignaturePad: the language choice is LOCAL to the pad');
ok(/setPadLang\(/.test(padSrc), 'SignaturePad: renders a control that changes it');
ok(/lang === undefined &&/.test(padSrc),
  'SignaturePad: the toggle hides when a caller pinned `lang` — a pinned locale means it');
ok(!/setLocale\(/.test(padSrc),
  'SignaturePad: it never reaches for the app-wide locale');

// The premise of the whole reconnection: no render site passes lang.
function walk(dir, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, out);
    else if (/\.(js|jsx)$/.test(e.name)) out.push(p);
  }
  return out;
}
const allSource = [...walk(path.join(FRONTEND, 'app')), ...walk(path.join(FRONTEND, 'src'))];
const renderSites = allSource.filter((p) => /<SignaturePad/.test(fs.readFileSync(p, 'utf8')));
// FOURTEEN with the fall-protection log. The count is pinned so a NEW render
// site cannot appear without someone checking it against the rule below — that
// no call site passes `lang`, which is the premise the whole reconnection rests
// on. It is a checkpoint, not a ceiling.
ok(renderSites.length === 14,
  `14 files render <SignaturePad> (got ${renderSites.length})`);
const passLang = renderSites.filter((p) => /<SignaturePad[\s\S]{0,1200}?\blang=/.test(fs.readFileSync(p, 'utf8')));
ok(passLang.length === 0,
  `zero render sites pass lang= — the app locale is the only path to Spanish${passLang.length ? ` — ${JSON.stringify(passLang)}` : ''}`);

// ── backend/checkin.html is NOT touched by this layer ────────────────────────
// It is a standalone HTML page served by the backend, outside this bundle. Its
// 87-key map was READ to model the namespace shape and deliberately left alone.
const checkin = path.join(FRONTEND, '..', 'backend', 'checkin.html');
if (fs.existsSync(checkin)) {
  const html = fs.readFileSync(checkin, 'utf8');
  ok(/const TRANSLATIONS = \{/.test(html) && !/src\/i18n/.test(html),
    'backend/checkin.html still owns its own TRANSLATIONS map and does not import this layer');
} else {
  ok(false, 'backend/checkin.html not found');
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
