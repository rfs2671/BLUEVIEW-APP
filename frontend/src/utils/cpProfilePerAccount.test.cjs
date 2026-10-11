/**
 * ONE ACCOUNT'S SIGNATURE NEVER REACHES ANOTHER'S. Ruled 2026-10-10.
 *
 * THE DEFECT, 588 Thomas. The signer's saved name and signature drawing lived
 * under ONE device-wide AsyncStorage key, `blueview_cp_profile`, which logout
 * did not clear. Shawn (a CP) and Michael (the superintendent) used one phone.
 * Shawn's profile was cached on 2026-09-16; on 2026-09-22 Michael's editors
 * loaded it, and `autoSave` wrote it to Michael's profile. Thirty of Michael's
 * filed logs carry Shawn's drawing -- seven under Michael's name.
 *
 * SECTION 1 runs the cache module against an in-memory store. SECTION 2 runs
 * the REAL hook, with React stubbed just enough to execute it, through the
 * exact sequence that leaked: Shawn's profile on the device, Michael signed
 * in, the server unreachable. SECTION 3 is logout.
 *
 *   node frontend/src/utils/cpProfilePerAccount.test.cjs
 */
const fs = require('fs');
const path = require('path');
const { loadEsm } = require('./esmHarness.cjs');

let passed = 0;
let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); } else { failed += 1; console.log(`  FAIL  ${label}`); }
}

function store(initial = {}) {
  const data = { ...initial };
  return {
    data,
    getItem: async (k) => (k in data ? data[k] : null),
    setItem: async (k, v) => { data[k] = v; },
    removeItem: async (k) => { delete data[k]; },
    getAllKeys: async () => Object.keys(data),
    multiRemove: async (ks) => { ks.forEach((k) => delete data[k]); },
  };
}

const SHAWN_SIG = { paths: [[{ x: 1, y: 2 }]], signerName: 'shawn' };
const MICHAEL_SIG = { paths: [[{ x: 9, y: 9 }]], signerName: 'Michael Cespedes' };
const LEGACY = JSON.stringify({ cp_name: 'shawn', cp_signature: SHAWN_SIG });

const cacheWith = (AsyncStorage) => loadEsm('src/utils/cpProfileCache.js', {
  stubs: { '@react-native-async-storage/async-storage': { __esModule: true, default: AsyncStorage } },
});

(async () => {
  console.log('\n1. THE CACHE IS KEYED BY THE ACCOUNT');
  {
    const S = store({ blueview_cp_profile: LEGACY, blueview_drafts_x: 'keep' });
    const C = cacheWith(S);
    ok(await C.readCpProfile('michael') === null,
      'the old device-wide value (Shawn\'s) is never read for Michael');
    ok(!('blueview_cp_profile' in S.data), 'and it is deleted on sight');
    await C.writeCpProfile('shawn', { cp_name: 'shawn', cp_signature: SHAWN_SIG });
    ok(await C.readCpProfile('michael') === null, 'a value saved for Shawn is not Michael\'s');
    const mine = await C.readCpProfile('shawn');
    ok(mine && mine.cp_name === 'shawn', 'and is still Shawn\'s');
    S.data['blueview_cp_profile:michael'] = JSON.stringify(
      { user_id: 'shawn', cp_name: 'shawn', cp_signature: SHAWN_SIG });
    ok(await C.readCpProfile('michael') === null,
      'a value whose owner field names another account is refused under any key');
    ok(await C.readCpProfile(null) === null && await C.readCpProfile('') === null,
      'no account, no profile');
    ok(await C.writeCpProfile(null, { cp_name: 'x' }) === false, 'and nothing is written without one');
    ok(S.data.blueview_drafts_x === 'keep', 'other keys are untouched');
  }

  console.log('\n2. THE HOOK, RUN THROUGH THE SEQUENCE THAT LEAKED');
  async function runHook({ device, signedIn, serverProfile, serverFails }) {
    const calls = { put: [] };
    const state = {};
    let hookIndex = 0;
    const React = {
      useState: (init) => {
        const i = hookIndex; hookIndex += 1;
        if (!(i in state)) state[i] = init;
        return [state[i], (v) => { state[i] = typeof v === 'function' ? v(state[i]) : v; }];
      },
      useRef: (init) => ({ current: init }),
      useEffect: (fn) => { fn(); },
    };
    const user = { current: signedIn };
    const api = {
      cpProfileAPI: {
        getProfile: async () => {
          if (serverFails) throw new Error('offline');
          return serverProfile;
        },
        updateProfile: async (body) => { calls.put.push(body); return {}; },
      },
      getStoredUser: async () => (user.current ? { id: user.current } : null),
    };
    const hook = loadEsm('src/hooks/useCpProfile.js', {
      stubs: {
        react: React,
        '../utils/api': api,
        '@react-native-async-storage/async-storage': { __esModule: true, default: device },
      },
      globals: { console: { warn() {}, log() {}, error() {} } },
    });
    const out = hook.useCpProfile();
    await new Promise((r) => setTimeout(r, 20));
    return { out, state, calls, user };
  }

  {
    // Shawn's profile on the phone under the OLD key; Michael signs in; no signal.
    const device = store({ blueview_cp_profile: LEGACY });
    const { state } = await runHook({ device, signedIn: 'michael', serverFails: true });
    ok(state[0] === '' && state[1] === null,
      'offline, Michael\'s editor starts with NO name and NO signature -- not Shawn\'s');
    ok(!('blueview_cp_profile' in device.data),
      'and the old device-wide value is gone from the phone');
  }
  {
    // THE ACCOUNT CHANGES UNDER A MOUNTED EDITOR: loaded for Shawn, saved as Michael.
    const device = store();
    const run = await runHook({ device, signedIn: 'shawn',
      serverProfile: { cp_name: 'shawn', cp_signature: SHAWN_SIG } });
    run.user.current = 'michael';
    await run.out.autoSave('shawn', { ...SHAWN_SIG, paths: [[{ x: 3, y: 3 }]] });
    ok(run.calls.put.length === 0,
      'a profile loaded for Shawn is never PUT once Michael is the one signed in');
    ok(!('blueview_cp_profile:michael' in device.data),
      'and nothing is cached under Michael either');
  }
  {
    // The ordinary case still works: his own name and signature, saved for him.
    const device = store();
    const run = await runHook({ device, signedIn: 'michael',
      serverProfile: { cp_name: 'Michael Cespedes', cp_signature: MICHAEL_SIG } });
    ok(run.state[0] === 'Michael Cespedes', 'his own profile loads from the server');
    await run.out.autoSave('Michael Cespedes', { ...MICHAEL_SIG, paths: [[{ x: 8, y: 8 }]] });
    ok(run.calls.put.length === 1, 'a changed signature of his own is saved to his profile');
    ok('blueview_cp_profile:michael' in device.data
       && JSON.parse(device.data['blueview_cp_profile:michael']).user_id === 'michael',
    'and cached under his account, owned by him');
  }

  console.log('\n3. LOGOUT CLEARS EVERY SAVED PROFILE');
  {
    const S = store({
      blueview_cp_profile: LEGACY,
      'blueview_cp_profile:shawn': '{}',
      'blueview_cp_profile:michael': '{}',
      blueview_token: 't',
      blueview_offline_drafts: 'keep',
    });
    const C = cacheWith(S);
    await C.clearAllCpProfiles();
    ok(!Object.keys(S.data).some((k) => k.startsWith('blueview_cp_profile')),
      'the legacy key and every account\'s profile are gone');
    ok(S.data.blueview_offline_drafts === 'keep', 'an unrelated key survives');
    const api = fs.readFileSync(path.join(__dirname, 'api.js'), 'utf8');
    const clear = api.slice(api.indexOf('export const clearAuth'), api.indexOf('};', api.indexOf('export const clearAuth')));
    ok(/await clearAllCpProfiles\(\);/.test(clear), 'clearAuth -- every logout path -- calls it');
  }

  console.log('\n4. NOTHING ELSE READS THE OLD KEY');
  {
    const hookSrc = fs.readFileSync(path.join(__dirname, '..', 'hooks', 'useCpProfile.js'), 'utf8');
    ok(!/AsyncStorage/.test(hookSrc.replace(/\/\*[\s\S]*?\*\//g, '')),
      'the hook no longer touches AsyncStorage directly -- only through the per-account module');
    ok(/if \(!ownerRef\.current \|\| current !== ownerRef\.current\) return;/.test(hookSrc),
      'autoSave asks whose values these are before saving');
  }

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
