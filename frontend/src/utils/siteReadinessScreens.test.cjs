/**
 * THE THREE GATE-TABLET SCREENS, EXECUTED — not grepped.
 *
 * WHAT WAS WRONG. app/site/logbooks.jsx and app/site/documents.jsx already had
 * a two-state honesty discipline keyed on `fetchState`: "No Submitted Logs" is
 * a claim about the RECORD, so it may only be made when the SERVER answered,
 * and otherwise an <OfflineNotice> says which way the read failed. That
 * discipline is right and nothing here weakens it.
 *
 * BUT IT IS THE WRONG AXIS. It distinguishes "did the network answer just now"
 * from "did it not". It says nothing about whether THIS DEVICE holds the
 * complete approved set. A tablet that fetched fine and wrote its own store
 * partway through reports fetchState 'ok' and renders a short list with
 * nothing on screen saying it is short — which is the state the operator ruled
 * on: "a device that silently holds nine of fifteen plans is worse than one
 * that says it holds none, because the second is a device somebody fixes and
 * the first is a device somebody trusts."
 *
 * WHAT IS ASSERTED, on all three screens, by RUNNING their real render blocks:
 *
 *   1. NOT READY renders the warning, and the honest-empty card ("No
 *      Documents" / "No Submitted Logs") does NOT appear beside it. On a
 *      device with no complete set, an empty screen is not a statement about
 *      the project — it is a statement about the tablet, and only one of those
 *      two may be on screen at a time.
 *   2. NOT READY renders the warning ABOVE a list that DOES have rows, so a
 *      short list is never presented as the list.
 *   3. THE EXISTING fetchState DISCIPLINE IS UNCHANGED. With the device ready:
 *      fetchState 'ok' + nothing to show still renders the honest empty card
 *      and no offline notice; fetchState 'offline' still renders the offline
 *      notice and NOT the empty card.
 *
 * HOW. The repo has no JS test runner and no renderer (see
 * logbookViewRenderers.test.cjs, which uses the same technique against the
 * same screen). The real JSX region is sliced out of the real file, transpiled
 * with the repo's own babel, and run against a tiny createElement that builds a
 * plain tree. Free identifiers resolve through a `with` scope: the ones that
 * matter are seeded, the rest become inert host markers, so the branch
 * structure under test is the screen's own.
 *
 * Run:  node src/utils/siteReadinessScreens.test.cjs
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

const FRONTEND = path.join(__dirname, '..', '..');
const read = (p) => fs.readFileSync(p, 'utf8').split('\r\n').join('\n');

// ── the copy, as literals ──────────────────────────────────────────────────
// Held here so this file fails on a tree with no readiness module at all
// (rather than dying), and cross-checked against the real module below so the
// two can never drift.
const NOT_READY_HEADING = 'This tablet is not ready to use offline';
const STALE_HEADING = 'These records may be out of date';

// ── a createElement that builds a plain tree ───────────────────────────────
const __R = {
  Fragment: function Fragment(props) { return props.children; },
  createElement: (type, props, ...children) => ({
    __el: true, type, props: props || {}, children,
  }),
};

function collect(node, out) {
  if (node === null || node === undefined || typeof node === 'boolean') return;
  if (Array.isArray(node)) { node.forEach((n) => collect(n, out)); return; }
  if (typeof node === 'string' || typeof node === 'number') { out.push(String(node)); return; }
  if (!node.__el) return;
  const kids = node.children.length ? node.children : node.props.children;
  // A seeded component renders; an inert host marker just yields its children.
  if (typeof node.type === 'function' && node.type.__render !== false) {
    collect(node.type({ ...node.props, children: kids }), out);
    return;
  }
  collect(kids, out);
}

const textOf = (node) => {
  const out = [];
  collect(node, out);
  return out.join(' ');
};

/** An inert stand-in for any identifier the test did not seed: usable as a JSX
 *  type (renders its children), as a style object, and as a call. */
function inert(name) {
  const fn = function inertStub() { return null; };
  fn.__render = false;
  fn.__stub = name;
  return new Proxy(fn, {
    get(t, k) {
      if (k === '__render' || k === '__stub' || typeof k === 'symbol') return t[k];
      if (k === 'call' || k === 'apply' || k === 'bind' || k === 'prototype'
        || k === 'length' || k === 'name') return t[k];
      return inert(`${name}.${String(k)}`);
    },
    apply() { return ''; },
  });
}

function runBlock(block, seed, label) {
  const code = babel.transformSync(`const __out = (<>${block}</>);`, {
    filename: `${label}.jsx`,
    babelrc: false,
    configFile: false,
    plugins: [[require.resolve('@babel/plugin-transform-react-jsx'),
      { runtime: 'classic', pragma: '__R.createElement', pragmaFrag: '__R.Fragment' }]],
  }).code;
  const base = { __R, ...seed };
  const scope = new Proxy(base, {
    has: () => true,
    get: (t, k) => {
      if (typeof k === 'symbol') return undefined;
      if (k in t) return t[k];
      return inert(String(k));
    },
  });
  // eslint-disable-next-line no-new-func
  return new Function('__scope', `with (__scope) { ${code}; return __out; }`)(scope);
}

/** Slice a JSX children region out of a screen, between two literal anchors. */
function slice(src, startAnchor, endAnchor, what) {
  const from = src.indexOf(startAnchor);
  if (from < 0) throw new Error(`${what}: start anchor not found — this test is stale`);
  const to = src.indexOf(endAnchor, from + startAnchor.length);
  if (to < 0) throw new Error(`${what}: end anchor not found — this test is stale`);
  return src.slice(from + startAnchor.length, to);
}

// ── seeds shared by every screen ───────────────────────────────────────────
//
// The two notices are the things under test, so they render identifiable text
// rather than being inert. Everything else about the screens is scenery.
const OfflineNotice = (props) => `«OFFLINE_NOTICE:${props.mode}:${props.cachedCount === undefined ? '-' : props.cachedCount}»`;
const readinessCopy = {
  never: `${NOT_READY_HEADING} It has not finished downloading this project’s plans, documents and logbooks.`,
  stale: STALE_HEADING,
};
const SiteReadinessNotice = (props) => {
  const r = props.readiness || {};
  return readinessCopy[r.state] || '';
};
const READY = { state: 'current', filling: false };
const NOT_READY = { state: 'never' };

/**
 * THE REAL PREDICATE, NOT A RESTATEMENT OF IT.
 *
 * `mayClaimEmpty` is computed just outside each sliced region, so the harness
 * has to supply it — and supplying a hand-written rule would make these tests
 * assert the harness rather than the screen. So the one-line export is lifted
 * out of the component source and evaluated. If it is renamed or its meaning
 * changes, this fails here rather than passing against a stale copy.
 */
const canClaimEmpty = (() => {
  const file = path.join(FRONTEND, 'src', 'components', 'SiteReadinessNotice.jsx');
  if (!fs.existsSync(file)) return () => true;
  const m = read(file).match(/export const canClaimEmpty = ([^;]+);/);
  if (!m) return () => true;
  // eslint-disable-next-line no-new-func
  return new Function('SITE_READY_NEVER', `return (${m[1]});`)('never');
})();

const commonSeed = {
  OfflineNotice,
  SiteReadinessNotice,
  GlassCard: (p) => p.children,
  GlassSkeleton: () => null,
  View: 'View',
  Text: 'Text',
  Pressable: 'Pressable',
  ScrollView: 'ScrollView',
  ActivityIndicator: () => null,
};

function main() {
  // ═══════════════════════════════════════════════════════════════════════
  // 0. THE COPY UNDER TEST IS THE COPY THE APP SHIPS.
  // ═══════════════════════════════════════════════════════════════════════
  {
    const mod = path.join(FRONTEND, 'src', 'utils', 'siteDeviceReadiness.js');
    if (!fs.existsSync(mod)) {
      ok(false, 'src/utils/siteDeviceReadiness.js exists');
    } else {
      const src = read(mod);
      ok(src.includes(NOT_READY_HEADING),
        'the NOT READY heading asserted here is the one in siteDeviceReadiness.js');
      ok(src.includes(STALE_HEADING),
        'the STALE heading asserted here is the one in siteDeviceReadiness.js');
    }
  }

  // ═══════════════════════════════════════════════════════════════════════
  // 0b. AN HONEST NOTICE IS NOT THE CRASH SCREEN, AND MUST NOT READ AS ONE.
  //
  // scripts/smoke-mount.cjs — the only gate that EXECUTES these screens —
  // decides whether a route crashed by searching the rendered body for the
  // error boundary's title. <OfflineNotice mode="error"> used to open with
  // that same phrase, so the two were indistinguishable. It cut both ways: a
  // screen honestly reporting a failed read FAILED the mount gate, and a real
  // boundary on any screen showing that notice would have been waved through
  // as "just the notice". These two strings have to stay disjoint.
  // ═══════════════════════════════════════════════════════════════════════
  {
    const layout = path.join(FRONTEND, 'app', '_layout.jsx');
    const notice = path.join(FRONTEND, 'src', 'components', 'OfflineNotice.jsx');
    const boundary = fs.existsSync(layout)
      ? (read(layout).match(/<Text style={errorStyles\.title}>([^<]+)</) || [])[1]
      : null;
    ok(!!boundary, 'the error boundary still renders a title the mount gate can key on');
    // COMMENTS STRIPPED FIRST. The rule is about what RENDERS; the note in
    // OfflineNotice.jsx explaining this rule necessarily quotes the phrase,
    // and a check that failed on its own documentation would be deleted
    // rather than obeyed.
    const noticeCode = fs.existsSync(notice)
      ? read(notice).replace(/\/\*[\s\S]*?\*\//g, ' ').replace(/^\s*\/\/.*$/gm, '')
      : '';
    ok(!!boundary && noticeCode !== '' && !noticeCode.includes(boundary),
      `OfflineNotice does not contain the error boundary's title (${boundary}) — a `
      + 'crash and an honest failed read must not render the same words');
  }

  // ═══════════════════════════════════════════════════════════════════════
  // 1. app/site/documents.jsx
  // ═══════════════════════════════════════════════════════════════════════
  {
    const src = read(path.join(FRONTEND, 'app', 'site', 'documents.jsx'));
    const block = slice(
      src,
      '          showsVerticalScrollIndicator={false}\n        >\n',
      '\n        </ScrollView>',
      'app/site/documents.jsx',
    );
    const render = (over) => {
      const seed = {
        ...commonSeed,
        loading: false,
        fetchState: 'ok',
        files: [],
        groups: [],
        matchCount: 0,
        query: '',
        isWide: false,
        readiness: READY,
        ...over,
      };
      seed.mayClaimEmpty = canClaimEmpty(seed.readiness);
      return textOf(runBlock(block, seed, 'documents'));
    };

    // — the state under test —
    const notReadyEmpty = render({ readiness: NOT_READY });
    ok(notReadyEmpty.includes(NOT_READY_HEADING),
      'documents: a device with no complete set says it is not ready to use offline');
    ok(!notReadyEmpty.includes('No Documents'),
      'documents: and does NOT also print "No Documents" — on a tablet that never '
      + 'finished downloading, an empty screen is a fact about the TABLET');

    const rows = [['Approved Plans', [{ id: 'f1', name: 'A.pdf' }]]];
    const notReadyShort = render({
      readiness: NOT_READY, groups: rows, matchCount: 1, files: [{ id: 'f1' }],
      getFileIcon: () => ({ Icon: 'Icon', color: '#fff' }),
      isViewable: () => true,
      formatFileSize: () => '1 KB',
      extOf: () => 'pdf',
      handleOpenFile: () => {},
    });
    ok(notReadyShort.includes(NOT_READY_HEADING),
      'documents: the warning is rendered ABOVE a list that has rows, so a short '
      + 'list is never presented as the list');

    // — the discipline that must not move —
    const readyEmptyOk = render({});
    ok(readyEmptyOk.includes('No Documents'),
      'documents: PRESERVED — the server answered with none, so the honest empty '
      + 'state is still made');
    ok(!readyEmptyOk.includes('«OFFLINE_NOTICE'),
      'documents: PRESERVED — and no offline notice appears when the read was fine');

    const readyEmptyOffline = render({ fetchState: 'offline' });
    ok(readyEmptyOffline.includes('«OFFLINE_NOTICE:offline'),
      'documents: PRESERVED — a failed read still says which way it failed');
    ok(!readyEmptyOffline.includes('No Documents'),
      'documents: PRESERVED — and never claims the project is empty on a read it '
      + 'did not get');

    const readyEmptyError = render({ fetchState: 'error' });
    ok(readyEmptyError.includes('«OFFLINE_NOTICE:error'),
      'documents: PRESERVED — an error is distinguished from being offline');

    // — both axes true at once —
    const bothBad = render({ readiness: NOT_READY, fetchState: 'offline' });
    ok(bothBad.includes(NOT_READY_HEADING),
      'documents: offline AND not ready — the device-level fact is the one shown');
    ok(!bothBad.includes('No Documents'),
      'documents: offline AND not ready — still no claim about the project');
    ok(!bothBad.includes('«OFFLINE_NOTICE'),
      'documents: offline AND not ready — the "showing saved copy, N saved items" '
      + 'notice stands down, because on an unfinished device that IS the short '
      + 'list presented as the list');
  }

  // ═══════════════════════════════════════════════════════════════════════
  // 2. app/site/logbooks.jsx — the screen a DOB inspector is handed.
  // ═══════════════════════════════════════════════════════════════════════
  {
    const src = read(path.join(FRONTEND, 'app', 'site', 'logbooks.jsx'));
    const block = slice(
      src,
      '<ScrollView style={s.scrollView} contentContainerStyle={s.scrollContent}>\n',
      '\n        </ScrollView>',
      'app/site/logbooks.jsx',
    );
    const render = (over) => {
      const seed = {
        ...commonSeed,
        loading: false,
        fetchState: 'ok',
        // THE LIST IS DRAWN OFF THE INDEX, not off a map of whole documents.
        // `filteredIndex` is the identity rows for the active tab; the day's
        // rendered detail is read off the filesystem into `dayLogs`, which is
        // why an unopened day is `undefined` here rather than an empty array.
        sortedDates: [],
        filteredIndex: [],
        dayLogs: {},
        dayLoading: null,
        expandedDate: null,
        visibleLogCount: 0,
        activeTab: 'daily_log',
        tabLabel: () => 'Daily Log',
        formatDate: (d) => String(d),
        readiness: READY,
        ...over,
      };
      seed.mayClaimEmpty = canClaimEmpty(seed.readiness);
      return textOf(runBlock(block, seed, 'logbooks'));
    };

    const notReadyEmpty = render({ readiness: NOT_READY });
    ok(notReadyEmpty.includes(NOT_READY_HEADING),
      'logbooks: a device with no complete set says it is not ready to use offline');
    ok(!notReadyEmpty.includes('No Submitted Logs'),
      'logbooks: and does NOT tell an inspector the record is empty — the record '
      + 'is not what is empty');
    ok(!render({ readiness: NOT_READY, fetchState: 'offline' }).includes('«OFFLINE_NOTICE'),
      'logbooks: offline AND not ready — one explanation of the screen, and it is '
      + 'the one about the tablet');

    const ROW = {
      date: '2026-08-30',
      id: 'day_P1_2026-08-30',
      cache_version: '2026-08-30T07:05:00+00:00',
      logs: [{ id: 'l1', log_type: 'daily_log', status: 'submitted', updated_at: 'v1' }],
    };
    const withRows = (over) => render({
      sortedDates: ['2026-08-30'],
      filteredIndex: [ROW],
      visibleLogCount: 1,
      renderLogContent: () => null,
      handleCombinedPdf: () => {},
      handleViewLogPdf: () => {},
      handleShareLogPdf: () => {},
      openDate: () => {},
      ...over,
    });

    const notReadyShort = withRows({ readiness: NOT_READY });
    ok(notReadyShort.includes(NOT_READY_HEADING),
      'logbooks: the warning is rendered ABOVE a list that has rows');
    ok(notReadyShort.includes('2026-08-30'),
      'logbooks: and the list under it really did render — a seed the screen no '
      + 'longer reads would make the assertion above vacuous');

    // A DAY WHOSE DETAIL IS NOT ON THIS TABLET IS NOT A BLANK DAY.
    //
    // The index is the complete filed history, so the date is real and the
    // count beside it is real. The rendered detail lives on the filesystem and
    // can be absent — never downloaded, or superseded by an amendment. Drawing
    // an opened date with nothing under it would show a filed day as an empty
    // one to a DOB inspector, which is the same claim-about-the-record the
    // empty state exists to refuse.
    const openMissing = withRows({ expandedDate: '2026-08-30', dayLogs: { '2026-08-30': null } });
    ok(openMissing.includes('not saved on this tablet'),
      'logbooks: an opened day whose detail this tablet does not hold SAYS SO '
      + 'rather than rendering blank');
    ok(openMissing.includes('One record was filed on this date'),
      'logbooks: and still reports how many records were filed, off the index');
    ok(openMissing.includes('PDF'),
      'logbooks: and still offers the PDFs, which are a separate cache and are '
      + 'usually still here');

    const openLoading = withRows({ expandedDate: '2026-08-30', dayLoading: '2026-08-30' });
    ok(openLoading.includes('Opening this day'),
      'logbooks: while the day is being read off disk the screen says so, so the '
      + 'gap is never mistaken for an empty day');
    ok(!openLoading.includes('not saved on this tablet'),
      'logbooks: and does not accuse the tablet before the read has finished');

    const readyEmptyOk = render({});
    ok(readyEmptyOk.includes('No Submitted Logs'),
      'logbooks: PRESERVED — the honest empty state still stands when the server '
      + 'answered');
    ok(!readyEmptyOk.includes('«OFFLINE_NOTICE'),
      'logbooks: PRESERVED — and no offline notice when the read was fine');

    const readyEmptyOffline = render({ fetchState: 'offline' });
    ok(readyEmptyOffline.includes('«OFFLINE_NOTICE:offline'),
      'logbooks: PRESERVED — a failed read says which way it failed');
    ok(!readyEmptyOffline.includes('No Submitted Logs'),
      'logbooks: PRESERVED — and never says "No Submitted Logs" to an inspector '
      + 'on a read it did not get');
  }

  // ═══════════════════════════════════════════════════════════════════════
  // 3. app/site/index.jsx — the home screen, where somebody decides whether
  //    to walk away from the signal with this tablet.
  // ═══════════════════════════════════════════════════════════════════════
  {
    const src = read(path.join(FRONTEND, 'app', 'site', 'index.jsx'));
    const block = slice(
      src,
      '<View style={s.content}>\n',
      '{/* Top Row: Log Books + Daily Logs */}',
      'app/site/index.jsx',
    );
    const render = (over) => textOf(runBlock(block, {
      ...commonSeed,
      loading: false,
      logsState: 'ok',
      workersState: 'ok',
      readiness: READY,
      ...over,
    }, 'site-index'));

    ok(render({ readiness: NOT_READY }).includes(NOT_READY_HEADING),
      'site home: a device with no complete set says it is not ready to use offline');
    ok(render({ readiness: { state: 'stale', ageKnown: true } }).includes(STALE_HEADING),
      'site home: a complete but ageing set is reported as ageing, not as broken');
    ok(!render({}).includes(NOT_READY_HEADING),
      'site home: a ready device is not accused of anything');

    // The counts banner is a different subject on a different axis and is
    // untouched: it is about TODAY'S NUMBERS, not about what this device holds.
    ok(render({ logsState: 'offline' }).includes('«OFFLINE_NOTICE:offline'),
      'site home: PRESERVED — an unreadable count still says so');
    ok(!render({}).includes('«OFFLINE_NOTICE'),
      'site home: PRESERVED — and says nothing when both counts read fine');
    const both = render({ readiness: NOT_READY, logsState: 'offline' });
    ok(both.includes(NOT_READY_HEADING) && both.includes('«OFFLINE_NOTICE:offline'),
      'site home: both axes can be true at once and both are stated — they are '
      + 'different facts about different things');
  }

  console.log(`\n  ${passed} passed, ${failed} failed`);
  process.exit(failed === 0 ? 0 : 1);
}

try {
  main();
} catch (e) {
  console.log(`  FAIL  ${e.message}`);
  console.log(`\n  ${passed} passed, ${failed + 1} failed`);
  process.exit(1);
}
