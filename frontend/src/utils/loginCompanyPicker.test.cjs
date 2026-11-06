/**
 * ONE EMAIL, SEVERAL COMPANIES: THE LOGIN SCREEN SHOWS A COMPANY PICKER.
 *
 * Roy, 2026-11-06: an email may hold one account per company. When the
 * password opens more than one of them, POST /api/auth/login answers
 * { choose_company: true, accounts: [{company_name, role, choice_token}] }
 * with NO session token, and the app exchanges the chosen account's
 * choice_token at POST /api/auth/login/choose. Asserted here:
 *
 *   1. readLoginAnswer tells a session from a picker, and a malformed answer
 *      from both;
 *   2. authAPI.login says it can show a picker, stores NO token when it gets
 *      one, and stores the token it does get; chooseLoginCompany posts the
 *      choice and stores the session;
 *   3. a 401 from the choose endpoint (an expired choice) does not destroy a
 *      session already on the device -- it is a login request, not a verdict;
 *   4. AuthContext's login returns the picker BEFORE asking /auth/me, and
 *      takes a choice token to finish; the login screen renders the picker
 *      and finishes through it;
 *   5. every picker string has EN and ES copy.
 *
 * Run: node src/utils/loginCompanyPicker.test.cjs
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
const read = (rel) => fs.readFileSync(path.join(FRONTEND, rel), 'utf8');

function load(rel, stubs = {}) {
  const file = path.join(FRONTEND, rel);
  if (!fs.existsSync(file)) {
    ok(false, `${rel} exists`);
    console.log(`\n  ${passed} passed, ${failed} failed`);
    process.exit(1);
  }
  const { code } = babel.transformSync(fs.readFileSync(file, 'utf8'), {
    filename: file,
    plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')],
    configFile: false,
    babelrc: false,
  });
  const m = {};
  const req = (name) => {
    if (Object.prototype.hasOwnProperty.call(stubs, name)) return stubs[name];
    return require(name);
  };
  // eslint-disable-next-line no-new-func
  new Function('exports', 'module', 'require', code)(m, { exports: m }, req);
  return m;
}

// Comments say what was wrong, in words; strip them before any source scan.
function stripJs(src) {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:'"`\\])\/\/.*$/gm, '$1')
    .replace(/\{\s*\/\*[\s\S]*?\*\/\s*\}/g, '');
}

// The body of `const <name> = async (...) => { ... }` by brace matching.
function arrowBody(src, name) {
  const at = src.indexOf(`const ${name} = async`);
  if (at < 0) return '';
  const open = src.indexOf('{', src.indexOf('=>', at));
  let depth = 0;
  for (let i = open; i < src.length; i += 1) {
    if (src[i] === '{') depth += 1;
    else if (src[i] === '}') { depth -= 1; if (depth === 0) return src.slice(open, i + 1); }
  }
  return '';
}

const choice = load('src/utils/loginChoice.js');
const session = load('src/utils/sessionSurvival.js');
const en = load('src/i18n/en.js').default;
const es = load('src/i18n/es.js').default;

// ── 1. the answer, read ────────────────────────────────────────────────────
console.log('\nreadLoginAnswer');
const picker = choice.readLoginAnswer({
  choose_company: true,
  accounts: [
    { company_name: 'Acme GC', role: 'cp', choice_token: 'c1' },
    { company_name: null, role: 'demo', choice_token: 'c2' },
    { company_name: 'No token', role: 'pm' },
  ],
});
ok(picker.kind === 'choose', 'a picker answer is a choice');
ok(picker.accounts.length === 2, 'a row without a choice token is dropped');
ok(picker.accounts[0].companyName === 'Acme GC' && picker.accounts[0].choiceToken === 'c1',
  'company name and choice token are carried');
ok(picker.accounts[1].companyName === null, 'no company stays null (the screen names it)');
ok(choice.readLoginAnswer({ token: 'a.b.c' }).kind === 'token', 'a token answer is a session');
ok(choice.readLoginAnswer({ choose_company: true, accounts: [] }).kind === 'none',
  'an empty picker is nothing usable, not a picker with no rows');
ok(choice.readLoginAnswer(null).kind === 'none', 'null is nothing usable');
const T = (k) => `<${k}>`;
ok(choice.companyLabel(picker.accounts[1], T) === '<noCompany>', 'no company has its own label');
ok(choice.roleLabel('CP ', T) === '<role_cp>', 'role labels are normalised');
ok(choice.roleLabel('mystery', T) === '', 'an unknown role shows nothing rather than a raw key');

// ── 2. the API calls ───────────────────────────────────────────────────────
console.log('\nauthAPI.login / chooseLoginCompany');
function apiWith(answers) {
  const posts = [];
  const store = {};
  const client = {
    interceptors: { request: { use() {} }, response: { use() {} } },
    post: async (url, body) => { posts.push({ url, body }); return { data: answers[url] }; },
    get: async () => ({ data: {} }),
  };
  const api = load('src/utils/api.js', {
    axios: { create: () => client },
    '@react-native-async-storage/async-storage': {
      getItem: async (k) => (k in store ? store[k] : null),
      setItem: async (k, v) => { store[k] = v; },
      removeItem: async (k) => { delete store[k]; },
    },
    './cpProfileCache': { clearAllCpProfiles: async () => {} },
    'expo-constants': { expoConfig: { version: '9.9.9' } },
    './sessionSurvival': session,
  });
  return { api, posts, store };
}

(async () => {
  {
    const { api, posts, store } = apiWith({
      '/api/auth/login': { choose_company: true, accounts: [{ company_name: 'A', choice_token: 'c1' }] },
    });
    const out = await api.authAPI.login('bob@x.example', 'pw');
    ok(posts[0].url === '/api/auth/login' && posts[0].body.company_picker === true,
      'login tells the server this app can show a picker');
    ok(out.choose_company === true, 'the picker answer is returned to the caller');
    ok(!('blueview_token' in store), 'a picker answer stores NO token');
  }
  {
    const { api, store } = apiWith({ '/api/auth/login': { token: 'tok-1' } });
    await api.authAPI.login('bob@x.example', 'pw');
    ok(store.blueview_token === 'tok-1', 'a single account still stores its token');
  }
  {
    const { api, posts, store } = apiWith({ '/api/auth/login/choose': { token: 'tok-B' } });
    ok(typeof api.authAPI.chooseLoginCompany === 'function', 'chooseLoginCompany exists');
    if (typeof api.authAPI.chooseLoginCompany === 'function') {
      await api.authAPI.chooseLoginCompany('c-B');
      ok(posts[0].url === '/api/auth/login/choose' && posts[0].body.choice_token === 'c-B',
        'the choice is posted to /api/auth/login/choose');
      ok(store.blueview_token === 'tok-B', 'the chosen account\'s session is stored');
    }
  }

  // ── 3. an expired choice is not a verdict on the session ──────────────────
  console.log('\nA 401 from the choose endpoint');
  const live = `x.${Buffer.from(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + 3600 })).toString('base64')}.y`;
  ok(session.unauthorizedVerdict({ url: '/api/auth/login/choose', token: live }) === session.KEEP,
    'keeps whatever session is on the device');

  // ── 4. AuthContext and the screen ─────────────────────────────────────────
  console.log('\nAuthContext.login and app/login.jsx');
  // The body is cut from the RAW source and only then stripped of its line
  // comments: stripJs over the whole file eats the login function, because a
  // `/*` inside an earlier `//` comment opens a "block" that runs into it.
  const body = arrowBody(read('src/context/AuthContext.js'), 'login')
    .replace(/(^|[^:'"`\\])\/\/.*$/gm, '$1');
  ok(body.length > 0, 'AuthContext has a login function');
  const iPick = body.indexOf('choose_company');
  const iMe = body.indexOf('getMe');
  ok(iPick > 0 && iMe > 0 && iPick < iMe,
    'login returns the picker BEFORE asking /auth/me (no session exists yet)');
  ok(/chooseLoginCompany\(/.test(body), 'login finishes a choice through chooseLoginCompany');

  const screen = stripJs(read('app/login.jsx'));
  ok(/useT\(['"]loginPicker['"]\)/.test(screen), 'the login screen uses the loginPicker strings');
  ok(/readLoginAnswer\(/.test(screen), 'the login screen reads the answer with readLoginAnswer');
  ok(/login\(\s*email\s*,\s*password\s*,\s*[A-Za-z_.]*choiceToken/.test(screen),
    'a picked company finishes login with its choice token');
  ok(/\.map\(/.test(screen) && /companyLabel\(/.test(screen), 'one row per company, labelled');

  // ── 5. EN and ES ──────────────────────────────────────────────────────────
  console.log('\nloginPicker copy');
  const enP = en.loginPicker || {};
  const esP = es.loginPicker || {};
  const used = [...new Set([...screen.matchAll(/\bt\(\s*'([A-Za-z_]+)'\s*\)/g)].map((m) => m[1]))];
  ok(used.length >= 3, `the screen asks for picker copy (${used.length} keys)`);
  const keys = Object.keys(enP);
  ok(keys.length > 0, `en.loginPicker has copy (${keys.length} keys)`);
  ok(JSON.stringify(Object.keys(esP).sort()) === JSON.stringify(keys.slice().sort()),
    'es.loginPicker has exactly the same keys');
  const untranslated = keys.filter((k) => esP[k] === enP[k] || !String(esP[k] || '').trim());
  ok(untranslated.length === 0, `every ES string is translated${untranslated.length ? ` — ${untranslated}` : ''}`);
  const missing = used.filter((k) => !(k in enP));
  ok(missing.length === 0, `every key the screen asks for exists${missing.length ? ` — ${missing}` : ''}`);
  for (const k of ['noCompany', 'role_admin', 'role_pm', 'role_cp', 'role_superintendent', 'role_demo']) {
    ok(k in enP, `en.loginPicker.${k} (used by loginChoice.js)`);
  }

  console.log(`\n  ${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})().catch((e) => {
  console.log(`  FAIL  threw: ${e && e.stack}`);
  process.exit(1);
});
