/**
 * RE-ADDING A REMOVED PERSON RESTORES HIS OLD ACCOUNT, AND THE SCREEN SAYS SO.
 *
 * Roy, 2026-11-06: Add user with the email of a removed account in the same
 * company restores that account (same id, history kept) and POST /admin/users
 * answers `restored: true`. app/admin/users.jsx must tell the admin, in EN and
 * ES, rather than report "User created".
 *
 * Run: node src/utils/adminUserReadd.test.cjs
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
function load(rel) {
  const file = path.join(FRONTEND, rel);
  const { code } = babel.transformSync(fs.readFileSync(file, 'utf8'), {
    filename: file,
    plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')],
    configFile: false,
    babelrc: false,
  });
  const m = {};
  // eslint-disable-next-line no-new-func
  new Function('exports', 'module', 'require', code)(m, { exports: m }, require);
  return m;
}

const en = load('src/i18n/en.js').default;
const es = load('src/i18n/es.js').default;
const screen = fs.readFileSync(path.join(FRONTEND, 'app/admin/users.jsx'), 'utf8')
  .replace(/(^|[^:'"`\\])\/\/.*$/gm, '$1');

// The create handler: from the create call to the end of its success toast.
const at = screen.indexOf('adminUsersAPI.create(');
const handler = at >= 0 ? screen.slice(at, at + 900) : '';
ok(at >= 0, 'the screen creates users through adminUsersAPI.create');
ok(/const\s+(\w+)\s*=\s*await\s+adminUsersAPI\.create\(/.test(screen),
  'the create answer is kept, not thrown away');
ok(/\.restored\s*===\s*true/.test(handler), 'the handler branches on restored === true');
ok(/useT\(['"]adminUserReadd['"]\)/.test(screen), 'the screen uses the adminUserReadd strings');
ok(/tReadd\('title'\)/.test(handler) && /tReadd\('body'\)/.test(handler),
  'a restore toasts the restore copy');

const enR = en.adminUserReadd || {};
const esR = es.adminUserReadd || {};
for (const k of ['title', 'body']) {
  ok(typeof enR[k] === 'string' && enR[k].trim(), `en.adminUserReadd.${k}`);
  ok(typeof esR[k] === 'string' && esR[k].trim() && esR[k] !== enR[k],
    `es.adminUserReadd.${k} is translated`);
}

console.log(`\n  ${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
