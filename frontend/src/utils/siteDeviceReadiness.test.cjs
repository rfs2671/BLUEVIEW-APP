/**
 * IS THIS TABLET READY TO BE TAKEN AT ITS WORD?
 *
 * THE MACHINE. A fixed Android tablet is bolted to a construction gate. It
 * fills itself from GET /api/projects/{id}/manifest and is read — offline,
 * with no one to prepare it — by a superintendent and by a DOB inspector.
 *
 * THE RULING THIS ENCODES. An incomplete set is UNUSABLE, not partially
 * usable. "A device that silently holds nine of fifteen plans is worse than
 * one that says it holds none, because the second is a device somebody fixes
 * and the first is a device somebody trusts." The chunked store already obeys
 * that at the data layer: its reader answers complete / partial / absent and
 * PARTIAL yields zero rows. What did not exist was any screen saying so.
 *
 * THREE STATES, AND THE THIRD IS THE ONE THAT NEEDS ARGUING.
 *
 *   NEVER COMPLETED   no generation this device can still read committed in
 *                     full. Not ready. Hard warning, and the list on screen
 *                     must not be presented as authoritative.
 *   COMPLETE, CURRENT normal operation. No chrome.
 *   COMPLETE, STALE   a previous generation committed fully and a later
 *                     update did not. THE OLD COMPLETE SET STAYS
 *                     AUTHORITATIVE and the screen shows its AGE.
 *
 * The third is a judgement, so it is asserted against the store rather than
 * assumed: `writeManifestList` purges superseded generations ONLY after its
 * own commit lands, and a failed write rolls back only what that run wrote.
 * So the prior complete generation genuinely survives a later failure, and
 * discarding it would make the tablet worse for no gain. That is proved below
 * against the REAL store, not asserted in a comment.
 *
 * AND THE AGE HAS TO BE THE RIGHT AGE. The commit record carries the moment a
 * COMPLETE assembly became this device's set — not the moment of any write.
 * syncSiteManifest also writes on an INCOMPLETE fetch (a union against a
 * complete previous list), and if that refreshed the stamp, a tablet with a
 * flaky connection would report itself current for ever while never once
 * seeing the whole set. Asserted directly.
 *
 * WORDING IS THE DELIVERABLE. It is read at a gate, possibly by an inspector.
 * It may not name internal machinery and it may not say "sync failed"; it must
 * say the device cannot be relied on away from signal, that records may be
 * missing without saying so, and what to do about it. The exact strings are
 * pinned here, and a forbidden-vocabulary sweep runs over all of them.
 *
 * Run:  node src/utils/siteDeviceReadiness.test.cjs
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

const HERE = __dirname;
const FRONTEND = path.join(HERE, '..', '..');

// ── module loader (the siteManifestStore harness, same shims) ───────────────
const compiled = {};
function compile(full) {
  if (!(full in compiled)) {
    if (!fs.existsSync(full)) { compiled[full] = ''; return compiled[full]; }
    compiled[full] = babel.transformSync(fs.readFileSync(full, 'utf8'), {
      filename: full,
      plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')],
      configFile: false,
      babelrc: false,
    }).code;
  }
  return compiled[full];
}

function makeDevice(opts) {
  const o = opts || {};
  const store = {};
  const disk = new Set(o.files || []);
  const io = { sets: 0 };
  const setFails = () => o.failSetItemAfter !== undefined && io.sets > o.failSetItemAfter;
  return {
    store,
    disk,
    listKeys: () => Object.keys(store).filter((k) => k.startsWith('bv_doclist:')),
    setFailSetAfter: (n) => { o.failSetItemAfter = n; io.sets = 0; },
    AsyncStorage: {
      getAllKeys: async () => Object.keys(store),
      getItem: async (k) => (k in store ? store[k] : null),
      setItem: async (k, v) => {
        io.sets += 1;
        if (setFails()) throw new Error('database or disk is full (code 13)');
        store[k] = v;
      },
      removeItem: async (k) => { delete store[k]; },
    },
    FileSystem: {
      documentDirectory: '/doc/',
      readDirectoryAsync: async () => [...disk],
      deleteAsync: async (uri) => { disk.delete(uri.split('/').pop()); },
      getInfoAsync: async (uri) => {
        const name = uri.split('/').pop();
        if (name === 'documents') return { exists: true, isDirectory: true };
        return disk.has(name) ? { exists: true, size: 10 } : { exists: false, size: 0 };
      },
      makeDirectoryAsync: async () => {},
      getFreeDiskStorageAsync: async () => 1e10,
      downloadAsync: async (url, dest) => {
        const name = dest.split('/').pop();
        disk.add(name);
        return { status: 200, uri: dest };
      },
    },
    NetInfo: {
      addEventListener: () => () => {},
      fetch: async () => ({ isConnected: true, isInternetReachable: true }),
    },
    AppState: { currentState: 'active', addEventListener: () => ({ remove: () => {} }) },
    apiClient: {
      defaults: { baseURL: 'https://api.test' },
      get: async () => {
        const page = (o.pages || []).shift();
        if (page === null || page === undefined) {
          const e = new Error('Network Error'); e.request = {}; throw e;
        }
        return { data: page };
      },
    },
  };
}

function load(device, rel) {
  const cache = device.__mods || (device.__mods = {});
  if (cache[rel]) return cache[rel];
  const m = {};
  cache[rel] = m;
  const full = path.join(HERE, rel);
  const shim = (spec) => {
    if (spec === '@react-native-async-storage/async-storage') {
      return { __esModule: true, default: device.AsyncStorage };
    }
    if (spec === 'expo-file-system/legacy') return device.FileSystem;
    if (spec === 'react-native') {
      return { Platform: { OS: 'android' }, AppState: device.AppState };
    }
    if (spec === '@react-native-community/netinfo') {
      return { __esModule: true, default: device.NetInfo };
    }
    if (spec === './api') {
      return { __esModule: true, default: device.apiClient, getToken: async () => 'jwt' };
    }
    if (spec === './docCache') return load(device, 'docCache.js');
    if (spec === './siteManifestStore') return load(device, 'siteManifestStore.js');
    throw new Error(`unstubbed import: ${spec}`);
  };
  shim.resolve = require.resolve;
  // eslint-disable-next-line no-new-func
  new Function('exports', 'module', 'require', compile(full))(m, { exports: m }, shim);
  return m;
}

const READINESS = 'siteDeviceReadiness.js';
const STORE = 'siteManifestStore.js';

// ── the wire/stored row shapes ─────────────────────────────────────────────
const sRow = (id, cache_version, e = 'pdf') => ({ id, cache_version, s: 100, e });
const fWire = (id, v, e = 'pdf') => ({ id, v, s: 100, e });
const lWire = (id, v) => ({ id, v });

function page({ files = [], logbooks = [], filesMore = false, logsMore = false, complete } = {}) {
  return {
    project_id: 'P1',
    limit: 1000,
    files: { rows: files, skip: 0, total: files.length, has_more: filesMore },
    logbooks: { rows: logbooks, skip: 0, total: logbooks.length, has_more: logsMore },
    complete: complete === undefined ? (!filesMore && !logsMore) : complete,
  };
}

// The exact copy, pinned. These literals ARE the deliverable; the module is
// asserted to produce them character for character.
const COPY = {
  never: {
    tone: 'critical',
    heading: 'This tablet is not ready to use offline',
    body: 'It has not finished downloading this project’s plans, documents and '
      + 'logbooks. Records may be missing without showing as missing. Keep it on '
      + 'Wi-Fi until this message clears.',
    detail: 'If this message is still here tomorrow, tell the office before anyone '
      + 'relies on this tablet.',
  },
  stale: {
    tone: 'attention',
    heading: 'These records may be out of date',
    body: 'This tablet holds a complete set of this project’s plans, documents and '
      + 'logbooks, but it has not been able to pick up newer ones. Anything added or '
      + 'withdrawn since then is not on it. Put it back on Wi-Fi to bring it up to date.',
  },
  filling: {
    tone: 'attention',
    heading: 'Still saving this project to the tablet',
  },
};

// Nothing in any string a superintendent or an inspector reads may name a
// mechanism, blame a subsystem, or read as a developer's error message.
const FORBIDDEN = [
  'sync', 'manifest', 'chunk', 'generation', 'commit', 'cache', 'AsyncStorage',
  'server', 'API', 'endpoint', 'fetch', 'partial', 'error', 'failed', 'failure',
  'null', 'undefined', 'store', 'poll',
];

async function main() {
  // ═══════════════════════════════════════════════════════════════════════
  // 0. NAMED FAILURES, NOT A STACK TRACE. Against a tree with no readiness
  //    module every guarantee below must still report itself by name.
  // ═══════════════════════════════════════════════════════════════════════
  const R = load(makeDevice({}), READINESS);
  {
    let missing = 0;
    for (const name of ['readinessFrom', 'readSiteReadiness', 'describeReadiness',
      'SITE_READY_NEVER', 'SITE_READY_CURRENT', 'SITE_READY_STALE',
      'SITE_READY_UNKNOWN', 'STALE_AFTER_MS']) {
      const present = R[name] !== undefined;
      ok(present, `siteDeviceReadiness exports ${name}`);
      if (!present) missing += 1;
    }
    if (missing > 0) {
      console.log(`\n  ${passed} passed, ${failed} failed`);
      console.log('  (stopping: this tree has no site device readiness state)');
      process.exit(1);
    }
  }

  const { readinessFrom, describeReadiness, STALE_AFTER_MS } = R;
  const NEVER = R.SITE_READY_NEVER;
  const CURRENT = R.SITE_READY_CURRENT;
  const STALE = R.SITE_READY_STALE;
  const UNKNOWN = R.SITE_READY_UNKNOWN;

  const NOW = 1800000000000;
  const complete = (rows, at) => ({ state: 'complete', rows, at, reason: null });
  const partial = (reason) => ({ state: 'partial', rows: [], at: null, reason });
  const absent = () => ({ state: 'absent', rows: [], at: null, reason: 'nothing-stored' });

  // ═══════════════════════════════════════════════════════════════════════
  // 1. NEVER COMPLETED. Either half unusable makes the whole device unusable
  //    — a tablet with every plan and no logbook is not a tablet an inspector
  //    can be handed.
  // ═══════════════════════════════════════════════════════════════════════
  {
    ok(readinessFrom({ files: absent(), logbooks: absent(), now: NOW }).state === NEVER,
      'nothing stored at all is NOT READY');
    ok(readinessFrom({ files: partial('missing-chunk-2'), logbooks: complete([], NOW), now: NOW }).state === NEVER,
      'a half-written PLANS list is NOT READY even though the logbooks are whole');
    ok(readinessFrom({ files: complete([], NOW), logbooks: partial('uncommitted-chunks'), now: NOW }).state === NEVER,
      'a half-written LOGBOOK list is NOT READY even though the plans are whole');

    const r = readinessFrom({
      files: partial('missing-chunk-2'), logbooks: absent(), now: NOW,
    });
    ok(r.countsKnown === false && r.expected === null && r.saved === null,
      'NOT READY reports NO fraction — an absent list supplies no denominator');
  }

  // ═══════════════════════════════════════════════════════════════════════
  // 2. COMPLETE AND CURRENT — and the age comes from the OLDER of the two,
  //    because the device is only as current as its stalest half.
  // ═══════════════════════════════════════════════════════════════════════
  {
    const cached = new Set(['f1.1.pdf', 'L1.2.pdf']);
    const r = readinessFrom({
      files: complete([sRow('f1', 1)], NOW - 1000),
      logbooks: complete([sRow('L1', 2)], NOW - 60000),
      cachedNames: cached,
      now: NOW,
    });
    ok(r.state === CURRENT, 'two fresh complete halves are CURRENT');
    ok(r.ageMs === 60000, 'the age is the OLDER half, not the newer one');
    ok(r.saved === 2 && r.expected === 2 && r.filling === false,
      'a device holding every file reports 2 of 2 and is not filling');
    ok(describeReadiness(r) === null,
      'COMPLETE AND CURRENT renders NO chrome at all');
  }

  // ═══════════════════════════════════════════════════════════════════════
  // 3. COMPLETE BUT STALE. The old complete set stays authoritative and the
  //    screen shows its age.
  // ═══════════════════════════════════════════════════════════════════════
  {
    const at = NOW - (3 * 24 * 60 * 60 * 1000);
    const r = readinessFrom({
      files: complete([sRow('f1', 1)], at),
      logbooks: complete([sRow('L1', 2)], NOW - 1000),
      cachedNames: new Set(['f1.1.pdf', 'L1.2.pdf']),
      now: NOW,
    });
    ok(r.state === STALE, 'a complete set older than the threshold is STALE');
    ok(r.rowsUsable === true,
      'STALE STILL HANDS BACK ITS ROWS — the previous complete set remains usable');
    const c = describeReadiness(r);
    ok(c.detail === 'Last complete update: 3 days ago.',
      'STALE states the AGE, in days a superintendent can act on');

    // A STALE DEVICE THAT IS ALSO SHORT OF FILES SAYS BOTH, IN ONE LINE — and
    // the denominator is still one a complete generation supplied.
    const short = readinessFrom({
      files: complete([sRow('f1', 1), sRow('f2', 1)], at),
      logbooks: complete([sRow('L1', 2)], NOW),
      cachedNames: new Set(['f1.1.pdf']),
      now: NOW,
    });
    ok(describeReadiness(short).detail
      === 'Last complete update: 3 days ago. 1 of 3 records are on this tablet.',
      'STALE reports how much of the complete set is actually on the device');

    const justUnder = readinessFrom({
      files: complete([], NOW - STALE_AFTER_MS + 1000),
      logbooks: complete([], NOW),
      now: NOW,
    });
    ok(justUnder.state === CURRENT, 'inside the threshold is still CURRENT');
    const justOver = readinessFrom({
      files: complete([], NOW - STALE_AFTER_MS - 1000),
      logbooks: complete([], NOW),
      now: NOW,
    });
    ok(justOver.state === STALE, 'outside the threshold is STALE');
  }

  // ═══════════════════════════════════════════════════════════════════════
  // 4. AN AGE THAT IS NOT RECORDED IS NOT AN AGE OF ZERO.
  //
  //    A list committed by a build older than the stamp reads as complete —
  //    the store says so on purpose — but nothing on the device says WHEN. A
  //    tablet that has been off the network since that build could be months
  //    out of date. Reporting CURRENT there would be a claim made from an
  //    absence, which is the exact move this whole feature exists to refuse.
  // ═══════════════════════════════════════════════════════════════════════
  {
    const r = readinessFrom({
      files: complete([], null),
      logbooks: complete([], NOW),
      now: NOW,
    });
    ok(r.state === STALE, 'a complete set with NO recorded age is STALE, never CURRENT');
    ok(r.ageKnown === false, 'and it says the age is unknown rather than inventing one');
    ok(describeReadiness(r).detail === 'Last complete update: not recorded on this tablet.',
      'the copy states the age is unrecorded rather than printing a fabricated one');
  }

  // ═══════════════════════════════════════════════════════════════════════
  // 5. NO FRACTION THIS DEVICE CANNOT STAND BEHIND.
  //
  //    A count of files on disk is real. A denominator is only real when a
  //    COMPLETE generation supplies it, and the numerator is only real when
  //    the device can read its own directory at all.
  // ═══════════════════════════════════════════════════════════════════════
  {
    const r = readinessFrom({
      files: complete([sRow('f1', 1), sRow('f2', 1), sRow('f3', 1, 'docx')], NOW),
      logbooks: complete([sRow('L1', 2)], NOW),
      cachedNames: new Set(['f1.1.pdf']),
      now: NOW,
    });
    ok(r.expected === 3,
      'the denominator counts only what this device can hold — the .docx is out');
    ok(r.saved === 1 && r.filling === true, 'the numerator is the files actually on disk');
    const c = describeReadiness(r);
    ok(c.heading === COPY.filling.heading, 'a complete set still filling says so');
    ok(c.body === '1 of 3 plans, documents and logbooks are on this tablet so far. '
      + 'The rest need Wi-Fi. Anything not yet saved will not open once the signal drops.',
      'and it prints the real fraction, with the real denominator');

    const noDir = readinessFrom({
      files: complete([sRow('f1', 1)], NOW),
      logbooks: complete([], NOW),
      cachedNames: null,
      now: NOW,
    });
    ok(noDir.countsKnown === false && noDir.saved === null,
      'a device that cannot read its own directory reports NO numerator');
    ok(describeReadiness(noDir) === null,
      'and prints no fraction at all rather than a zero it did not measure');
  }

  // ═══════════════════════════════════════════════════════════════════════
  // 6. UNKNOWN IS NOT A VERDICT. Before the read resolves the screen must say
  //    nothing — an accusation on first paint would be there on every cold
  //    boot of a perfectly healthy tablet.
  // ═══════════════════════════════════════════════════════════════════════
  {
    ok(readinessFrom({ files: null, logbooks: null, now: NOW }).state === UNKNOWN,
      'nothing read yet is UNKNOWN, not NOT READY');
    ok(describeReadiness({ state: UNKNOWN }) === null, 'UNKNOWN renders nothing');
    ok(describeReadiness(null) === null, 'and neither does a missing readiness object');
  }

  // ═══════════════════════════════════════════════════════════════════════
  // 7. THE WORDING. Pinned exactly, then swept for vocabulary that would
  //    either name a mechanism or read as a developer's error message on a
  //    screen a DOB inspector may be looking at.
  // ═══════════════════════════════════════════════════════════════════════
  {
    const never = describeReadiness(readinessFrom({
      files: absent(), logbooks: absent(), now: NOW,
    }));
    ok(never.tone === COPY.never.tone, 'NOT READY is a critical notice, not an advisory');
    ok(never.heading === COPY.never.heading, `NOT READY heading: "${COPY.never.heading}"`);
    ok(never.body === COPY.never.body, 'NOT READY body is pinned exactly');
    ok(never.detail === COPY.never.detail, 'NOT READY says what to do when it does not clear');

    const stale = describeReadiness(readinessFrom({
      files: complete([], NOW - 5 * 86400000), logbooks: complete([], NOW), now: NOW,
    }));
    ok(stale.tone === COPY.stale.tone, 'STALE is an advisory — the set is still usable');
    ok(stale.heading === COPY.stale.heading, `STALE heading: "${COPY.stale.heading}"`);
    ok(stale.body === COPY.stale.body, 'STALE body is pinned exactly');

    const all = [];
    for (const r of [never, stale, describeReadiness(readinessFrom({
      files: complete([sRow('f1', 1)], NOW), logbooks: complete([], NOW),
      cachedNames: new Set(), now: NOW,
    }))]) {
      all.push(r.heading, r.body, r.detail || '');
    }
    const blob = all.join(' ').toLowerCase();
    for (const word of FORBIDDEN) {
      ok(!blob.includes(word.toLowerCase()),
        `no reader-facing string contains "${word}"`);
    }
    ok(blob.includes('offline') || blob.includes('wi-fi'),
      'every notice tells the reader what the device can and cannot do without signal');
  }

  // ═══════════════════════════════════════════════════════════════════════
  // 8. THE STALE RECOMMENDATION, PROVED AGAINST THE REAL STORE.
  //
  //    Keeping a previous complete generation is only the right answer if the
  //    store actually retains it. It does: purgeGenerations runs ONLY after
  //    the new commit lands, and a failed write rolls back only its own
  //    generation. If that ever changes, this fails and the recommendation
  //    has to be revisited.
  // ═══════════════════════════════════════════════════════════════════════
  {
    const d = makeDevice({});
    const M = load(d, STORE);
    const KEY = 'site_manifest_logs:P1';
    const first = await M.writeManifestList(KEY, [sRow('a', 1), sRow('b', 1)], { chunkRows: 1 });
    ok(first.ok === true, 'setup: a complete generation commits');

    // The next write dies partway through its chunks.
    d.setFailSetAfter(1);
    const second = await M.writeManifestList(KEY, [sRow('a', 1), sRow('b', 1), sRow('c', 1)], { chunkRows: 1 });
    ok(second.ok === false, 'setup: the later write does not land');

    const back = await M.readManifestList(KEY);
    ok(back.state === 'complete' && back.rows.length === 2,
      'THE PRIOR COMPLETE GENERATION SURVIVES A LATER FAILED WRITE — so keeping '
      + 'it authoritative and merely aging it is a choice the store supports');
  }

  // ═══════════════════════════════════════════════════════════════════════
  // 9. THE STAMP IS THE MOMENT A COMPLETE SET LANDED, NOT THE MOMENT OF ANY
  //    WRITE.
  //
  //    syncSiteManifest writes on an INCOMPLETE fetch too — a union against a
  //    complete previous list, which is right, because a dropped page must
  //    never shrink anything. But that write must NOT refresh the age, or a
  //    tablet on a flaky link reports itself current for ever while never
  //    once seeing the whole set. This is the difference between an honest
  //    age and a decorative one.
  // ═══════════════════════════════════════════════════════════════════════
  {
    const d = makeDevice({
      pages: [page({ files: [fWire('f1', 1)], logbooks: [lWire('L1', 2)] })],
    });
    const M = load(d, STORE);
    const scopes = M.manifestScopes('P1');
    await M.syncSiteManifest('P1');
    const afterComplete = await M.readManifestList(scopes.files);
    ok(typeof afterComplete.at === 'number' && afterComplete.at > 0,
      'a COMPLETE assembly stamps the moment it became this device’s set');

    // Age it, then run a poll whose walk is truncated.
    const aged = afterComplete.at - 5 * 86400000;
    const raw = JSON.parse(d.store[`bv_doclist:${scopes.files}`]);
    raw[0].__manifest_at = aged;
    d.store[`bv_doclist:${scopes.files}`] = JSON.stringify(raw);

    d.__mods = undefined;                    // fresh module state, same device
    const M2 = load(d, STORE);
    d.pages = undefined;
    const dev2 = d;
    dev2.apiClient.get = async () => ({
      data: page({ files: [fWire('f1', 1)], logbooks: [lWire('L1', 2)], filesMore: true }),
    });
    await M2.syncSiteManifest('P1', { maxPages: 1 });
    const afterPartial = await M2.readManifestList(scopes.files);
    ok(afterPartial.state === 'complete',
      'an incomplete poll still leaves a complete stored list (it unions, never shrinks)');
    ok(afterPartial.at === aged,
      'AND IT DOES NOT REFRESH THE AGE — an incomplete update cannot make a '
      + 'stale tablet report itself current');
  }

  // ═══════════════════════════════════════════════════════════════════════
  // 10. THE NOTICE COMPONENT RENDERS THE COPY IT IS GIVEN.
  //
  //     The real return block of SiteReadinessNotice.jsx is sliced out,
  //     transpiled and executed, so the text asserted is the text the
  //     component produces rather than a hand-copy of it.
  // ═══════════════════════════════════════════════════════════════════════
  {
    const file = path.join(FRONTEND, 'src', 'components', 'SiteReadinessNotice.jsx');
    if (!fs.existsSync(file)) {
      ok(false, 'src/components/SiteReadinessNotice.jsx exists');
    } else {
      const src = fs.readFileSync(file, 'utf8').split('\r\n').join('\n');
      const START = '  return (\n';
      const END = '\n  );\n}';
      const from = src.indexOf(START);
      const to = src.indexOf(END, from);
      ok(from >= 0 && to > from, 'the notice component has a sliceable return block');
      if (from >= 0 && to > from) {
        const block = src.slice(from + START.length, to);
        const code = babel.transformSync(`const __out = (${block.trim()});`, {
          filename: 'SiteReadinessNotice.jsx',
          babelrc: false,
          configFile: false,
          plugins: [[require.resolve('@babel/plugin-transform-react-jsx'),
            { runtime: 'classic', pragma: '__R.createElement', pragmaFrag: '__R.Fragment' }]],
        }).code;
        const __R = {
          Fragment: 'Fragment',
          createElement: (type, props, ...children) => ({ __el: true, type, props: props || {}, children }),
        };
        const text = (node, out = []) => {
          if (node === null || node === undefined || typeof node === 'boolean') return out;
          if (Array.isArray(node)) { node.forEach((n) => text(n, out)); return out; }
          if (typeof node === 'string' || typeof node === 'number') { out.push(String(node)); return out; }
          if (!node.__el) return out;
          text(node.children.length ? node.children : node.props.children, out);
          return out;
        };
        const copy = describeReadiness(readinessFrom({
          files: absent(), logbooks: absent(), now: NOW,
        }));
        const seed = {
          __R,
          copy,
          Icon: 'Icon',
          tint: '#ef4444',
          critical: true,
          style: undefined,
          withAlpha: () => 'rgba(0,0,0,0.5)',
          s: new Proxy({}, { get: () => ({}) }),
        };
        const scope = new Proxy(seed, {
          has: () => true,
          get: (t, k) => (k in t ? t[k] : {}),
        });
        // eslint-disable-next-line no-new-func
        const out = new Function('__scope', `with (__scope) { ${code}; return __out; }`)(scope);
        const rendered = text(out).join(' ');
        ok(rendered.includes(COPY.never.heading), 'the component renders the heading');
        ok(rendered.includes(COPY.never.body), 'the component renders the body');
        ok(rendered.includes(COPY.never.detail), 'the component renders the detail line');
      }
    }
  }

  console.log(`\n  ${passed} passed, ${failed} failed`);
  process.exit(failed === 0 ? 0 : 1);
}

main().catch((e) => { console.error(e); process.exit(1); });
