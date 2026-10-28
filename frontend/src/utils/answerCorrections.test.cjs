/**
 * OWNER PORTAL → "MARK WRONG" (answer corrections): the correct answer is
 * required and the note optional; what the Answers list shows; that the
 * form is on the Answers screen and on a queue item with an answer; and
 * that only the operator's /api/owner routes are called.
 *
 * Run:  node src/utils/answerCorrections.test.cjs
 */

const fs = require('fs');
const path = require('path');
const { loadEsm } = require('./esmHarness.cjs');

let passed = 0;
let failed = 0;
const ok = (cond, label) => {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
};
const read = (p) => fs.readFileSync(path.join(__dirname, '..', '..', p), 'utf8');

const C = loadEsm('src/utils/answerCorrections.js');

console.log('\nthe correct answer is required, the note optional');
ok(!!C.correctionRequest('').error, 'empty: refused');
ok(!!C.correctionRequest('   ').error, 'blank: refused');
ok(!!C.correctionRequest('x').error, 'one character: refused');
const a = C.correctionRequest('  3\'-6" per A-101 rev 2 ');
ok(a.body && a.body.correct_answer === '3\'-6" per A-101 rev 2' && !('note' in a.body),
  'trimmed; no note is not sent');
const b = C.correctionRequest('3\'-6"', '  rev 2 changed it ');
ok(b.body && b.body.note === 'rev 2 changed it', 'a note is sent trimmed');
ok(!!C.correctionRequest('3\'-6"', 'n'.repeat(C.MAX_NOTE + 1)).error, 'a note too long: refused');

console.log('\nan answer row');
const row = {
  answer: { id: 'al1', surface: 'group', question: 'door 101?', final_text: "3'-0\"",
    records: [{ id: 'r1', sheet: 'A-101', text: 'DOOR' }], records_total: 1, gates: [],
    model: 'm', code_sha: 'abc', created_at: '2026-10-28T09:10:00+00:00' },
  company: { id: 'c1', name: 'ACME BUILDERS' }, corrections_count: 2,
};
const v = C.answerRowView(row);
ok(v.id === 'al1' && v.question === 'door 101?' && v.answer === "3'-0\"", 'question and answer');
ok(v.company === 'ACME BUILDERS' && v.surfaceLabel === 'Group', 'company and surface');
ok(v.when === '2026-10-28 09:10 UTC' && v.build === 'm · abc', 'when and build');
ok(v.correctionsLabel === 'Marked wrong ×2', 'how many times marked wrong');
ok(C.answerRowView({ ...row, corrections_count: 0 }).correctionsLabel === '', 'none: no label');
ok(C.answerRowView(undefined).id === '' && C.answerRowView({}).records.length === 0,
  'any shape renders (never throws)');
const cv = C.correctionView({ id: 'k1', correct_answer: "3'-6\"", note: 'rev 2',
  ts: '2026-10-28T11:00:00+00:00' });
ok(cv.correct === "3'-6\"" && cv.note === 'rev 2' && cv.when === '2026-10-28 11:00 UTC',
  'a correction as text');
const sp = C.searchParams({ q: '  door ', surface: 'dm', offset: 25, limit: 25 });
ok(sp.q === 'door' && sp.surface === 'dm' && sp.offset === 25, 'search params');
ok(Object.keys(C.searchParams({})).length === 0, 'no filters: nothing sent');

console.log('\nthe form');
const FORM = read('src/components/MarkWrongForm.jsx');
ok(/const req = correctionRequest\(correct, note\);\s*if \(req\.error\) \{ setError\(req\.error\); return; \}/.test(FORM),
  'checks the correct answer before any request');
ok(/ownerAPI\.answerCorrect\(answerId, req\.body\)/.test(FORM), 'posts the checked body');
ok(/CORRECT ANSWER \(REQUIRED\)/.test(FORM) && /NOTE \(OPTIONAL\)/.test(FORM),
  'required and optional are labelled');
ok(/accessibilityLabel="Mark wrong"/.test(FORM), 'a Mark wrong button');
ok(!/[Nn]otify|send_whatsapp/.test(FORM), 'nothing notifies anyone');

console.log('\nthe screens');
const ANS = read('app/owner/answers.jsx');
ok(/isPlatformOperator\(user\)/.test(ANS) && /if \(!isOperator\) return;/.test(ANS),
  'Answers: fetches nothing for a non-operator');
ok(/Platform operator access required\./.test(ANS), 'Answers: shows the denial panel');
ok(/ownerAPI\.answers\(\s*searchParams\(/.test(ANS), 'Answers: searches with searchParams');
ok(/<MarkWrongForm answerId=\{ov\.id\}/.test(ANS), 'Answers: Mark wrong on an opened answer');
ok(/<OwnerNav\b/.test(ANS) && !/FloatingNav/.test(ANS), 'Answers: owner portal nav');
const REV = read('app/owner/review.jsx');
ok(/<MarkWrongForm answerId=\{ov\.answerLog\.id\}/.test(REV),
  'Review queue: Mark wrong on an item with an answer');
ok(/ownerAPI\.answer\(answerId\)/.test(REV), 'Review queue: loads the answer\'s corrections');
ok(/if \(openIdRef\.current === row\.id && got\.status === 'ok'/.test(REV),
  'Review queue: a late corrections response for a closed item is dropped');

const API = read('src/utils/api.js');
ok(/apiClient\.get\('\/api\/owner\/answers', \{ params \}\)/.test(API), 'api: GET /api/owner/answers');
ok(/\/api\/owner\/answers\/\$\{encodeURIComponent\(id\)\}\/corrections`, body\)/.test(API),
  'api: POST /api/owner/answers/{id}/corrections');
const SMOKE = read('scripts/smoke-mount.cjs');
const routes = SMOKE.slice(SMOKE.indexOf('const ROUTES = ['), SMOKE.indexOf('const MIME'));
ok(/'\/owner\/answers',/.test(routes), 'mounted by smoke-mount');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed) process.exit(1);
