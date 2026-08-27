/**
 * A valid-but-wrong trade can be corrected, and the sheet cannot be dirtied.
 *
 * THE GAP WAS UI ONLY. POST /checkins/{id}/assign-trade already validates the
 * pair against the roster, rewrites trade/company/worker_trade/worker_company,
 * clears needs_trade_assignment, stamps trade_assigned_by/_by_name/_at,
 * rewrites the worker_project_trades pairing and writes an audit_log. Nothing
 * in it requires the check-in to be unassigned.
 *
 * buildFlagMap gated on `if (!sst && !needsTrade) continue`, so a row only
 * appeared when something was WRONG with it. A worker who picked a VALID roster
 * entry that was simply the WRONG one had no flag, no row, and no route -- the
 * pairing was fixed by hand in mongosh twice this week.
 *
 * ── THE CRITICAL QUESTION: CAN A TAP DIRTY A SIGNED LOGBOOK? ──────────────
 *
 * This screen feeds a filed record, and daily_jobsite had exactly that defect:
 * hydrate() set fourteen fields, all of them in the autosave deps, with no
 * dirty tracking, and a filed log was overwritten BY BEING VIEWED.
 *
 * Here it cannot happen, for three independent reasons, each asserted below:
 *
 *   1. FLAGS ARE NOT WORKERS. buildFlagMap writes `flags`, and the autosave
 *      effect depends on `workers`. The screen's own comment states the rule:
 *      "Result goes into `flags`, never into `workers`." Opening the picker
 *      sets `tradePickerFor` / `pendingTrade` -- neither is an autosave dep.
 *
 *   2. THE AUTOSAVE NEVER REACHES THE SERVER. It calls writeDraft only, with
 *      `status` omitted so it cannot downgrade a submitted log, and the key is
 *      marked pending only on an explicit submit.
 *
 *   3. A FILED SHEET IS FINALIZED. chooseEditableLog returns readOnly for a
 *      submitted log, the screen calls setLocked(true) AND markFinalized(), and
 *      writeDraft refuses to edit a finalized draft's content. That is #215's
 *      fix, and it is what daily_jobsite lacked.
 *
 * ONE PATH DOES WRITE, DELIBERATELY AND ONLY ON SUCCESS: completing an
 * assignment calls updateWorker(index, 'company', res.company), correcting an
 * EXISTING logbook field from the server's response. That is pre-existing,
 * intentional, and local-only.
 *
 *   node frontend/src/utils/tradeCorrectionUI.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
const SCREEN = path.join(FRONTEND, 'app', 'logbooks', 'preshift_signin.jsx');

let passed = 0;
let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log('  PASS ', label); } else { failed += 1; console.log('  FAIL ', label); }
}

const raw = fs.readFileSync(SCREEN, 'utf8');
// COMMENTS STRIPPED. The new comments quote the removed gate and the words
// "corrected"/"fixed" while explaining why they are banned -- an unstripped
// source matches the explanation instead of the code.
const src = raw
  .replace(/\{\s*\/\*[\s\S]*?\*\/\s*\}/g, '')
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/(?<!:)\/\/.*$/gm, '');

console.log('\n-- the gate is lifted --');
{
  ok(!/if \(!sst && !needsTrade\) continue;/.test(src),
    'the flag gate is gone. It made a row appear only when something was '
    + 'WRONG with it, so a valid-but-wrong trade had no route');
  ok(/const needsTrade = !!c\.needs_trade_assignment;/.test(src),
    'needsTrade is still computed — it drives the WARNING, not reachability');
  ok(/f\.needs_trade \?/.test(src),
    'and the warning is now a conditional inside the row, not a gate on it');
  ok(/'Assign Trade' : 'Change Trade'|\{f\.needs_trade \? 'Assign Trade' : 'Change Trade'\}/.test(src)
    || /Change Trade/.test(src),
    'a row with a trade offers Change Trade rather than nothing');
}

console.log('\n-- flags never become workers --');
{
  const i = src.indexOf('const buildFlagMap');
  ok(i > -1, 'buildFlagMap exists');
  const body = src.slice(i, src.indexOf('const setFlag', i));
  ok(!/setWorkers/.test(body),
    'THE INVARIANT. buildFlagMap writes flags and never workers — the autosave '
    + 'effect depends on `workers`, so this is what makes a tap safe');
  ok(/setFlags\(map\)/.test(body), 'it writes setFlags');
  ok(/current_trade:/.test(body) && /current_company:/.test(body),
    'the current pairing rides on the FLAG entry, read-only, so showing what a '
    + 'row is being changed from cannot dirty the sheet either');
}

console.log('\n-- opening the picker cannot trigger an autosave --');
{
  // The autosave dependency array is the thing that decides this.
  const m = raw.match(/\}, \[loading, projectId, date, company, projectLocation, workers, cpSignature, cpName\]\);/);
  ok(!!m, 'the autosave deps are the known list');
  const deps = m ? m[0] : '';
  for (const state of ['tradePickerFor', 'pendingTrade', 'flags', 'priorCounts']) {
    ok(!deps.includes(state),
      `${state} is NOT an autosave dependency — changing it writes nothing`);
  }
  ok(/onPress=\{\(\) => setTradePickerFor\(key\)\}/.test(src),
    'the tap that opens the picker only sets tradePickerFor');
  ok(/onPress=\{\(\) => setPendingTrade\(\{ workerKey: key, index, assignment: a \}\)\}/.test(src),
    'and choosing an option only stages a confirm — it does not write');
}

console.log('\n-- the autosave cannot reach the server --');
{
  const i = src.indexOf('const t = setTimeout(');
  const body = src.slice(i, src.indexOf('}, 700);', i));
  ok(/writeDraft\(/.test(body), 'the autosave writes a LOCAL draft');
  ok(!/logbooksAPI/.test(body),
    'and makes no server call — the daily_jobsite overwrite went out through '
    + 'the drain, which only replays keys marked pending');
  ok(!/markPending/.test(body),
    'it does not mark the key pending, so a drain has nothing to push');
  ok(!/status:/.test(body),
    '`status` is omitted, so an autosave can never downgrade a submitted log');
}

console.log('\n-- a filed sheet is locked AND finalized --');
{
  ok(/chooseEditableLog\(/.test(src),
    'the shared openness rule decides whether this sheet is editable');
  ok(/if \(readOnly\) \{[\s\S]{0,200}setLocked\(true\)/.test(src)
    || /setLocked\(true\);[\s\S]{0,120}markFinalized\(/.test(src),
    'a filed sheet sets locked');
  ok((src.match(/markFinalized\(/g) || []).length >= 2,
    'AND marks the local draft finalized — writeDraft then refuses to edit its '
    + 'content, which is the protection daily_jobsite did not have (#215)');

  const drafts = fs.readFileSync(
    path.join(FRONTEND, 'src', 'utils', 'logbookDrafts.js'), 'utf8');
  ok(/finalized/.test(drafts), 'and logbookDrafts still enforces it');
}

console.log('\n-- the one deliberate write, and only on success --');
{
  const i = src.indexOf('const handleAssignTrade');
  const body = src.slice(i, src.indexOf('const updateWorker', i));
  ok(/updateWorker\(index, 'company', res\.company\)/.test(body),
    'completing an assignment corrects the roster row\'s company from the '
    + 'SERVER response — pre-existing and intentional');
  ok(body.indexOf('await checkinsAPI.assignTrade') < body.indexOf('updateWorker('),
    'and it happens AFTER the server confirms, never before');
  ok(/catch \(e\) \{[\s\S]{0,400}toast\.error/.test(body),
    'a failure writes nothing and says so — the picker stays open');
}

console.log('\n-- the confirm step names what is NOT changing --');
{
  ok(/pendingTrade\?\.workerKey === key \?/.test(src),
    'a confirm step renders before the write');
  ok(/tradeChangeCaveat\(key\)/.test(src),
    'and it carries the caveat');

  const i = src.indexOf('const tradeChangeCaveat');
  const fn = src.slice(i, src.indexOf('const handleAssignTrade', i));
  ok(/priorCounts\[workerKey\]/.test(fn),
    'the count comes from the SERVER (prior_checkin_counts), not from a client '
    + 'guess');
  // SPLIT ACROSS TWO TEMPLATE LITERALS -- `...${n} earlier ` + `check-in${...}`
  // -- so the phrase never appears contiguously in the source. Asserting the
  // rendered sentence rather than the source spelling.
  ok(/\$\{n\} earlier /.test(fn) && /check-in\$\{n === 1/.test(fn),
    'it names earlier check-ins, with the count and correct pluralisation');
  ok(/any filed logs keep what they recorded/.test(fn),
    'and filed logs, without a number — a preshift sheet keys its roster by '
    + 'name, an orientation by worker_id, so one count would be wrong for two '
    + 'of the three');
  ok(/Future check-ins on this project will use it/.test(fn),
    'and says what DOES change');
}

console.log('\n-- never "corrected", never "fixed" --');
{
  // User-visible strings only: the words appear in comments explaining the ban.
  const strings = (src.match(/'[^']{8,}'|`[^`]{8,}`/g) || []).join(' ');
  ok(!/\bcorrected\b/i.test(strings),
    'no user-visible copy says "corrected" — it is not retroactive');
  ok(!/\bfixed\b/i.test(strings), 'nor "fixed"');
  ok(/'Trade updated'/.test(src),
    'the success title is "Trade updated"');
}

console.log('\n-- the server half --');
{
  const server = fs.readFileSync(path.join(FRONTEND, '..', 'backend', 'server.py'), 'utf8');
  ok(/"prior_checkin_counts": prior_checkins/.test(server),
    'the flagged endpoint returns the per-worker count');
  ok(/db\.checkins\.aggregate\(/.test(server),
    'computed as ONE aggregate — a lookup per row would be an N+1 on a screen '
    + 'a CP opens every morning');
  ok(/max\(0, int\(_row\.get\("n"\) or 0\) - 1\)/.test(server),
    'minus the row being corrected, which is itself a check-in');
  ok(/prior_checkins = \{\}/.test(server),
    'and a failure yields no counts rather than blocking — never a reason a CP '
    + 'cannot fix a trade');
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
