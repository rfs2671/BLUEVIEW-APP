/**
 * The admin picks a trade. He does not type one by accident.
 *
 * THE DEFECT. The roster editor's trade control was a plain TextInput with a
 * filtered suggestion list that merely FILLED IT IN — `pickSuggestion` set the
 * text and nothing validated it. `TradeAssignment.trade` was a bare `str`
 * server-side. So whatever an admin typed was stored, and "Framers" reached
 * production while a twenty-entry list sat in this same file.
 *
 * That list was a SECOND COPY of the server's DEFAULT_TRADES — twenty identical
 * strings in two files, and between them they validated nothing. The server
 * owns the list now; this screen fetches it.
 *
 * WHAT MUST STAY TRUE, and each is asserted below:
 *
 *   The picker is a picker. No free-text path to a stored trade except the
 *   explicit one.
 *
 *   "Add a trade not on the list" REMAINS. A fixed list always lags a live
 *   jobsite, and removing the escape hatch would push every off-list crew to
 *   "My company isn't listed" at the gate — turning one admin inconvenience
 *   into a daily CP burden.
 *
 *   It requires an EXPLICIT step. An admin going off-vocabulary must know he
 *   did. `customMode` is entered by tapping that item, never by typing.
 *
 *   A custom value shows back as CHOSEN. Reopening a row whose trade is off the
 *   list must not blank the field — that turns "we do not recognise this" into
 *   "you never entered anything".
 *
 *   node frontend/src/utils/tradeVocabularyPicker.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
const SCREEN = path.join(FRONTEND, 'app', 'project', '[id]', 'trades.jsx');

let passed = 0;
let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log('  PASS ', label); } else { failed += 1; console.log('  FAIL ', label); }
}

const raw = fs.readFileSync(SCREEN, 'utf8');
// COMMENTS STRIPPED. This file's own prose — and the screen's — name the very
// identifiers being asserted absent. An unstripped source matches the
// explanation instead of the code, which is the trap this project keeps hitting.
const src = raw
  .replace(/\{\s*\/\*[\s\S]*?\*\/\s*\}/g, '')
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/(?<!:)\/\/.*$/gm, '');

console.log('\n-- one source of truth --');
{
  ok(!/const TRADE_SUGGESTIONS/.test(src),
    'the screen carries no local copy of the list');
  ok(/tradesAPI/.test(src) && /getVocabulary\(\)/.test(src),
    'it FETCHES the vocabulary instead');
  ok(/setVocabulary\(/.test(src) && /vocabulary\.map\(/.test(src),
    'and the picker renders what it fetched, not a constant');

  const api = fs.readFileSync(path.join(FRONTEND, 'src', 'utils', 'api.js'), 'utf8');
  ok(/\/api\/trades\/vocabulary/.test(api), 'the API client names the endpoint');
  ok(/deprecated/.test(api),
    'and carries `deprecated` through — those labels stay valid on existing '
    + 'rows and must never be re-spelled');
}

console.log('\n-- the trade control is a picker --');
{
  const i = src.indexOf('addLabel}>TRADE');
  ok(i > -1, 'the TRADE field exists');
  const field = src.slice(i, src.indexOf('addLabel}>COMPANY', i));

  ok(/onPress=\{\(\) => setShowSuggest/.test(field),
    'the closed control is a Pressable that opens the list, not a text box');
  ok(/customMode \?/.test(field),
    'and free-text is reachable ONLY through customMode');
  ok(!/onChangeText=\{setNewTrade\}[\s\S]{0,400}onFocus=\{\(\) => setShowSuggest\(true\)\}/.test(field),
    'the old shape is gone — a TextInput whose suggestion list merely filled '
    + 'it in, so anything typed was stored');
}

console.log('\n-- the escape hatch remains, and is explicit --');
{
  ok(/setCustomMode\(true\)/.test(src),
    'there IS a way to add an off-list trade. Removing it would push every '
    + 'off-list crew to "My company isn\'t listed" at the gate');
  ok(/Add a trade not on the list/.test(src),
    'and it says plainly what it is');

  // The only writer of customMode(true) must be that control's onPress.
  const enters = src.match(/setCustomMode\(true\)/g) || [];
  ok(enters.length === 1,
    'exactly ONE path enters custom mode — an admin cannot arrive there by '
    + 'mistyping');
  ok(/onPress=\{\(\) => \{ setCustomMode\(true\)/.test(src),
    'and that path is a deliberate tap');
}

console.log('\n-- a custom value is shown back as chosen --');
{
  ok(/newTrade \|\| 'Select a trade'/.test(src),
    'the picker renders whatever the value is, vocabulary or not — it never '
    + 'blanks an unrecognised trade');
  ok(/!isVocabularyTrade\(newTrade\)/.test(src),
    'and labels it rather than dropping it');
  ok(/Custom trade/.test(src), 'in words the admin can act on');
}

console.log('\n-- the off-vocabulary count is surfaced --');
{
  ok(/offVocabularyCount/.test(src), 'the screen counts off-list rows');
  ok(/not on the standard list/.test(src),
    'and says so — this is how the vocabulary earns its next entries');
  ok(/visibleAssignments\.filter\(/.test(src)
    && /offVocabularyCount = visibleAssignments/.test(src),
    'counted over VISIBLE rows, so a soft-deleted crew is not reported as a '
    + 'problem an admin has to solve');
}

console.log('\n-- the match rule agrees with the server --');
{
  ok(/\.trim\(\)\.toLowerCase\(\)/.test(src),
    'rosterKey mirrors _roster_key (strip + casefold). The server is '
    + 'authoritative; this copy only decides what the screen SAYS');
  ok(/deprecatedTrades/.test(src) && /\.\.\.vocabulary, \.\.\.deprecatedTrades/.test(src),
    'DEPRECATED LABELS COUNT AS KNOWN. They were published, so a row carrying '
    + 'one is history — flagging it custom would tell an admin to fix '
    + 'something already correct');

  const server = fs.readFileSync(path.join(FRONTEND, '..', 'backend', 'server.py'), 'utf8');
  ok(/def _trade_source\(trade\) -> str:/.test(server),
    'and the server owns the real predicate');
}

console.log('\n-- a failed fetch does not stop an admin working --');
{
  // Asserted against RAW, and anchored to the call. The comment-strip above
  // collapses `{ /* ... */ }` -- an empty catch body with an explanation in it
  // looks exactly like a JSX comment -- so the stripped source loses the very
  // thing under test. A regex anchored on getVocabulary cannot match prose.
  ok(/getVocabulary\(\)[\s\S]{0,800}\.catch\(/.test(raw),
    'the vocabulary fetch is non-fatal. An admin on a site at 6am must not be '
    + 'blocked from adding a crew because a list did not load');
  ok(/setVocabulary\(v\.trades\)/.test(raw),
    'and the success path takes the server list verbatim');
}

console.log('\n-- the header comment names both actors --');
{
  // Read the RAW source: this assertion is about the comment.
  const header = raw.slice(0, raw.indexOf('export default function'));
  ok(/THE WORKER/.test(header) && /THE ADMIN/.test(header),
    'the header distinguishes them. It used to end "No free-text" — true of '
    + 'the worker, false of the admin, sitting directly above the admin\'s '
    + 'free-text input');
  ok(!/`company` fields get populated from it\. No free-text\./.test(header),
    'the unqualified claim is gone');
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
