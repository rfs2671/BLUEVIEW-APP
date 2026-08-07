/**
 * Operator ruling: "An unfilled admin form must never stop a man from working."
 *
 * With an EMPTY project roster (no trade_assignments) the worker must still be
 * able to complete check-in — the backend admits them and flags the row
 * needs_trade_assignment. The CLIENT must therefore not block before the
 * request is ever sent. With a roster PRESENT nothing changes: the strict
 * (trade, company) match stays required and a non-roster pair is still refused.
 *
 * Static guard over the two shipped client surfaces:
 *   frontend/app/checkin/[project_id]/[tag_id].jsx  (Expo screen)
 *   backend/checkin.html                            (server-rendered gate page)
 *
 * Following the checkinRosterKey.test.cjs harness: read the REAL sources,
 * extract the guards VERBATIM with balanced-brace matching, and assert over
 * them. If a guard's shape changes, extraction tracks it or throws loudly.
 *
 * Run:  node src/utils/checkinEmptyRoster.test.cjs
 */

const fs = require('fs');
const path = require('path');

const repo = path.join(__dirname, '..', '..', '..');
const jsxPath = path.join(repo, 'frontend', 'app', 'checkin', '[project_id]', '[tag_id].jsx');
const htmlPath = path.join(repo, 'backend', 'checkin.html');
const jsx = fs.readFileSync(jsxPath, 'utf8');
const html = fs.readFileSync(htmlPath, 'utf8');

let passed = 0;
let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

function matchBalanced(text, openIdx, open, close) {
  let depth = 0;
  for (let i = openIdx; i < text.length; i += 1) {
    if (text[i] === open) depth += 1;
    else if (text[i] === close) {
      depth -= 1;
      if (depth === 0) return i;
    }
  }
  throw new Error('unbalanced region');
}

// Slice a named function/handler body out of a source file.
function bodyOf(src, anchor, label) {
  const at = src.indexOf(anchor);
  if (at < 0) throw new Error(`${label}: anchor not found -> ${anchor}`);
  const braceOpen = src.indexOf('{', at);
  return src.slice(braceOpen, matchBalanced(src, braceOpen, '{', '}') + 1);
}

// ===================================================================
// A. Expo screen — app/checkin/[project_id]/[tag_id].jsx
// ===================================================================
const handler = bodyOf(jsx, 'const handleCheckIn = async () =>', 'jsx handleCheckIn');

// The roster is still read from projectInfo (not silently dropped).
ok(/const assignments = projectInfo\?\.trade_assignments \|\| \[\];/.test(handler),
  'jsx: roster still sourced from projectInfo.trade_assignments');

// The whole trade/company block must live inside a roster-configured branch.
const branchAnchor = 'if (assignments.length > 0)';
ok(handler.indexOf(branchAnchor) >= 0,
  'jsx: trade/company guards are gated on a configured roster');
const branch = bodyOf(handler, branchAnchor, 'jsx roster branch');

// Populated roster: every guard is INSIDE the branch and therefore still runs.
ok(/assignments\.some\(/.test(branch),
  'jsx: strict roster match still present (populated roster)');
ok(/'Invalid Selection'/.test(branch) && /'Please pick from the dropdown'/.test(branch),
  'jsx: "Invalid Selection" guard still fires for a non-roster pair');
ok(/'Please select your trade & company'/.test(branch),
  'jsx: trade+company still required when the roster is populated');

// Empty roster: NO roster guard survives outside the branch, so nothing between
// the roster read and the POST can block.
const outsideBranch = handler.replace(branch, '');
ok(!/assignments\.some\(/.test(outsideBranch),
  'jsx: no roster-match guard outside the roster-configured branch');
ok(!/Invalid Selection/.test(outsideBranch),
  'jsx: no "Invalid Selection" block on the empty-roster path');
ok(!/select your trade & company'\s*\);/.test(outsideBranch),
  'jsx: no trade/company "Required" toast on the empty-roster path');

// Empty roster: submit is still reached (the POST is not inside the branch).
ok(/apiClient\.post\('\/api\/checkin\/submit'/.test(outsideBranch),
  'jsx: /api/checkin/submit is reached on the empty-roster path');

// Guards that must NOT have been relaxed for anyone.
ok(/!workerName\.trim\(\)/.test(outsideBranch) && /!workerPhone\.trim\(\)/.test(outsideBranch),
  'jsx: name + phone still required on every path');
ok(/phoneRegex\.test\(cleanPhone\)/.test(outsideBranch),
  'jsx: phone-format validation still runs on every path');

// Behavioural check over the VERBATIM extracted match predicate. Reconstructs
// the shipped nesting: blocked === roster configured AND no pair matches.
const someAt = branch.indexOf('assignments.some(');
const someOpen = branch.indexOf('(', someAt);
const predSrc = branch.slice(someAt, matchBalanced(branch, someOpen, '(', ')') + 1);
if (!/\.toLowerCase\(\)/.test(predSrc)) {
  throw new Error('jsx match predicate no longer case-normalizing — update this test intentionally');
}
// eslint-disable-next-line no-new-func
const buildMatch = new Function('assignments', 'workerTrade', 'workerCompany', `return ${predSrc};`);
function blocked(assignments, trade, company) {
  return assignments.length > 0 && !buildMatch(assignments, trade, company);
}
const ROSTER = [{ trade: 'Concrete', company: 'AAZ' }];

ok(blocked([], 'anything', 'anything') === false,
  'jsx behaviour: EMPTY roster -> never blocked (ruling honoured)');
ok(blocked([], '', '') === false,
  'jsx behaviour: EMPTY roster + nothing picked -> still not blocked');
ok(blocked(ROSTER, 'Concrete', 'AAZ') === false,
  'jsx behaviour: populated roster + on-roster pair -> admitted');
ok(blocked(ROSTER, 'concrete', '  aaz ') === false,
  'jsx behaviour: populated roster + case/space variant -> admitted');
ok(blocked(ROSTER, 'Plumbing', 'Someone Else') === true,
  'jsx behaviour: populated roster + off-roster pair -> STILL blocked');
ok(blocked(ROSTER, '', '') === true,
  'jsx behaviour: populated roster + no pick -> STILL blocked');

// The empty-state copy must not send the worker away to find an admin.
ok(/you can\s*\n?\s*still check in/i.test(jsx) || /still check in/i.test(jsx),
  'jsx: empty-roster picker copy tells the worker they can still check in');

// ===================================================================
// B. Gate page — backend/checkin.html
// ===================================================================
const loadRoster = bodyOf(html, 'function loadTradeAssignments()', 'html loadTradeAssignments');
ok(/if \(!tradeAssignments\.length\)/.test(loadRoster) && /noTradesConfigured = true/.test(loadRoster),
  'html: empty roster sets noTradesConfigured');
ok(/nextBtn\.disabled = false;/.test(loadRoster) && !/nextBtn\.disabled = true/.test(loadRoster),
  'html: empty roster never disables Next (was a hard block)');
ok(/noTradesConfigured = false/.test(loadRoster),
  'html: a populated roster clears the flag (strict path re-armed)');

// Both step-nav and submit gate the roster requirement on noTradesConfigured.
const goStep = bodyOf(html, 'function goStep(step)', 'html goStep');
ok(/if \(!noTradesConfigured && !assignment\)/.test(goStep),
  'html goStep: roster pick required ONLY when trades are configured');
const submitReg = bodyOf(html, 'async function submitRegistration()', 'html submitRegistration');
ok(/if \(!noTradesConfigured && !assignment\)/.test(submitReg),
  'html submitRegistration: roster pick required ONLY when trades are configured');
ok(/api\('\/checkin\/register-and-checkin'/.test(submitReg),
  'html submitRegistration: still reaches register-and-checkin');
ok(/trade_not_listed: notListed/.test(submitReg),
  'html submitRegistration: unassigned flag still sent to the backend');

// Returning worker: the re-prompt only applies when there IS a roster to be off.
const quick = bodyOf(html, 'async function quickCheckIn()', 'html quickCheckIn');
ok(/if \(tradeAssignments\.length\)/.test(quick) && /stillOnRoster/.test(quick),
  'html quickCheckIn: stillOnRoster re-prompt is gated on a non-empty roster');
const quickBranch = bodyOf(quick, 'if (tradeAssignments.length)', 'html quickCheckIn roster branch');
ok(/if \(!stillOnRoster\)/.test(quickBranch),
  'html quickCheckIn: off-roster returning worker is still re-prompted (populated roster)');
ok(!/stillOnRoster/.test(quick.replace(quickBranch, '')),
  'html quickCheckIn: no roster re-prompt on the empty-roster path');

// Roster order must survive: the <select> resolves by ARRAY INDEX.
ok(/opt\.value = String\(i\);/.test(loadRoster) && !/\.sort\(|\.filter\(/.test(loadRoster),
  'html: roster rendered by array index, not reordered or filtered');

// ===================================================================
// C. Bilingual — every user-facing empty-roster string in BOTH en and es
// ===================================================================
const tAt = html.indexOf('const TRANSLATIONS = {');
if (tAt < 0) throw new Error('TRANSLATIONS map not found in checkin.html');
const tOpen = html.indexOf('{', tAt);
const tMap = html.slice(tOpen, matchBalanced(html, tOpen, '{', '}') + 1);
const enAt = tMap.indexOf('en: {');
const esAt = tMap.indexOf('es: {');
if (enAt < 0 || esAt < 0) throw new Error('en/es sections not found in TRANSLATIONS');
const enBlock = tMap.slice(enAt, matchBalanced(tMap, tMap.indexOf('{', enAt), '{', '}') + 1);
const esBlock = tMap.slice(esAt, matchBalanced(tMap, tMap.indexOf('{', esAt), '{', '}') + 1);
ok(enBlock.length > 100 && esBlock.length > 100 && !enBlock.includes('es: {'),
  'html: en and es translation blocks extracted cleanly');

// Every data-i18n key the page renders must resolve in BOTH languages —
// this is what stops an English-only string reaching a Spanish-speaking worker.
const usedKeys = [...html.matchAll(/data-i18n(?:-placeholder)?="([A-Za-z0-9_]+)"/g)]
  .map((m) => m[1]);
ok(usedKeys.includes('noTradesProceed'),
  'html: the empty-roster notice is rendered from a translation key');
const missingEn = [...new Set(usedKeys)].filter((k) => !new RegExp(`(^|\\s)${k}:`, 'm').test(enBlock));
const missingEs = [...new Set(usedKeys)].filter((k) => !new RegExp(`(^|\\s)${k}:`, 'm').test(esBlock));
ok(missingEn.length === 0, `html: every rendered data-i18n key exists in en (${missingEn.join(', ') || 'none missing'})`);
ok(missingEs.length === 0, `html: every rendered data-i18n key exists in es (${missingEs.join(', ') || 'none missing'})`);

// The empty-roster / unassigned strings specifically, in both maps.
['noTradesProceed', 'notListed', 'selectTradeCompanyErr', 'selectTradeCompany'].forEach((k) => {
  ok(new RegExp(`(^|\\s)${k}:`, 'm').test(enBlock) && new RegExp(`(^|\\s)${k}:`, 'm').test(esBlock),
    `html: "${k}" present in BOTH en and es`);
});
ok(!/noTradesProceed:\s*'No trades are set up yet/.test(esBlock),
  'html: the es empty-roster notice is actually Spanish (not an en copy)');

// Recently-merged neighbours must be untouched.
['displayCrop', 'connectionErrorHint', 'tbtBoxRet', 'tbtBoxReg'].forEach((marker) => {
  ok(html.includes(marker), `html: pre-existing marker "${marker}" still present`);
});

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
