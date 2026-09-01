/**
 * Two things on the CP's dashboard that were wrong on 2026-09-01.
 *
 * ── 1. A REASON THAT IS NOT A SENTENCE, GLUED TO THE NEXT CLAUSE ───────────
 *
 *   "A correction was filed by Michael Cespedes on 2026-08-14. Photo Review it
 *    and sign."
 *
 * "Photo" is the ENTIRE stored amendment_reason on that child — not a
 * truncation. The card interpolated it raw with no terminator:
 *
 *     `${lead} ${a.reason} Review it and sign.`
 *
 * so any reason without ending punctuation runs into the following sentence.
 * Every amendment filed before the readability rule can be a fragment like
 * this, and the four "1" reasons on 588 Thomas are the extreme case.
 *
 * THE FIX IS NOT TO PUNCTUATE IT. Appending a full stop to "Photo" would
 * present a fragment as though it were prose somebody wrote. It is QUOTED
 * instead — reported as the text that was recorded, which is what it is —
 * and the quoting makes it structurally impossible to run into the next
 * clause whatever it contains.
 *
 * ── 2. "DRAFT" OVER 33 SIGNED WORKERS ──────────────────────────────────────
 *
 *     logs.forEach(log => { logMap[log.log_type] = log; });
 *
 * LAST-WRITE-WINS on log_type. Subcontractor orientation files ONE DOCUMENT
 * PER WORKER, so 34 documents collapsed to whichever the array happened to end
 * with — and when that was an unsigned Angel Lopez amendment, the whole log
 * type read "Draft" over 33 signed workers. The endpoint sorts by `date`, so
 * within one date the winner is unspecified: the pill could differ between two
 * loads of the same data.
 *
 * IT IS NOT "ANY DRAFT EXISTS" AND MUST NOT BECOME THAT. An unsigned amendment
 * is an open CORRECTION on a filed record, not unfinished work — the record is
 * filed, and the stale-unsigned card is what surfaces the correction. Making
 * the pill read Draft would tell a CP his signed day is unfinished.
 *
 * So the pill asks: is every worker's CURRENT record filed? Chain heads, the
 * same rule the list uses.
 *
 * Run:  node src/utils/logbookStatusAndReason.test.cjs
 */
const fs = require('fs');
const path = require('path');
const babel = require('@babel/core');

const FRONTEND = path.join(__dirname, '..', '..');
const load = (rel) => {
  const p = path.join(FRONTEND, ...rel);
  const { code } = babel.transformSync(fs.readFileSync(p, 'utf8'), {
    filename: p,
    plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')],
    configFile: false,
    babelrc: false,
  });
  const mod = {};
  // eslint-disable-next-line no-new-func
  new Function('exports', 'module', 'require', code)(mod, { exports: mod }, require);
  return mod;
};

const M = load(['src', 'utils', 'amendmentChain.js']);
const SCREEN = fs.readFileSync(
  path.join(FRONTEND, 'app', 'logbooks', 'index.jsx'), 'utf8',
).split('\r\n').join('\n');

let failures = 0;
const ok = (c, m) => {
  if (c) { console.log(`  ok  ${m}`); } else { failures += 1; console.log(`FAIL  ${m}`); }
};

console.log('\n1. A FRAGMENT IS REPORTED, NOT GLUED');
{
  const line = M.amendmentSentence({
    by: 'Michael Cespedes', at: '2026-08-14',
    has_reason: true, reason: 'Photo',
  });
  ok(!/Photo Review/.test(line),
    'THE BUG: "Photo Review it and sign" cannot be produced');
  ok(/Photo/.test(line), 'the recorded text is still shown — it is the record');
  ok(/"Photo"|“Photo”/.test(line),
    'and is QUOTED, so a fragment reads as what was recorded rather than as '
    + 'prose somebody wrote');
  ok(/Review it and sign\.$/.test(line), 'the instruction still ends the line');

  const digit = M.amendmentSentence({
    by: 'Michael', at: '2026-08-31', has_reason: true, reason: '1',
  });
  ok(/"1"/.test(digit) && !/1 Review/.test(digit),
    'the four "1" reasons on 588 Thomas read as recorded text, not as prose');

  const sentence = M.amendmentSentence({
    by: 'Roy Fishman', at: '2026-08-31', has_reason: true,
    reason: 'This log listed every subcontractor twice.',
  });
  ok(/twice\."/.test(sentence) || /twice\."\s/.test(sentence),
    'a real sentence is quoted too — one rendering, not two');

  const none = M.amendmentSentence({ by: 'Roy', at: '2026-08-31', has_reason: false });
  ok(/No reason was recorded/.test(none) && /Review it and sign\.$/.test(none),
    'and a missing reason still says so');

  const bare = M.amendmentSentence(null);
  ok(/Review it and sign\.$/.test(bare), 'no amendment facts at all still guides him');
}

console.log('\n2. THE PILL ASKS WHETHER EVERY WORKER IS FILED');
{
  const doc = (over) => ({
    log_type: 'subcontractor_orientation',
    data: { worker_id: over.w },
    created_at: over.at, status: over.st || 'draft',
    cp_signature: over.st === 'submitted' ? { d: 'i' } : null,
    id: over.id,
  });

  // 33 signed workers, plus one worker whose record is signed and carries TWO
  // unsigned amendments — the Angel Lopez fork.
  const rows = [];
  for (let i = 0; i < 33; i += 1) {
    rows.push(doc({ id: `w${i}`, w: `W${i}`, at: '2026-08-31T12:00:00Z', st: 'submitted' }));
  }
  rows.push(doc({ id: 'a-parent', w: 'ANGEL', at: '2026-08-31T12:43:06Z', st: 'submitted' }));
  rows.push(doc({ id: 'a-d1', w: 'ANGEL', at: '2026-08-31T17:09:58Z' }));
  rows.push(doc({ id: 'a-d2', w: 'ANGEL', at: '2026-08-31T17:10:47Z' }));

  ok(M.logTypeStatus(rows) === 'submitted',
    'THE BUG: 33 signed workers plus an open correction reads DONE, not Draft');

  const heads = M.collapseChains(rows);
  ok(heads.length === 34, 'and the collapse still sees 34 workers, not 36 rows');

  const withUnfinished = rows.concat(
    doc({ id: 'w99', w: 'W99', at: '2026-08-31T12:00:00Z' }),
  );
  ok(M.logTypeStatus(withUnfinished) === 'draft',
    'a worker whose record was NEVER filed still reads Draft — real unfinished '
    + 'work is not hidden');

  ok(M.logTypeStatus([]) === 'pending', 'nothing filed at all is pending');
  ok(M.logTypeStatus(null) === 'pending', 'and a missing list is pending');

  const single = [doc({ id: 'x', w: 'W1', at: '2026-08-31T12:00:00Z', st: 'submitted' })];
  ok(M.logTypeStatus(single) === 'submitted', 'the ordinary one-document case');
}

console.log('\n3. THE SCREEN USES IT, AND THE LAST-WRITE-WINS MAP IS GONE');
{
  ok(!/logMap\[log\.log_type\] = log;/.test(SCREEN),
    'the last-write-wins assignment is removed');
  ok(/logTypeStatus/.test(SCREEN), 'the screen asks the shared rule');
  ok(/amendmentSentence/.test(SCREEN),
    'and renders the reason through the shared renderer, not its own template');
  ok(!/\$\{lead\} \$\{a\.reason\}/.test(SCREEN),
    'the raw interpolation that produced "Photo Review it" is gone');

  // THE SHAPE CHANGED, SO EVERY READER OF IT HAD TO BE FOUND. todayLogs holds
  // a LIST per type now; the toolbox banner read `.status` off it and would
  // have been silently always false.
  ok(!/logMap\['toolbox_talk'\]\?\.status/.test(SCREEN),
    'the toolbox reader no longer reads .status off what is now an array');
  ok(/logTypeStatus\(logMap\['toolbox_talk'\]\)/.test(SCREEN),
    'and asks the same shared rule instead');
}

console.log(`\n${failures === 0 ? 'ALL PASS' : `${failures} FAILURE(S)`}\n`);
process.exit(failures === 0 ? 0 : 1);
