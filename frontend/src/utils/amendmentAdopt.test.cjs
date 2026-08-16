/**
 * THE AMENDMENT REACHES THE CP.
 *
 * Device round 5, finding 19, reproduced on a device: the CP filed a daily
 * jobsite log, tapped Amend, wrote a reason — and got a screen still marked
 * "FINALIZED — read-only", while the logbook LIST showed the same log as a
 * Draft. Both were truthful about different sources: the list reads the server,
 * where the amendment exists; the screen reads the device, where the parent is
 * frozen.
 *
 * The parent and its amendment share ONE draft key — (project, logType, date),
 * all three copied onto the child by amend_logbook — so the finalized local
 * draft shadowed the child forever. And writeDraft justified its absolute lock
 * with "corrections happen through an amendment (a NEW key)", an invariant
 * nothing has ever implemented. The lock was made absolute on the strength of
 * an escape hatch that did not exist.
 *
 * This is the only route for correcting a filed compliance record.
 *
 * Run:  node src/utils/amendmentAdopt.test.cjs
 */
const fs = require('fs');
const path = require('path');

const UTILS = __dirname;
const APP_LOGBOOKS = path.join(UTILS, '..', '..', 'app', 'logbooks');

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

/**
 * Comments stripped before every source assertion.
 *
 * These files EXPLAIN the calls being asserted, by name and at length — this
 * one included. Matching raw source has defeated a mutation check three times
 * on this project, most recently where the guard existed and simply was not
 * used. Data reads (package.json) do not go through this; source does.
 */
const strip = (text) => text
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/^\s*\/\/.*$/gm, '')
  .replace(/\s\/\/[^\n'"`]*$/gm, '');

const MOD_RAW = fs.readFileSync(path.join(UTILS, 'amendmentAdopt.js'), 'utf8');
const MOD = strip(MOD_RAW);
ok(/adoptAmendment/.test(MOD) && !/escape hatch that did not exist/.test(MOD),
  'the comment stripper removes prose but keeps code');

// The real module, executed against stubs — not a hand-copy of the rule.
function load({ docs, throws, onDiscard }) {
  const calls = { discarded: [], fetched: [] };
  const body = MOD_RAW
    .replace(/^import[\s\S]*?;\s*$/gm, '')
    .replace(/^export default [\s\S]*$/m, '')
    .replace(/^export (async function|function|const) /gm, '$1 ');
  // eslint-disable-next-line no-new-func
  const mod = new Function('__env', `
    const logbooksAPI = __env.logbooksAPI;
    const discardFinalizedDraft = __env.discardFinalizedDraft;
    ${body}
    return { adoptAmendment, isEditableChild, pickEditableChild };
  `)({
    logbooksAPI: {
      getByProject: async (p, t, d) => {
        calls.fetched.push([p, t, d]);
        if (throws) throw new Error('Network Error');
        return docs;
      },
    },
    discardFinalizedDraft: async (k) => {
      calls.discarded.push(k);
      return onDiscard === undefined ? true : onDiscard;
    },
  });
  return { mod, calls };
}

const ARGS = { key: 'logbook_draft:p1:daily_jobsite:2026-08-15', projectId: 'p1', logType: 'daily_jobsite', date: '2026-08-15' };
const LOCKED = { _id: 'orig', is_locked: true, status: 'submitted' };
const CHILD = { _id: 'child', is_locked: false, status: 'draft', is_amendment: true };

(async () => {
  console.log('\n-- what counts as an editable child --');
  {
    const { mod } = load({ docs: [] });
    ok(mod.isEditableChild(CHILD) === true, 'an unlocked document is adoptable');
    ok(mod.isEditableChild(LOCKED) === false, 'a FILED record is never adopted');
    ok(mod.isEditableChild(null) === false && mod.isEditableChild('x') === false,
      'and junk is not a document');
    ok(mod.pickEditableChild([LOCKED, CHILD])._id === 'child',
      'the child is found regardless of order');
    ok(mod.pickEditableChild([CHILD, LOCKED])._id === 'child', 'either way round');
    ok(mod.pickEditableChild([LOCKED]) === null, 'and a locked-only day has none');
  }

  console.log('\n-- the frozen parent is discarded, but only on proof --');
  {
    const { mod, calls } = load({ docs: [LOCKED, CHILD] });
    ok(await mod.adoptAmendment(ARGS) === true,
      'a locked original PLUS an unlocked child is an amendment: adopt it');
    ok(calls.discarded[0] === ARGS.key, 'the frozen parent is discarded by key');
    ok(calls.fetched[0][1] === 'daily_jobsite' && calls.fetched[0][2] === '2026-08-15',
      'and it asked the server about that exact (project, type, date)');
  }
  {
    const { mod, calls } = load({ docs: [LOCKED] });
    ok(await mod.adoptAmendment(ARGS) === false,
      'a filed log with NO child is left alone');
    ok(calls.discarded.length === 0, 'nothing is discarded');
  }
  {
    // ONE document that happens to be unlocked is not an amendment — it is the
    // log itself, mid-write or never filed. Discarding the local copy on that
    // would drop the only offline record of a filed log.
    const { mod, calls } = load({ docs: [CHILD] });
    ok(await mod.adoptAmendment(ARGS) === false,
      'a single unlocked document is NOT an amendment');
    ok(calls.discarded.length === 0, 'so nothing is discarded');
  }

  console.log('\n-- offline it does nothing, and says nothing --');
  {
    const { mod, calls } = load({ docs: [], throws: true });
    ok(await mod.adoptAmendment(ARGS) === false,
      'a failed fetch is NOT evidence that an amendment exists');
    ok(calls.discarded.length === 0,
      'and the local copy of a filed log survives — the log stays locked, which is honest');
  }
  {
    const { mod } = load({ docs: [] });
    ok(await mod.adoptAmendment(ARGS) === false, 'an empty day adopts nothing');
    ok(await mod.adoptAmendment({ ...ARGS, key: null }) === false,
      'and a missing key is refused rather than throwing');
  }
  {
    const { mod } = load({ docs: [LOCKED, CHILD], onDiscard: false });
    ok(await mod.adoptAmendment(ARGS) === false,
      'if the discard itself fails, the caller is told NO — it must not fall through '
      + 'to a server path while the frozen draft is still on disk');
  }

  console.log('\n-- all six editors are wired to it --');
  // Amend was broken on every form that is local-first, not only the one the
  // device test happened to use.
  const FORMS = ['daily_jobsite', 'toolbox_talk', 'osha_log', 'scaffold_maintenance',
    'preshift_signin', 'ssc_daily_safety_log'];
  for (const f of FORMS) {
    const src = strip(fs.readFileSync(path.join(APP_LOGBOOKS, `${f}.jsx`), 'utf8'));
    ok(/from '\.\.\/\.\.\/src\/utils\/amendmentAdopt'/.test(src), `${f}: imports it`);
    ok(/const _amended = \w+\.finalized && await adoptAmendment\(\{/.test(src),
      `${f}: asks the server before trusting a finalized local draft`);
    // The guard must sit BEFORE the early return, or it is decoration.
    const at = src.indexOf('const _amended =');
    const ret = src.indexOf('setLoading(false);', at);
    ok(at > -1 && ret > at, `${f}: it runs before the local-first early return`);
    // And the finalized lock must still apply when there is NO amendment.
    ok(/setLocked\(true\)/.test(src), `${f}: a filed log with no amendment still locks`);
  }

  console.log('\n-- the amend action clears the parent immediately --');
  {
    const bar = strip(fs.readFileSync(
      path.join(UTILS, '..', 'components', 'LogbookLockBar.jsx'), 'utf8'));
    ok(/await logbooksAPI\.amend\(logId, reason\.trim\(\)\);/.test(bar),
      'the amend call is still made');
    ok(/if \(draftKey\) await discardFinalizedDraft\(draftKey\);/.test(bar),
      'and the frozen parent is discarded the moment the server confirms the child');
    ok(bar.indexOf('logbooksAPI.amend(') < bar.indexOf('discardFinalizedDraft(draftKey)'),
      'AFTER the server confirms, never before — a failed amend must not '
      + 'destroy the local copy of a filed log');
  }

  console.log('\n-- the draft store says what it actually does --');
  {
    const store = fs.readFileSync(path.join(UTILS, 'logbookDrafts.js'), 'utf8');
    // The comment that justified an absolute lock with an invariant nothing
    // implements. It is why the lock was absolute, and it was wrong from the
    // day it was written.
    ok(!/corrections happen through an amendment \(a NEW key\)/i.test(store),
      'the false "a NEW key" justification is gone');
    ok(/CORRECTED \(device round 5, finding 19\)/.test(store),
      'and the record says what actually happens instead');
    ok(/export async function discardFinalizedDraft/.test(store),
      'the one documented way past the lock exists');
    // It must be a DELETE, not a write — writeDraft refuses finalized content
    // edits and should keep refusing them.
    ok(/removeItem\(key\)/.test(strip(store)),
      'and it deletes the record rather than editing a filed one in place');
  }

  console.log(`\n${passed} passed, ${failed} failed`);
  if (failed > 0) process.exit(1);
  console.log('ALL PASSED');
})();
