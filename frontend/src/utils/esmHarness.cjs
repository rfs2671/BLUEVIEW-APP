/**
 * LOAD A REAL ESM MODULE UNDER PLAIN NODE.
 *
 * NOT A TEST. A shared harness, required by the *.test.cjs files that need to
 * execute shipped source. The filename deliberately does not end in .test.cjs
 * so the suite runner does not collect it.
 *
 * WHY IT EXISTS. The suite is plain node — no jest, no react-native preset — so
 * `require('@react-native-community/netinfo')` cannot work. The technique that
 * grew up around that was to read the source and delete its imports by regex:
 *
 *     const body = src
 *       .replace(/^import[\s\S]*?;\s*$/gm, '')
 *       .replace(/^export (async function|function|const) /gm, '$1 ');
 *     new Function('__env', `
 *       const AsyncStorage = __env.AsyncStorage;
 *       const NetInfo = __env.NetInfo;
 *       ...
 *       ${body}
 *     `)(env);
 *
 * That works, and it costs three things.
 *
 * 1. IT CANNOT TELL A LOADABLE IMPORT FROM AN UNLOADABLE ONE. The strip is
 *    line-based, so `./signatureAffirmed` — which imports nothing and would
 *    load cleanly — was deleted along with NetInfo. draftSync therefore carried
 *    a hand-copy of isAffirmedSignature, held in step with the real one by a
 *    string-equality assertion in signatureAffirmed.test.cjs. A copied
 *    predicate kept in sync by string comparison is the shape that produced
 *    stripAffirmation: three named literals, an attestation that grew a fourth
 *    field, and nothing that failed.
 *
 * 2. A MISSING DECLARATION IS SILENT UNTIL IT IS REACHED. draftSync imports
 *    `writeDraft` and `uploadPendingActivityPhotos`; submitSignatureGate and
 *    draftSync.finalizeGate declared neither. They passed because no exercised
 *    path touched them — a latent ReferenceError, one refactor away from
 *    becoming a confusing failure in an unrelated test.
 *
 * 3. IT SILENTLY ACCEPTS A HALF-STUBBED MODULE. `import { getPendingKeys } from
 *    './logbookDrafts'` compiles to a property read, so a stub missing that key
 *    yields `undefined` rather than an error.
 *
 * WHAT THIS DOES INSTEAD. Babel transforms ESM to CommonJS — the same loader
 * already used by logbookEditable, credentialStrip, signatureInk,
 * affirmationRefusalCopy and signatureAffirmedLang — and the module's `require`
 * is a shim under the caller's control:
 *
 *   a RELATIVE import   loads FOR REAL, recursively, unless stubbed. So
 *                       `./signatureAffirmed` resolves to the shipped module
 *                       and there is nothing left to duplicate.
 *   a BARE import       must be stubbed. Unstubbed throws, naming the specifier
 *                       and the file that imported it — the RN and Expo
 *                       packages this suite genuinely cannot load, surfaced as
 *                       one legible error instead of a deleted line.
 *
 * Every stub is wrapped so that reading a key it does not define THROWS and
 * names the key. That is point 2 and point 3 closed: the harness reports what
 * the module under test actually needs.
 */
const fs = require('fs');
const path = require('path');
const babel = require('@babel/core');

const FRONTEND = path.join(__dirname, '..', '..');

/**
 * Properties a stub may be asked for without having declared them.
 *
 * `__esModule` and `default` are babel's interop protocol, not the module's
 * API: `_interopRequireDefault` reads `__esModule` on every default import, and
 * a falsy answer is the correct one for a plain object. The rest are what
 * node, promise plumbing and console formatting probe on arbitrary values.
 */
const INTEROP_KEYS = new Set([
  '__esModule', 'default', 'then', 'catch', 'constructor', 'prototype',
  'toJSON', 'inspect', 'nodeType',
]);

/**
 * A stub that refuses to answer for a key it does not define.
 *
 * The point of the whole file: a module importing `writeDraft` from a stub that
 * has no `writeDraft` should say so, at the moment it is read, rather than hand
 * back undefined and fail somewhere else — or not at all.
 */
function strictStub(specifier, obj, importer) {
  if (obj === null || typeof obj !== 'object') return obj;
  return new Proxy(obj, {
    get(target, prop, recv) {
      if (typeof prop === 'symbol' || INTEROP_KEYS.has(prop) || prop in target) {
        return Reflect.get(target, prop, recv);
      }
      throw new Error(
        `harness stub for '${specifier}' has no '${String(prop)}', but `
        + `${path.basename(importer)} imports it. Add it to the stub — a `
        + 'missing key is a real gap in the harness, not noise.',
      );
    },
    has(target, prop) {
      return INTEROP_KEYS.has(prop) || Reflect.has(target, prop);
    },
  });
}

function transformToCjs(file) {
  return babel.transformSync(fs.readFileSync(file, 'utf8'), {
    filename: file,
    plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')],
    configFile: false,
    babelrc: false,
  }).code;
}

/**
 * What a file imports, read from the AST rather than guessed with a regex.
 *
 * Returns [{ source, named: [...], needsDefault: bool }]. The point is EAGER
 * checking: babel compiles `import { readDraft } from './logbookDrafts'` into a
 * property read at the USE site, so a stub missing that key does not fail when
 * the module loads — it fails later, or never, which is the behaviour this file
 * exists to end. Knowing the import list up front turns that into an error at
 * load, naming the key.
 *
 * Regexes are what the old harness used, and a line-based one is why
 * `./signatureAffirmed` got deleted along with NetInfo. Parsing with the real
 * parser is the whole idea.
 */
function importsOf(file) {
  const ast = babel.parseSync(fs.readFileSync(file, 'utf8'), {
    filename: file,
    configFile: false,
    babelrc: false,
    sourceType: 'module',
  });
  const out = [];
  for (const node of ast.program.body) {
    if (node.type !== 'ImportDeclaration') continue;
    const named = [];
    let needsDefault = false;
    for (const spec of node.specifiers) {
      if (spec.type === 'ImportSpecifier') {
        named.push(spec.imported.name ?? spec.imported.value);
      } else {
        // default or namespace — satisfied by the stub object itself
        needsDefault = true;
      }
    }
    out.push({ source: node.source.value, named, needsDefault });
  }
  return out;
}

/** The file a relative specifier points at, trying the usual extensions. */
function resolveRelative(specifier, fromFile) {
  const base = path.resolve(path.dirname(fromFile), specifier);
  const candidates = [
    base, `${base}.js`, `${base}.jsx`, `${base}.cjs`,
    path.join(base, 'index.js'), path.join(base, 'index.jsx'),
  ];
  for (const c of candidates) {
    if (fs.existsSync(c) && fs.statSync(c).isFile()) return c;
  }
  throw new Error(`harness cannot resolve '${specifier}' from ${fromFile}`);
}

/**
 * Execute an ESM module under node.
 *
 * @param relPath  path to the module, relative to `frontend/`
 * @param stubs    { specifier: object } — bare specifiers MUST appear here;
 *                 a relative specifier may appear here to override the real
 *                 module. A stub carrying both a default and named exports
 *                 declares `__esModule: true` and a `default` key, which is
 *                 the same contract babel's interop uses.
 * @param globals  { name: value } injected as parameters, so they SHADOW the
 *                 real global inside the module — how `console`, `fetch` and
 *                 `FormData` get silenced or faked without touching globalThis.
 */
function loadEsm(relPath, { stubs = {}, globals = {} } = {}) {
  const cache = new Map();

  function load(file) {
    if (cache.has(file)) return cache.get(file);
    const mod = { exports: {} };
    cache.set(file, mod.exports);

    // EAGER, BEFORE ANYTHING RUNS. Every named import this file makes is
    // checked against its stub now, so a gap is one error at load naming the
    // key and the importer — not an `undefined` that surfaces elsewhere, and
    // not a ReferenceError from inside generated source.
    for (const imp of importsOf(file)) {
      if (!Object.prototype.hasOwnProperty.call(stubs, imp.source)) continue;
      const stub = stubs[imp.source];
      if (stub === null || typeof stub !== 'object') continue;
      const missing = imp.named.filter((n) => !(n in stub));
      if (missing.length) {
        throw new Error(
          `harness stub for '${imp.source}' has no ${missing.map((m) => `'${m}'`).join(', ')}, `
          + `but ${path.basename(file)} imports it. Add it to the stub — a missing `
          + 'key is a real gap in the harness, not noise.',
        );
      }
    }

    const shim = (specifier) => {
      if (Object.prototype.hasOwnProperty.call(stubs, specifier)) {
        return strictStub(specifier, stubs[specifier], file);
      }
      if (specifier.startsWith('.')) {
        // REAL, and recursively. This is the line that removed the need for a
        // duplicated predicate.
        return load(resolveRelative(specifier, file));
      }
      throw new Error(
        `harness has no stub for '${specifier}', imported by `
        + `${path.basename(file)}. This suite runs on plain node, so a `
        + 'react-native / expo / axios package cannot be loaded — stub it '
        + 'explicitly rather than letting the import disappear.',
      );
    };

    const names = ['module', 'exports', 'require', ...Object.keys(globals)];
    const values = [mod, mod.exports, shim, ...Object.values(globals)];
    // eslint-disable-next-line no-new-func
    new Function(...names, transformToCjs(file))(...values);
    cache.set(file, mod.exports);
    return mod.exports;
  }

  return load(path.join(FRONTEND, relPath));
}

module.exports = { loadEsm, strictStub };
