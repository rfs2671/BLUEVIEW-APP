/**
 * ANDROID SAVES A DOWNLOAD STRAIGHT INTO DOWNLOADS; IPHONE KEEPS THE SHARE
 * SHEET BEHIND A BUTTON LABELLED "SAVE".
 *
 *   1. saveToDownloads.js, driven: the folder is asked for once (explained
 *      first), remembered, reused without a prompt, asked again when its grant
 *      is gone; a decline saves nothing; a failed write leaves no empty file
 *      and is thrown so the screen can fall back to the share sheet;
 *   2. the Plans & Files screen: Android saves and returns before the share
 *      sheet, says "Saved to Downloads", and iPhone's button is labelled Save;
 *   3. every new string has EN and ES copy;
 *   4. OTA only: nothing the 1.3.0 binary lacks.
 *
 * CONTROL: on main, saveToDownloads.js does not exist and the screen shares
 * on Android, so sections 1-3 fail.
 *
 * Run: node src/utils/saveToDownloads.test.cjs
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
const read = (rel) => {
  try { return fs.readFileSync(path.join(FRONTEND, rel), 'utf8'); } catch (_e) { return ''; }
};

function load(rel, stubs = {}) {
  const file = path.join(FRONTEND, rel);
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

function stripJs(src) {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:'"`\\])\/\/.*$/gm, '$1')
    .replace(/\{\s*\/\*[\s\S]*?\*\/\s*\}/g, '');
}

const DOWNLOAD_ROOT = 'content://com.android.externalstorage.documents/tree/primary:Download/document/primary:Download';
const LEVELOG = 'content://com.android.externalstorage.documents/tree/primary%3ADownload%2FLeveLog';
const OTHER = 'content://com.android.externalstorage.documents/tree/primary%3ADownload%2FPlans';
const SRC = 'file:///cache/downloads/ab/A-101 Plan.pdf';
const FILE = { id: 'f1', name: 'A-101 Plan.pdf', size: 3 };

function harness({ remembered = null, pick = { granted: true, directoryUri: LEVELOG }, revoked = [], failWrite = false, confirm = true } = {}) {
  const store = new Map(remembered ? [['bv_android_save_dir', remembered]] : []);
  const calls = { confirm: 0, picker: [], created: [], written: [], deleted: [], base64: 0 };
  const SAF = {
    getUriForDirectoryInRoot: (f) => `content://com.android.externalstorage.documents/tree/primary:${f}/document/primary:${f}`,
    requestDirectoryPermissionsAsync: async (initial) => { calls.picker.push(initial); return pick; },
    createFileAsync: async (dir, name, mime) => {
      if (revoked.includes(dir)) throw new Error('No permission');
      const uri = `${dir}/document/${encodeURIComponent(name)}`;
      calls.created.push({ dir, name, mime, uri });
      return uri;
    },
    deleteAsync: async (uri) => { calls.deleted.push(uri); },
    writeAsStringAsync: async () => { calls.base64 += 1; },
    readAsStringAsync: async () => { calls.base64 += 1; return ''; },
  };
  class FakeFile {
    constructor(uri) { this.uri = uri; }
    async bytes() { return new Uint8Array([1, 2, 3]); }
    write(bytes) {
      if (failWrite) throw new Error('disk full');
      calls.written.push({ uri: this.uri, n: bytes.length });
    }
  }
  const mod = load('src/utils/saveToDownloads.js', {
    'expo-file-system': { File: FakeFile },
    'expo-file-system/legacy': { StorageAccessFramework: SAF },
    '@react-native-async-storage/async-storage': {
      __esModule: true,
      default: {
        getItem: async (k) => (store.has(k) ? store.get(k) : null),
        setItem: async (k, v) => { store.set(k, v); },
        removeItem: async (k) => { store.delete(k); },
      },
    },
    './fileDownloadPlan': load('src/utils/fileDownloadPlan.js'),
  });
  const confirmFirstPick = async () => { calls.confirm += 1; return confirm; };
  return { mod, calls, store, confirmFirstPick };
}

(async () => {
  const exists = !!read('src/utils/saveToDownloads.js');
  ok(exists, 'src/utils/saveToDownloads.js exists');

  // ── 1. the save, driven ─────────────────────────────────────────────────
  console.log('\nAndroid: the folder is asked for once, then every save goes straight in');
  if (exists) {
    {
      const { mod, calls, store, confirmFirstPick } = harness();
      const res = await mod.saveToAndroidDownloads(SRC, FILE, { confirmFirstPick });
      ok(calls.confirm === 1, 'first save: the reason is shown before the system picker');
      ok(calls.picker.length === 1 && calls.picker[0] === DOWNLOAD_ROOT,
        `the picker opens IN Downloads (${calls.picker[0]})`);
      ok(store.get('bv_android_save_dir') === LEVELOG, 'the granted folder is remembered');
      ok(calls.created.length === 1 && calls.created[0].dir === LEVELOG
        && calls.created[0].name === 'A-101 Plan.pdf' && calls.created[0].mime === 'application/pdf',
        'the file is created in that folder under its own name, as a PDF');
      ok(calls.written.length === 1 && calls.written[0].uri === calls.created[0].uri && calls.written[0].n === 3,
        'and its bytes are written into it');
      ok(res.saved === true && res.folder === 'Download/LeveLog' && res.name === 'A-101 Plan.pdf',
        `the result names the file and the folder (${JSON.stringify(res)})`);
      ok(calls.base64 === 0, 'bytes, never a base64 string of a 100 MB plan set');
    }
    {
      const { mod, calls, confirmFirstPick } = harness({ remembered: LEVELOG });
      const res = await mod.saveToAndroidDownloads(SRC, FILE, { confirmFirstPick });
      ok(res.saved && calls.confirm === 0 && calls.picker.length === 0,
        'second save: no explanation, no picker, no share sheet: straight into the folder');
    }
    {
      const { mod, calls, store, confirmFirstPick } = harness({
        remembered: OTHER, revoked: [OTHER],
      });
      const res = await mod.saveToAndroidDownloads(SRC, FILE, { confirmFirstPick });
      ok(res.saved && calls.picker.length === 1 && store.get('bv_android_save_dir') === LEVELOG,
        'a remembered folder that was deleted or revoked is forgotten and asked for again in the same tap');
    }
    {
      const { mod, calls, store, confirmFirstPick } = harness({ confirm: false });
      const res = await mod.saveToAndroidDownloads(SRC, FILE, { confirmFirstPick });
      ok(res.saved === false && calls.picker.length === 0 && !store.has('bv_android_save_dir'),
        'declining the explanation opens no picker and saves nothing');
    }
    {
      const { mod, calls, store, confirmFirstPick } = harness({ pick: { granted: false } });
      const res = await mod.saveToAndroidDownloads(SRC, FILE, { confirmFirstPick });
      ok(res.saved === false && calls.created.length === 0 && !store.has('bv_android_save_dir'),
        'backing out of the picker saves nothing and remembers nothing');
    }
    {
      const { mod, calls, confirmFirstPick } = harness({ failWrite: true });
      let threw = false;
      try { await mod.saveToAndroidDownloads(SRC, FILE, { confirmFirstPick }); } catch (_e) { threw = true; }
      ok(threw, 'a write that fails in a folder granted just now is thrown (the screen falls back to share)');
      ok(calls.deleted.length === 1 && calls.deleted[0] === calls.created[0].uri,
        'and the empty file it created is removed, not left in Downloads');
    }
    ok(mod2Label('content://com.android.externalstorage.documents/tree/primary%3ADownload') === 'Download'
      && mod2Label('garbage') === '', 'folderLabel reads a tree URI and gives nothing for anything else');
  }

  // ── 2. the screen ───────────────────────────────────────────────────────
  console.log('\nThe Plans & Files screen');
  const screen = stripJs(read('app/projects/[id]/files.jsx'));
  const handler = screen.slice(screen.indexOf('const handleDownloadFile'), screen.indexOf('const downloadMeta'));
  ok(handler.length > 200, 'the download handler is found (the checks below would pass on an empty slice)');
  const androidAt = handler.indexOf("Platform.OS === 'android'");
  const saveAt = handler.indexOf('saveToAndroidDownloads(');
  const shareAt = handler.indexOf('shareDownloadedFile(');
  ok(androidAt > 0 && saveAt > androidAt && shareAt > saveAt,
    'on Android the file is saved BEFORE any share-sheet call');
  const androidBlock = handler.slice(androidAt, shareAt);
  ok(/return;/.test(androidBlock) && /tDl\('savedTitle'\)/.test(androidBlock),
    'a save says "Saved to Downloads" and returns: no share sheet after it');
  ok(/confirmFirstPick:\s*askWhereToSave/.test(androidBlock),
    'the one-time folder choice is explained first');
  ok(/accessibilityLabel=\{Platform\.OS === 'ios' \? tDl\('saveLabel'\)/.test(screen)
    && /Platform\.OS === 'ios' && \(\s*<Text style=\{s\.fileActionLabel\}>\{tDl\('saveLabel'\)\}<\/Text>/.test(screen),
    'iPhone: the download button is labelled Save (visible and for VoiceOver)');

  // ── 3. EN/ES ────────────────────────────────────────────────────────────
  console.log('\nEN and ES copy');
  const en = read('src/i18n/en.js');
  const es = read('src/i18n/es.js');
  const block = (src) => {
    const at = src.indexOf('fileDownload: {');
    return at < 0 ? '' : src.slice(at, src.indexOf('\n  },', at));
  };
  const keys = ['savedTitle', 'savedBody', 'notSavedTitle', 'noFolder', 'saveFailed',
    'pickTitle', 'pickBody', 'pickGo', 'saveLabel', 'downloadLabel'];
  const missing = keys.filter((k) => !new RegExp(`\\b${k}:`).test(block(en)) || !new RegExp(`\\b${k}:`).test(block(es)));
  ok(missing.length === 0, `every new key has en and es copy${missing.length ? ` — missing: ${missing.join(', ')}` : ''}`);
  ok(/savedTitle: 'Saved to Downloads'/.test(en) && /saveLabel: 'Save'/.test(en)
    && /savedTitle: 'Guardado en Descargas'/.test(es) && /saveLabel: 'Guardar'/.test(es),
    'the wording asked for: "Saved to Downloads" / "Save", and the Spanish');

  // ── 4. OTA only ─────────────────────────────────────────────────────────
  console.log('\nOTA only');
  const src = read('src/utils/saveToDownloads.js');
  const imports = [...src.matchAll(/from '([^']+)'/g)].map((m) => m[1]).sort();
  ok(JSON.stringify(imports) === JSON.stringify([
    './fileDownloadPlan', '@react-native-async-storage/async-storage', 'expo-file-system', 'expo-file-system/legacy',
  ]), `imports only modules the binary carries (${imports.join(', ')})`);
  const pkg = JSON.parse(read('package.json') || '{}');
  ok(/^~?19\./.test(pkg.dependencies?.['expo-file-system'] || '') && /^54/.test(pkg.dependencies?.expo || ''),
    'expo-file-system 19 on SDK 54: the version the 1.3.0 binary was built with');

  console.log(`\n  ${passed} passed, ${failed} failed`);
  if (failed > 0) process.exit(1);
})().catch((e) => { console.error(e); process.exit(1); });

function mod2Label(uri) {
  return harness().mod.folderLabel(uri);
}
