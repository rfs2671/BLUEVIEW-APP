/**
 * THE SAME DECISION ON TWO SURFACES MUST BE EQUALLY DURABLE.
 *
 * An Approve / Send-home call on a flagged check-in is a compliance record. The
 * site-device kiosk (app/site/checkins.jsx) has always survived a dead zone:
 * the decision goes to the offline queue and processQueue() posts it on the
 * NetInfo reconnect. The CP's own surface (app/logbooks/review.jsx) — the
 * screen a competent person actually uses, on a phone, on a jobsite — was
 * online-only. Its catch block said so out loud: "No write queue here (out of
 * scope)". Same decision, two surfaces, one durable.
 *
 * This pins that review.jsx now reuses queueCheckInReview rather than growing a
 * second mechanism, and that it reuses ALL of the twin's behaviour, not just
 * the write:
 *
 *   • queue on unreachable-or-5xx, but NEVER on a 4xx (a real refusal replayed
 *     would never succeed)
 *   • drop the queued copy when the same decision later lands online
 *   • mark the row review_pending_sync with NULL attribution — reviewed_by is
 *     derived server-side from the token and does not exist yet
 *   • SHOW that it is pending. A decision that silently queues is a different
 *     defect, so the marker must reach the screen, per row and in aggregate.
 *   • re-overlay the queue on every refetch. This matters MORE here than on the
 *     kiosk: review.jsx refetches on focus, on pull-to-refresh and on project
 *     change, and the server's flagged list excludes nothing that never
 *     arrived — so without the overlay the row returns looking undecided and
 *     the CP decides the same worker again.
 *
 * Static guard over the real sources, the house pattern.
 *
 * Run:  node src/utils/reviewDecisionDurability.test.cjs
 */

const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');

// Comments stripped: prose describing the queue must not be able to satisfy a
// guard asking whether the queue is WIRED.
const strip = (p) => fs.readFileSync(path.join(FRONTEND, p), 'utf8')
  .replace(/\{\s*\/\*[\s\S]*?\*\/\s*\}/g, '')
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/(?<!:)\/\/.*$/gm, '');

const rawReview = fs.readFileSync(
  path.join(FRONTEND, 'app', 'logbooks', 'review.jsx'), 'utf8');
const review = strip(path.join('app', 'logbooks', 'review.jsx'));
const twin = strip(path.join('app', 'site', 'checkins.jsx'));
const queue = fs.readFileSync(
  path.join(FRONTEND, 'src', 'utils', 'offlineQueue.js'), 'utf8');
const smoke = fs.readFileSync(
  path.join(FRONTEND, 'scripts', 'smoke-mount.cjs'), 'utf8');
const enCat = fs.readFileSync(
  path.join(FRONTEND, 'src', 'i18n', 'en.js'), 'utf8');

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

// Source of one function, declaration to terminator (fix1FlaggedWorkerSurfaces).
function block(src, opener, closer) {
  const start = src.indexOf(opener);
  if (start < 0) return '';
  const end = src.indexOf(closer, start + opener.length);
  return end < 0 ? src.slice(start) : src.slice(start, end);
}

// ── Subjects are real (assertionsCanFail.test.cjs) ──────────────────────────
ok(rawReview.length > 5000, 'review.jsx loaded');
ok(review.length > rawReview.length * 0.5, 'the comment strip left review.jsx code behind');
ok(twin.length > 5000, 'the site twin loaded');

const handleReview = block(review, 'const handleReview', 'const handleAssign');
ok(handleReview.length > 400, 'the handleReview slice is a real function body');

// ── One mechanism, not two ──────────────────────────────────────────────────
console.log('\nreview.jsx — reuses the existing queue, invents nothing');

ok(/from '\.\.\/\.\.\/src\/utils\/offlineQueue'/.test(review),
  'imports from the shared offlineQueue module');
ok(/queueCheckInReview/.test(review),
  'reuses queueCheckInReview — the same helper the site device uses');
ok(/getQueuedCheckInReviews/.test(review),
  'reuses getQueuedCheckInReviews to rehydrate pending decisions');
ok(/clearQueuedCheckInReview/.test(review),
  'reuses clearQueuedCheckInReview');

// A second mechanism is the failure this test exists to prevent.
ok(!/async-storage/.test(review),
  'no direct AsyncStorage use — the queue owns storage');
ok(!/AsyncStorage/.test(review),
  'AsyncStorage is not referenced at all');
ok(!/setItem\(|getItem\(/.test(review),
  'no hand-rolled persistence');
ok(!/writeDraft/.test(review),
  'no draft mechanism grafted onto a decision surface');
ok(!/blueview_offline_queue/.test(review),
  'the queue storage key stays private to offlineQueue.js');

// The helper it reuses must still be the shared one.
ok(/export async function queueCheckInReview/.test(queue),
  'queueCheckInReview is still exported from offlineQueue.js');
ok(/export async function getQueuedCheckInReviews/.test(queue),
  'getQueuedCheckInReviews is still exported');
ok(/export async function clearQueuedCheckInReview/.test(queue),
  'clearQueuedCheckInReview is still exported');
ok(/dedupeKey:\s*`\$\{REVIEW_DEDUPE_PREFIX\}\$\{checkinId\}`/.test(queue),
  'a re-decision still dedupes to ONE queued action per check-in');

// ── The write, and what must NOT be queued ──────────────────────────────────
console.log('\nreview.jsx — queues an unreachable decision, refuses to queue a refusal');

ok(/checkinsAPI\.review\(id, decision\)/.test(handleReview),
  'the online path still posts /checkins/{id}/review');
ok(/await queueCheckInReview\(id, decision\)/.test(handleReview),
  'the offline path queues the SAME decision for the SAME check-in');
ok(/isOfflineError\(e\)\s*\|\|\s*status\s*>=\s*500/.test(handleReview),
  'queues on unreachable OR a 5xx — the twin rule, verbatim');
ok(/e\?\.response\?\.status/.test(handleReview),
  'the status is read off the error to make that distinction');
ok(/await clearQueuedCheckInReview\(id\)/.test(handleReview),
  'a decision that lands online drops any queued copy');

// A 4xx is a real refusal. Replaying it would never succeed, so it must still
// surface as an error rather than being buried in a queue that retries 3 times.
const queueBranch = block(handleReview, 'if (isOfflineError(e)', 'toast.error');
ok(queueBranch.length > 100, 'the queue branch slice is non-empty');
ok(/return;/.test(queueBranch),
  'the queue branch returns — a 4xx falls through to the error toast');
ok(/toast\.error\(/.test(handleReview),
  'a real refusal still errors');

// ── The row is marked, with honest attribution ──────────────────────────────
console.log('\nreview.jsx — a queued decision is marked, not silently applied');

ok(/review_pending_sync:\s*true/.test(handleReview),
  'the row is stamped review_pending_sync on queue');
ok(/review_pending_sync:\s*false/.test(handleReview),
  'and cleared when the server confirms');
ok(/reviewed_by_name:\s*null/.test(handleReview) && /reviewed_at:\s*null/.test(handleReview),
  'attribution is NULL while pending — reviewed_by is derived server-side from the token');

// ── It is VISIBLE ───────────────────────────────────────────────────────────
// "A decision that silently queues with no indicator is a different defect."
console.log('\nreview.jsx — the pending state reaches the screen');

ok(/item\.review_pending_sync/.test(review),
  'the row render branches on review_pending_sync');
ok(/pendingCount/.test(review),
  'pending decisions are counted in aggregate');
ok(/CloudOff/.test(review),
  'the pending marker carries the same CloudOff icon as the twin');
ok(/pendingRow|pendingText/.test(review),
  'the per-row pending style exists');
ok(/pendingBanner/.test(review),
  'the aggregate banner style exists');

// The warning toast must not read like a success.
ok(/toast\.warning\(/.test(handleReview),
  'a queued decision toasts a WARNING, not a success');
ok(!/toast\.success\([^)]*offline/i.test(handleReview),
  'nothing reports an offline queue as a completed write');

// ── The overlay survives a refetch ──────────────────────────────────────────
console.log('\nreview.jsx — a refetch does not erase a pending decision');

const fetchFlagged = block(review, 'const fetchFlagged', 'useEffect(');
ok(fetchFlagged.length > 200, 'the fetchFlagged slice is non-empty');
ok(/withPendingReviews|getQueuedCheckInReviews/.test(fetchFlagged),
  'the flagged list is overlaid with queued decisions on every load');
ok(/const withPendingReviews/.test(review),
  'the overlay helper exists on this screen');

// It refetches aggressively — that is exactly why the overlay is required.
ok(/useFocusEffect/.test(review), 'the screen still refetches on focus');

// ── handleAssign is deliberately NOT changed ────────────────────────────────
// Trade assignment is a different action with no queue helper. Its honest
// "nothing was recorded" copy must survive, or this change would have made a
// second surface lie.
console.log('\nreview.jsx — trade assignment keeps its honest offline copy');

const handleAssign = block(review, 'const handleAssign', 'const fmt =');
ok(handleAssign.length > 300, 'the handleAssign slice is non-empty');
ok(!/queueCheckInReview/.test(handleAssign),
  'a trade assignment is NOT queued as a review decision');
ok(/offlineWrite/.test(handleAssign),
  'it still says plainly that nothing was recorded');
ok(/offlineWriteHint:\s*'The decision was NOT saved/.test(enCat),
  'the "NOT saved" copy still exists for the path that really does not save');

// ── Copy for the new state ──────────────────────────────────────────────────
console.log('\ni18n — the queued-decision copy exists (review is EN-only)');

const reviewNs = enCat.slice(enCat.indexOf('review: {'), enCat.indexOf('reason_CLASS_UNVERIFIED'));
ok(reviewNs.length > 500, 'the review namespace slice is non-empty');
ok(/queuedTitle:/.test(reviewNs), 'queuedTitle exists');
ok(/queuedApproved:/.test(reviewNs), 'queuedApproved exists');
ok(/queuedSentHome:/.test(reviewNs), 'queuedSentHome exists');
ok(/pendingSuffix:/.test(reviewNs), 'pendingSuffix exists — the per-row marker');
ok(/pendingBannerOne:/.test(reviewNs) && /pendingBannerMany:/.test(reviewNs),
  'the aggregate line is pluralized properly — no "1 decision(s)" on a compliance surface');
ok(/pendingCount === 1/.test(review),
  'the screen picks the singular form rather than rendering a template');
ok(/will sync/i.test(reviewNs),
  'the copy tells the CP the decision will sync, rather than claiming it is filed');

// ── The mount smoke must execute this screen ────────────────────────────────
console.log('\nsmoke-mount.cjs — the CP review route is mounted');

const routes = smoke.slice(smoke.indexOf('const ROUTES = ['), smoke.indexOf('const MIME'));
ok(routes.length > 300, 'the ROUTES slice is non-empty');
ok(/'\/logbooks\/review/.test(routes),
  '/logbooks/review is in ROUTES — nothing else in CI executes this screen');
ok(/'\/workers\/w1'/.test(routes),
  '/workers/w1 is still in ROUTES');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
