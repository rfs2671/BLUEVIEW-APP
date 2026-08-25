#!/usr/bin/env node
/**
 * Find identifiers that resolve to nothing, which throw ReferenceError.
 *
 * WHAT THIS EXISTS FOR. `app/demo.jsx` used `semantic.attention` while
 * importing only `withAlpha` from the same module. That is a hard
 * ReferenceError on first render, and it sat on main for four weeks — through
 * every build, including the one Apple was reviewing — because nothing looked.
 * It is the screen a self-registered account lands on, so it was the first
 * screen Apple's reviewer would have seen after signing up.
 *
 * Sweeping for it found three MORE of the identical shape, each one waiting on
 * a branch nobody had taken in CI:
 *
 *   admin/safety-staff.jsx           `styles`     (the file's local is `s`)
 *   projects/[id]/construction-plans `colors`     (module-scope helper)
 *   workers/[id].jsx                 `apiClient`  (imported the named export only)
 *
 * A grep cannot find these: the defect is not a string, it is the ABSENCE of a
 * binding. Only scope resolution can see it. This walks each file's scope chain
 * with Babel and reports every identifier that resolves to neither a local, a
 * parameter, an import, nor a real runtime global.
 *
 * WHY IT IS NOT COVERED BY THE OTHER GUARDS. find-bare-jsx-text.cjs parses for
 * a different defect (text outside <Text>). The .test.cjs suites read source as
 * text and assert on substrings — they can prove a call site EXISTS, never that
 * its identifiers RESOLVE. Nothing in this repo executes these screens.
 *
 * FALSE NEGATIVES, deliberately. Anything on the GLOBALS list below is assumed
 * to exist at runtime. That list is the only tuning surface; if a genuine
 * runtime global is missing, add it there rather than skipping a file. There is
 * no per-file allowlist, because a list of known-broken files is how this class
 * of defect survives a guard.
 *
 *   node frontend/scripts/find-unbound-identifiers.cjs
 *
 * Exit 1 if anything is found, so it gates CI.
 */
const fs = require('fs');
const path = require('path');
const babel = require('@babel/core');
const traverse = require('@babel/traverse').default;

const ROOT = path.join(__dirname, '..');

/**
 * Identifiers that genuinely exist at runtime and so are not defects.
 *
 * Scoped to what a React Native + react-native-web bundle actually provides.
 * Deliberately NOT the full browser global list: `name`, `status`, `length`,
 * `event` and friends are real `window` properties, and treating them as
 * globals would silently swallow the exact typo this script is for.
 */
const GLOBALS = new Set([
  // ECMAScript
  'undefined', 'NaN', 'Infinity', 'globalThis',
  'Object', 'Array', 'String', 'Number', 'Boolean', 'Symbol', 'BigInt',
  'Function', 'Math', 'JSON', 'Date', 'RegExp', 'Promise', 'Proxy', 'Reflect',
  'Map', 'Set', 'WeakMap', 'WeakSet', 'Intl',
  'Error', 'TypeError', 'RangeError', 'SyntaxError', 'ReferenceError',
  'parseInt', 'parseFloat', 'isNaN', 'isFinite',
  'encodeURIComponent', 'decodeURIComponent', 'encodeURI', 'decodeURI',
  'ArrayBuffer', 'DataView', 'Uint8Array', 'Uint8ClampedArray', 'Int8Array',
  'Uint16Array', 'Int16Array', 'Uint32Array', 'Int32Array',
  'Float32Array', 'Float64Array', 'structuredClone', 'queueMicrotask',
  // CommonJS / Metro
  'require', 'module', 'exports', 'process', 'Buffer', '__DEV__',
  '__filename', '__dirname',
  // React Native runtime
  'console', 'setTimeout', 'clearTimeout', 'setInterval', 'clearInterval',
  'setImmediate', 'clearImmediate', 'requestAnimationFrame',
  'cancelAnimationFrame', 'fetch', 'Headers', 'Request', 'Response',
  'FormData', 'Blob', 'File', 'FileReader', 'URL', 'URLSearchParams',
  'AbortController', 'AbortSignal', 'XMLHttpRequest', 'WebSocket',
  'TextEncoder', 'TextDecoder', 'atob', 'btoa', 'performance', 'crypto',
  'alert', 'navigator',
  // Web-only surfaces. Reachable in this codebase because it also builds for
  // web; call sites are expected to guard with Platform.OS === 'web'.
  'window', 'document', 'localStorage', 'sessionStorage', 'location',
  'HTMLElement', 'Image', 'Event', 'CustomEvent', 'MutationObserver',
  'ResizeObserver', 'IntersectionObserver', 'getComputedStyle', 'matchMedia',
]);

const SKIP_DIRS = new Set(['node_modules', 'dist', '.expo', 'android', 'ios', 'build']);

/** Every source file the app bundles. Tests and scripts are not app code. */
function sourceFiles(dir, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name.startsWith('.') || SKIP_DIRS.has(e.name)) continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) sourceFiles(p, out);
    else if (/\.(js|jsx)$/.test(e.name) && !/\.test\.(c?js)$/.test(e.name)) out.push(p);
  }
  return out;
}

const files = [
  ...sourceFiles(path.join(ROOT, 'app')),
  ...sourceFiles(path.join(ROOT, 'src')),
].concat(fs.existsSync(path.join(ROOT, 'App.js')) ? [path.join(ROOT, 'App.js')] : []);

const findings = [];
const parseFailures = [];

for (const file of files) {
  let ast;
  try {
    ast = babel.parseSync(fs.readFileSync(file, 'utf8'), {
      filename: file,
      presets: [require.resolve('babel-preset-expo')],
      ast: true,
      code: false,
      configFile: false,
      babelrc: false,
    });
  } catch (err) {
    // A file that will not parse cannot be cleared, so this is a failure and
    // not a skip. Silently passing an unparseable file is how a guard lies.
    parseFailures.push([file, err.message.split('\n')[0]]);
    continue;
  }

  let program = null;
  traverse(ast, { Program(p) { program = p; } });
  if (!program) continue;

  for (const [name, binding] of Object.entries(program.scope.globals)) {
    if (GLOBALS.has(name)) continue;
    findings.push({
      file: path.relative(ROOT, file),
      name,
      line: (binding.loc && binding.loc.start.line) || 0,
    });
  }
}

for (const [file, msg] of parseFailures) {
  console.log(`PARSE FAILED  ${path.relative(ROOT, file)}\n    ${msg}`);
}

if (findings.length) {
  console.log(`\n${findings.length} identifier(s) resolve to nothing and will throw ReferenceError:\n`);
  let last = null;
  for (const f of findings.sort((a, b) => a.file.localeCompare(b.file) || a.line - b.line)) {
    if (f.file !== last) { console.log(`  ${f.file}`); last = f.file; }
    console.log(`    :${f.line}  ${f.name}`);
  }
  console.log('\nEach is a missing import, a renamed local, or a typo. If one is a real');
  console.log('runtime global, add it to GLOBALS in this script — do not skip the file.');
}

console.log(`\n${files.length} files scanned, ${findings.length} unbound, ${parseFailures.length} unparseable`);

if (findings.length || parseFailures.length) process.exit(1);
console.log('No unbound identifiers.');
