/**
 * A DRAFT THE RETIRED SCREENS LEFT BEHIND MUST BE SURFACED ONCE, AND ONCE ONLY.
 *
 * The two legacy daily-log editors are gone. They wrote drafts to the device
 * and promised an offline save would sync on reconnect; draftSync refuses those
 * types outright, so it never did. The bytes survived -- the refusal never
 * cleared the pending key -- and there is NO SERVER-SIDE TRACE of one, so the
 * device is the only place that can ask whether any exist.
 *
 * The selection rule and the wording are pure, which is why they can be tested
 * here at all, and why the component is a shell over them.
 *
 * Run:  node src/utils/unfiledDailyLogs.test.cjs
 */

const fs = require('fs');
const path = require('path');
const babel = require('@babel/core');

let passed = 0;
let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

const FILE = path.join(__dirname, 'unfiledDailyLogs.js');
const M = (() => {
  const { code } = babel.transformSync(fs.readFileSync(FILE, 'utf8'), {
    filename: FILE,
    plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')],
    configFile: false, babelrc: false,
  });
  const m = {};
  // eslint-disable-next-line no-new-func
  new Function('exports', 'module', 'require', code)(m, { exports: m }, require);
  return m;
})();

const K_OLD = 'logbook_draft:proj1:daily_log:2026-04-14';
const K_SITE = 'logbook_draft:proj2:site_daily_log:2026-04-02';
const K_LIVE = 'logbook_draft:proj1:daily_jobsite:2026-09-10';

// ── export check, so a tree without the module names what is absent ────────
for (const n of ['unfiledDrafts', 'noticeText', 'formatDraftDate', 'draftLines',
                 'parseKey', 'RETIRED_LOG_TYPES', 'DISMISSED_KEY']) {
  ok(typeof M[n] !== 'undefined', `unfiledDailyLogs exports ${n}`);
}

// ── 1. WHICH DRAFTS ────────────────────────────────────────────────────────
{
  const got = M.unfiledDrafts([K_LIVE, K_OLD, K_SITE], []);
  ok(got.length === 2, 'both retired types are surfaced');
  ok(!got.some((d) => d.logType === 'daily_jobsite'),
     'a LIVE logbook draft is never surfaced — it syncs on its own');
  ok(got[0].date === '2026-04-02',
     'oldest first: the one he is least likely to remember comes first');
}

// ── 2. ONCE, AND ONCE ONLY ─────────────────────────────────────────────────
{
  ok(M.unfiledDrafts([K_OLD], [K_OLD]).length === 0,
     'a dismissed draft never returns');
  ok(M.unfiledDrafts([K_OLD, K_OLD], []).length === 1,
     'a key listed twice is surfaced once');
  ok(M.unfiledDrafts([K_OLD], [K_SITE]).length === 1,
     'dismissing ONE site does not silence the other — he has two jobs');
}

// ── 3. IT NEVER THROWS ON RUBBISH ──────────────────────────────────────────
{
  ok(M.unfiledDrafts(null, null).length === 0, 'no pending list is not a crash');
  ok(M.unfiledDrafts(['', 'nonsense', 'logbook_draft:only:two'], []).length === 0,
     'an unparseable key is skipped, not surfaced');
}

// ── 4. THE WORDING, WHICH IS THE POINT ─────────────────────────────────────
{
  const t = M.noticeText({ projectName: '588 Thomas', date: '2026-04-14' });

  ok(t.body.indexOf('588 Thomas') < t.body.indexOf('never reached'),
     'the FACT comes before the FAILURE — he did nothing wrong');
  ok(t.body.includes('588 Thomas') && t.body.includes('14 April 2026'),
     'the project and the date are in the first line — he may have two jobs');
  ok(t.body.includes('Nothing has been lost'),
     'the question he will actually have is answered, not buried');
  ok(t.body.indexOf('Nothing has been lost') < t.body.indexOf('cannot be moved'),
     '"nothing has been lost" lands BEFORE the bad news about re-entering');
  ok(t.body.includes('cannot be moved'),
     'it says plainly it cannot be moved for him, rather than implying one tap');
  ok(t.actions[0] === 'Read what I saved',
     'READ IS FIRST and not optional: without it "enter it in Log Books" is an '
     + 'instruction he cannot follow, the content being only in the draft');
  ok(!/error|failed|problem|sorry/i.test(t.title + t.body),
     'it does not read as an error — nothing here is his fault');

  const anon = M.noticeText({ projectName: '', date: '2026-04-14' });
  ok(anon.body.includes('a project on this device'),
     'an unknown project degrades to a phrase, never to "undefined"');
}

// ── 5. THE DATE ────────────────────────────────────────────────────────────
{
  ok(M.formatDraftDate('2026-04-14') === '14 April 2026', 'a stored date reads plainly');
  ok(M.formatDraftDate('2026-04-02') === '2 April 2026', 'no leading zero on the day');
  ok(M.formatDraftDate('rubbish') === 'rubbish', 'an unparseable date is passed through');
  ok(M.formatDraftDate('2026-13-01') === '2026-13-01', 'an impossible month is not invented');
}

// ── 6. WHAT HE SAVED ───────────────────────────────────────────────────────
{
  const lines = M.draftLines({
    data: {
      work_performed: 'Framing on 1 and 2', notes: '', worker_count: 11,
      corrective_actions_na: false, incident_log_na: true,
      subcontractor_cards: [{ a: 1 }, { a: 2 }],
      competent_person_signature: { paths: [[1, 2]] },
    },
  });
  const flat = Object.fromEntries(lines);
  ok(flat['Work performed'] === 'Framing on 1 and 2', 'his own words come back');
  ok(flat['Worker count'] === '11', 'a number is shown, not dropped as falsy');
  ok(!('Notes' in flat), 'an empty field is not shown as empty');
  ok(!('Corrective actions na' in flat), 'an unset flag is not shown');
  ok(flat['Incident log na'] === 'true', 'a SET flag is shown');
  ok(flat['Subcontractor cards'] === '2 entries', 'a list is counted, not drawn');
  ok(flat['Competent person signature'] === 'recorded',
     'a signature is reported as present rather than invented on screen');
  ok(M.draftLines(null).length === 0, 'a missing draft is not a crash');
}

console.log(`\n  ${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
