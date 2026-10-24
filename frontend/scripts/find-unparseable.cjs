#!/usr/bin/env node
/**
 * Every .js / .jsx file in frontend/ must PARSE, with the bundler's own preset.
 *
 * WHAT THIS EXISTS FOR. On 2026-10-23 merging main into #849 kept both sides of
 * an i18n conflict as ruled, and git ALSO auto-merged the same
 * `import { useT } from '../../../src/i18n';` line from both sides into
 * app/project/[id]/dob-logs.jsx with no conflict marker. Two imports of one
 * binding do not parse ("Identifier 'useT' has already been declared"), so the
 * Compliance screen would not have built. The i18n parity test passed on it.
 *
 * find-unbound-identifiers.cjs already fails on an unparseable file, but only
 * under app/ and src/ (it resolves scopes, which node-run config files would
 * drown in false positives). The files it does not reach -- app.config.js,
 * babel.config.js, metro.config.js, scripts/*.js -- break every build when
 * they break. This sweep is parse-only, so it covers ALL of them, and it is
 * named for the one property it checks.
 *
 * A DUPLICATE IMPORT IS A PARSE FAILURE HERE ONLY WHEN IT REBINDS A NAME. The
 * same module imported on two lines with different names (a default import and
 * a named one) is legal JavaScript and appears 16 times on main; failing on it
 * would be noise, so it is not checked.
 *
 *   node frontend/scripts/find-unparseable.cjs              # sweep frontend/
 *   node frontend/scripts/find-unparseable.cjs --self-test  # the gate can fail
 *   node frontend/scripts/find-unparseable.cjs --files a.jsx b.js
 *
 * Exit 1 on any file that does not parse (or a self-test that does not hold).
 */
const fs = require('fs');
const path = require('path');
const babel = require('@babel/core');

const ROOT = path.join(__dirname, '..');
const SKIP_DIRS = new Set(['node_modules', 'dist', '.expo', 'android', 'ios', 'build', 'web-build']);

function jsFiles(dir, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name.startsWith('.') || SKIP_DIRS.has(e.name)) continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) jsFiles(p, out);
    else if (/\.(js|jsx)$/.test(e.name)) out.push(p);
  }
  return out;
}

/** null if `code` parses, else the first line of the parser's message. */
function parseError(code, filename) {
  try {
    babel.parseSync(code, {
      filename,
      presets: [require.resolve('babel-preset-expo')],
      configFile: false,
      babelrc: false,
    });
    return null;
  } catch (err) {
    return err.message.split('\n')[0];
  }
}

function selfTest() {
  // Each case says what the gate must answer. A gate that passes everything
  // passes the sweep too, so the sweep alone proves nothing.
  const cases = [
    ['parses', false, "import { useT } from './i18n';\nexport default () => useT('x');\n"],
    ['the #849 merge: one binding imported twice', true,
      "import { useT } from './i18n';\nimport Other from './other';\nimport { useT } from './i18n';\n"],
    ['plain syntax error', true, 'const a = ;\n'],
    ['same module, different names (legal)', false,
      "import api from './api';\nimport { get } from './api';\nexport { api, get };\n"],
    ['CommonJS config file', false, 'module.exports = { presets: [] };\n'],
  ];
  let bad = 0;
  for (const [name, shouldFail, code] of cases) {
    const failed = parseError(code, 'self-test.jsx') !== null;
    const ok = failed === shouldFail;
    if (!ok) bad += 1;
    console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}: ${failed ? 'rejected' : 'accepted'}`);
  }
  console.log(bad ? `\n${bad} self-test case(s) wrong` : '\nself-test holds');
  return bad === 0;
}

function main(argv) {
  if (argv.includes('--self-test')) return selfTest() ? 0 : 1;
  const i = argv.indexOf('--files');
  const files = i >= 0 ? argv.slice(i + 1).map((f) => path.resolve(f)) : jsFiles(ROOT);
  const failures = [];
  for (const f of files) {
    const err = parseError(fs.readFileSync(f, 'utf8'), f);
    if (err) failures.push([path.relative(ROOT, f), err]);
  }
  for (const [f, err] of failures) console.log(`  ${f}: ${err}`);
  console.log(`\n${files.length} files parsed, ${failures.length} unparseable`);
  return failures.length ? 1 : 0;
}

process.exit(main(process.argv.slice(2)));
