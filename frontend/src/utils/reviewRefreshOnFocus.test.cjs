/**
 * THE REVIEW SCREEN MUST RE-ASK THE SERVER WHEN IT REGAINS FOCUS.
 *
 * Reported from a real phone: approving a flagged worker left him on the list.
 * Navigating away and back did not clear him. Only a full app force-close did,
 * so a CP would approve the same man repeatedly believing it had failed.
 *
 * THREE FACTS COMPOUNDED, and only the third was wrong:
 *   1. The server already excludes resolved rows —
 *      get_flagged_project_checkins filters {"review_decision": {"$exists":
 *      False}} (backend/server.py). Nothing to fix there.
 *   2. handleReview updates the row IN PLACE, stamping review_decision onto it
 *      and leaving it rendered. That is deliberate — it shows the CP what he
 *      just did — and is NOT changed here.
 *   3. The only fetch effect had deps [projectId, fetchFlagged]. expo-router
 *      keeps the screen MOUNTED when the CP navigates away, so returning to it
 *      never re-ran anything. That is the whole defect.
 *
 * Run:  node src/utils/reviewRefreshOnFocus.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
const REVIEW = path.join(FRONTEND, 'app', 'logbooks', 'review.jsx');
const HUB = path.join(FRONTEND, 'app', 'logbooks', 'index.jsx');
const SERVER = path.join(FRONTEND, '..', 'backend', 'server.py');

const src = fs.readFileSync(REVIEW, 'utf8');
const hub = fs.readFileSync(HUB, 'utf8');
const server = fs.readFileSync(SERVER, 'utf8');

let passed = 0, failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

// ── 1. the fix is wired ─────────────────────────────────────────────────────
ok(/import \{[^}]*\buseFocusEffect\b[^}]*\} from 'expo-router';/.test(src),
  'review.jsx imports useFocusEffect from expo-router');
ok(/useFocusEffect\(/.test(src), 'review.jsx registers a focus effect');

// The focus effect must actually REFETCH — a focus hook that does something
// else would satisfy a naive "is it imported" check and fix nothing.
const focusBlock = (() => {
  const at = src.indexOf('useFocusEffect(');
  if (at === -1) return '';
  return src.slice(at, src.indexOf(');', src.indexOf('}, [', at)) + 2);
})();
ok(/fetchFlagged\(\)/.test(focusBlock),
  'the focus effect calls fetchFlagged — it re-asks the SERVER');
ok(/\}, \[projectId, fetchFlagged\]\)/.test(focusBlock),
  'the focus effect depends on projectId and fetchFlagged');

// ── 2. what must NOT have changed ───────────────────────────────────────────
ok(/useEffect\(\(\) => \{\s*if \(projectId\) \{ setLoading\(true\); fetchFlagged\(\); \}/.test(src),
  'the original mount effect is still there — focus is an ADDITION, not a swap');
ok(/setItems\(\(prev\) => prev\.map\(/.test(src),
  'handleReview still updates the row in place (shows the CP what he just did)');
ok(/const onRefresh = \(\) => \{ setRefreshing\(true\); fetchFlagged\(\); \};/.test(src),
  'pull-to-refresh is untouched');

// A spinner on focus would flash the list to empty on every return, which
// reads as "everything vanished" on a list the CP is already looking at.
ok(!/setLoading\(true\)/.test(focusBlock),
  'the focus refetch does NOT flash a loading state over a visible list');

// ── 3. it mirrors the established pattern rather than inventing one ─────────
ok(/useFocusEffect\(/.test(hub) && /from 'expo-router'/.test(hub),
  'app/logbooks/index.jsx already uses this exact pattern (the one being mirrored)');

// ── 4. the server half of the invariant ─────────────────────────────────────
// If the server ever stopped excluding resolved rows, refetching would return
// them and the screen would be wrong again for a completely different reason.
ok(/\{"review_decision": \{"\$exists": False\}\}/.test(server),
  'the server still excludes rows that already carry a review_decision');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed) process.exit(1);
console.log('ALL PASSED');
