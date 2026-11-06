/**
 * PLAN NOTE "SHARE IMAGE" IN THE PHONE APP -- parity with the web viewer (#946).
 *
 * The phone has no DOM canvas, so the image is drawn by a hidden WebView's
 * <canvas>: planNoteShareNative.js runs the web composer (planNoteShare.js)
 * against a recording canvas, and the page replays the calls. Asserted here,
 * by RUNNING the real page script in a sandbox wired to the real bridge:
 *
 *   1. compose with and without a photo; the page draws exactly the calls the
 *      web composer makes for the same input (layout is not re-implemented);
 *   2. an empty context leaves no blank caption line;
 *   3. the share sheet gets a FILE only: expo-sharing's shareAsync is called
 *      with a file:// uri and {mimeType, UTI}, never a message/text/url/title;
 *   4. a cancelled or dismissed share sheet is quiet (no error copy, no throw);
 *   5. nothing in the share path touches the network (fetch / XHR / beacon /
 *      Linking / a messaging-provider host), and the page's CSP refuses it;
 *   6. PDFViewer.native.jsx renders the Share image button on a saved note for
 *      a user who is neither its author nor an admin, and the panel's controls;
 *   7. EN and ES copy for every key the viewer uses;
 *   8. OTA only: no native module the 1.3.0 binary does not already carry.
 *
 * Run: node src/utils/planNoteShareNative.test.cjs
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const babel = require('@babel/core');

let passed = 0;
let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

const FRONTEND = path.join(__dirname, '..', '..');
const read = (rel) => fs.readFileSync(path.join(FRONTEND, rel), 'utf8').split('\r\n').join('\n');
const exists = (rel) => fs.existsSync(path.join(FRONTEND, rel));

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

const VIEWER = 'src/components/PDFViewer.native.jsx';
const MODULE = 'src/utils/planNoteShareNative.js';
const viewerSrc = read(VIEWER);
const en = load('src/i18n/en.js').default;
const es = load('src/i18n/es.js').default;
const W = load('src/utils/planNoteShare.js');

const b64 = (s) => Buffer.from(String(s), 'utf8').toString('base64');
const unb64 = (s) => Buffer.from(String(s), 'base64').toString('utf8');
const dataImg = (w, h, type = 'image/png') => `data:${type};base64,${b64(`${w}x${h}`)}`;
const tick = () => new Promise((r) => setImmediate(r));

// The web test's recording canvas: methods recorded, `font` sets not recorded,
// measureText = 20 px per character.
function recorder(calls) {
  return new Proxy({}, {
    get(t, k) {
      if (k === 'measureText') return (s) => ({ width: String(s).length * 20 });
      if (k in t) return t[k];
      return (...a) => { calls.push([k, ...a]); };
    },
    set(t, k, v) { t[k] = v; if (k !== 'font') calls.push(['set:' + String(k), v]); return true; },
  });
}

// The same layout through the WEB path, for the parity check.
function webCalls(args) {
  const made = [];
  const createCanvas = (w, h) => {
    const calls = [];
    const c = { width: w, height: h, calls, getContext: () => recorder(calls) };
    made.push(c);
    return c;
  };
  const out = W.composeShareImage({ ...args, createCanvas });
  return { out, calls: out.canvas.calls.map((x) => (x[0] === 'drawImage' ? ['drawImage', x[1].tag, ...x.slice(2)] : x)) };
}

// ── a sandbox that runs the real page script ───────────────────────────────
function makePage(S, { onPost, net, breakDraw = false }) {
  const canvases = [];
  class FakeImage {
    set src(v) {
      this._src = v;
      setImmediate(() => {
        const m = /;base64,(.*)$/.exec(String(v));
        const [w, h] = (m ? unb64(m[1]) : '').split('x').map(Number);
        if (!(w > 0 && h > 0)) { if (this.onerror) this.onerror(new Error('bad')); return; }
        this.naturalWidth = w; this.naturalHeight = h; this.tag = `img${w}x${h}`;
        if (this.onload) this.onload();
      });
    }
    get src() { return this._src; }
  }
  const document = {
    createElement(tag) {
      if (tag !== 'canvas') throw new Error(`page created <${tag}>`);
      const calls = [];
      const c = {
        width: 0, height: 0, calls,
        getContext: () => recorder(calls),
        toDataURL(type) {
          if (breakDraw) throw new Error('canvas exploded');
          return `data:${type};base64,${b64(JSON.stringify({ w: c.width, h: c.height, calls: calls.map((x) => (x[0] === 'drawImage' ? ['drawImage', x[1].tag, ...x.slice(2)] : x)) }))}`;
        },
      };
      canvases.push(c);
      return c;
    },
    addEventListener() {},
  };
  const window = {
    ReactNativeWebView: { postMessage: (s) => setImmediate(() => onPost(s)) },
    addEventListener() {},
    open: (...a) => { net.push(['window.open', a[0]]); },
    location: {},
  };
  const ctx = vm.createContext({
    window, document, Image: FakeImage, Promise, JSON, String, Number, Array, Error, setTimeout,
    fetch: (...a) => { net.push(['fetch', a[0]]); return Promise.reject(new Error('no network')); },
    XMLHttpRequest: function XHR() { net.push(['xhr']); },
    navigator: { sendBeacon: (...a) => { net.push(['beacon', a[0]]); } },
  });
  // the script that ships is the one inside COMPOSER_HTML
  const html = S.COMPOSER_HTML;
  const script = html.slice(html.indexOf('<script>') + 8, html.lastIndexOf('</script>'));
  return { ctx, script, canvases, run: () => vm.runInContext(script, ctx), inject: (js) => vm.runInContext(js, ctx) };
}

function sharingStub({ available = true, share } = {}) {
  const calls = [];
  return {
    calls,
    isAvailableAsync: async () => available,
    shareAsync: async (...a) => { calls.push(a); if (share) return share(...a); return undefined; },
  };
}
function fsStub() {
  const writes = [];
  return {
    writes,
    cacheDirectory: 'file:///data/user/0/com.levelog/cache/',
    EncodingType: { Base64: 'base64', UTF8: 'utf8' },
    writeAsStringAsync: async (uri, data, opts) => { writes.push({ uri, data, opts }); },
  };
}
function manipStub() {
  const calls = [];
  return {
    calls,
    SaveFormat: { JPEG: 'jpeg', PNG: 'png' },
    manipulateAsync: async (uri, actions, opts) => {
      calls.push({ uri, actions, opts });
      const resize = (actions || []).find((a) => a.resize);
      const w = resize ? resize.resize.width : 800;
      const h = Math.round(w * 4 / 3);
      return { uri: `${uri}.out.jpg`, width: w, height: h, base64: opts && opts.base64 ? b64(`${w}x${h}`) : undefined };
    },
  };
}

(async () => {
  console.log('\nThe native share module exists');
  if (!exists(MODULE)) {
    ok(false, `${MODULE} exists (the phone app has no image share path)`);
  }
  let S = null;
  try { S = exists(MODULE) ? load(MODULE, { './planNoteShare': W }) : null; } catch (e) { ok(false, `${MODULE} loads: ${e.message}`); }
  const fns = ['composeInPage', 'sharePlanNoteImage', 'shareImageFile', 'createComposerBridge', 'shareStatusKey'];
  ok(!!S && fns.every((f) => typeof S[f] === 'function'), `exports ${fns.join(', ')}`);
  ok(!!S && typeof S.COMPOSER_HTML === 'string' && S.COMPOSER_HTML.includes('<canvas') === false && /<script>/.test(S.COMPOSER_HTML),
    'exports the composer page (a script, no markup canvas)');

  // ── 6. the viewer renders the button on a saved note ────────────────────
  console.log('\nPDFViewer.native.jsx: the Share image button on a saved note');
  const tShare = (k) => {
    const v = en.planNoteShare && en.planNoteShare[k];
    return v === undefined ? k : v;
  };
  const __R = {
    Fragment: function Fragment(props) { return props.children; },
    createElement: (type, props, ...children) => ({ __el: true, type, props: props || {}, children }),
  };
  function inert(name) {
    const fn = function inertStub() { return null; };
    fn.__stub = name;
    return new Proxy(fn, {
      get(t, k) {
        if (k === '__stub' || typeof k === 'symbol') return t[k];
        if (['call', 'apply', 'bind', 'prototype', 'length', 'name'].includes(k)) return t[k];
        return inert(`${name}.${String(k)}`);
      },
      apply() { return ''; },
    });
  }
  function renderThread(seed) {
    const start = '{/* Bottom sheet: Thread view */}';
    const end = '      </View>\n    </Modal>';
    const from = viewerSrc.indexOf(start);
    const to = viewerSrc.indexOf(end, from);
    if (from < 0 || to < 0) throw new Error('thread view anchors not found');
    const block = viewerSrc.slice(from + start.length, to);
    const code = babel.transformSync(`const __out = (<>${block}</>);`, {
      filename: 'thread.jsx', babelrc: false, configFile: false,
      plugins: [[require.resolve('@babel/plugin-transform-react-jsx'), { runtime: 'classic', pragma: '__R.createElement', pragmaFrag: '__R.Fragment' }]],
    }).code;
    const base = {
      __R, React: __R, Date, String, Number, Array, JSON,
      require: (n) => ({ default: `Module(${n})` }),
      View: 'View', Text: 'Text', Pressable: 'Pressable', ScrollView: 'ScrollView', TextInput: 'TextInput',
      Image: 'Image', ActivityIndicator: 'ActivityIndicator',
      tShare, isImageDataUri: S ? S.isImageDataUri : () => false, COMPOSER_HTML: S ? S.COMPOSER_HTML : undefined,
      composerKey: 0, composerBridge: { current: { onMessage() {}, reset() {} } },
      ...seed,
    };
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
  function walk(node, visit) {
    if (node === null || node === undefined || typeof node === 'boolean') return;
    if (Array.isArray(node)) { node.forEach((n) => walk(n, visit)); return; }
    if (typeof node !== 'object' || !node.__el) return;
    visit(node);
    walk(node.children, visit);
  }
  function texts(tree) {
    const out = [];
    const grab = (n) => {
      if (n === null || n === undefined || typeof n === 'boolean') return;
      if (Array.isArray(n)) { n.forEach(grab); return; }
      if (typeof n === 'string' || typeof n === 'number') { out.push(String(n)); return; }
      if (n.__el) grab(n.children);
    };
    grab(tree);
    return out.join(' | ');
  }
  const findByLabel = (tree, label) => {
    const hits = [];
    walk(tree, (n) => { if (n.props && n.props.accessibilityLabel === label) hits.push(n); });
    return hits;
  };
  const savedNote = {
    _id: 'ann1', comment: 'Lintel cracked', status: 'open', page_number: 1,
    created_by: { _id: 'someone-else', full_name: 'Pat' }, thread: [{ user_name: 'Lee', message: 'Seen it' }],
  };
  const seedBase = {
    selectedAnnotation: savedNote, showNoteSheet: false, shareOpen: false, shareBusy: false,
    sharePhoto: null, shareNote: '', shareContext: '', replyText: '',
    canDelete: () => false, // a CP who did not write the note and is not an admin
  };
  let closed = null; let open = null; let openCrop = null; let pendingNote = null;
  try {
    closed = renderThread(seedBase);
    open = renderThread({ ...seedBase, shareOpen: true });
    openCrop = renderThread({ ...seedBase, shareOpen: true, selectedAnnotation: { ...savedNote, screenshot: dataImg(400, 400) }, sharePhoto: { uri: 'file:///p.jpg', width: 4000, height: 3000 } });
    pendingNote = renderThread({ ...seedBase, selectedAnnotation: null });
  } catch (e) {
    ok(false, `the thread view renders (${e.message})`);
  }
  const btn = closed ? findByLabel(closed, en.planNoteShare && en.planNoteShare.shareImage) : [];
  ok(!!en.planNoteShare && btn.length === 1 && btn[0].type === 'Pressable' && typeof btn[0].props.onPress === 'function',
    'a saved note shows ONE "Share image" button (author: someone else, not an admin)');
  ok(!!closed && texts(closed).includes('Share image'), 'the button carries the visible label "Share image"');
  ok(!!closed && /Lintel cracked/.test(texts(closed)) && !findByLabel(closed, tShare('share')).length,
    'closed: the thread shows, the share panel does not');
  ok(!!pendingNote && texts(pendingNote).trim() === '', 'no note selected: no thread sheet, no button');
  if (open) {
    const t = texts(open);
    ok(findByLabel(open, tShare('takePhoto')).length === 1 && findByLabel(open, tShare('choosePhoto')).length === 1,
      'open: Take photo and Choose photo');
    ok(findByLabel(open, tShare('share')).length === 1 && findByLabel(open, tShare('contextPlaceholder')).length === 1,
      'open: a context box and a Share button');
    ok(t.includes(tShare('noPlanCrop')), 'open, no plan crop on the note: says the image carries photo and caption');
    ok(!/Seen it/.test(t), 'open: the panel takes the thread\'s place (sheet keeps its height)');
    let web = 0;
    walk(open, (n) => { if (n.type === 'Module(react-native-webview)') web += 1; });
    let webClosed = 0;
    walk(closed, (n) => { if (n.type === 'Module(react-native-webview)') webClosed += 1; });
    ok(web === 1 && webClosed === 0, 'the hidden composer WebView is mounted only while the panel is open');
    let composer = null;
    walk(open, (n) => { if (n.type === 'Module(react-native-webview)') composer = n; });
    ok(!!composer && S && composer.props.source && composer.props.source.html === S.COMPOSER_HTML && composer.props.allowFileAccess === false,
      'the composer WebView loads COMPOSER_HTML with no file access');
  } else {
    ok(false, 'open: the share panel renders');
  }
  if (openCrop) {
    const t = texts(openCrop);
    ok(!t.includes(tShare('noPlanCrop')) && t.includes(tShare('photoAttached')) && findByLabel(openCrop, tShare('removePhoto')).length === 1,
      'open with a crop and a photo: no crop warning, photo attached + Remove photo');
  } else ok(false, 'open with a crop and a photo renders');

  // no role gate on the button or in the share handler
  const btnSrc = viewerSrc.slice(Math.max(0, viewerSrc.indexOf("tShare('shareImage')") - 400), viewerSrc.indexOf("tShare('shareImage')") + 200);
  ok(viewerSrc.includes("tShare('shareImage')") && !/canDelete|isCompanyAdmin|\brole\b|isAdmin/.test(btnSrc.slice(btnSrc.indexOf('Mark Resolved') + 1)),
    'the button sits outside any role/permission check');
  const handler = viewerSrc.slice(viewerSrc.indexOf('const handleShareImage'), viewerSrc.indexOf('const getMarkerColor'));
  ok(handler.length > 200, 'found handleShareImage');
  const hCode = stripJs(handler);
  ok(!/\brole\b|isCompanyAdmin|isAdmin|canDelete/.test(hCode), 'the share handler has no role gating');
  ok(!/API\.|fetch\s*\(|XMLHttpRequest|Linking\.|Share\.share/.test(hCode), 'the share handler calls no API, fetch, Linking or the text Share API');

  if (!S || fns.some((f) => typeof S[f] !== 'function')) {
    ok(false, 'the native share module is missing: the compose/share behaviour cannot run');
    console.log(`\n  ${passed} passed, ${failed} failed`);
    process.exit(1);
  }

  // ── network spies for the RN side ────────────────────────────────────────
  const net = [];
  const realFetch = global.fetch;
  global.fetch = (...a) => { net.push(['fetch', a[0]]); return Promise.reject(new Error('no network in test')); };
  const realXHR = global.XMLHttpRequest;
  global.XMLHttpRequest = function XHR() { net.push(['xhr']); };

  // one full run: page + bridge + stubs
  async function run({ photo = null, planDataUri = dataImg(400, 400), context = 'Lintel is cracked at the east wall', share, available = true, breakDraw = false, projectName = 'Boyland St' } = {}) {
    let bridge = null;
    const page = makePage(S, { onPost: (s) => bridge.onMessage(s), net, breakDraw });
    const injected = [];
    bridge = S.createComposerBridge({ inject: (js) => { injected.push(js); page.inject(js); } });
    page.run();
    await tick();
    const Sharing = sharingStub({ available, share });
    const FileSystem = fsStub();
    const ImageManipulator = manipStub();
    let composed = 0;
    const res = await S.sharePlanNoteImage({
      bridge, planDataUri, photo, context, projectName, sheetLabel: 'A-101', date: '2026-11-06',
      filename: W.shareFileName('A-101', '2026-11-06'),
      ImageManipulator, FileSystem, Sharing, onComposed: () => { composed += 1; },
    });
    const drawn = FileSystem.writes[0] ? JSON.parse(unb64(FileSystem.writes[0].data)) : null;
    return { res, Sharing, FileSystem, ImageManipulator, drawn, injected, composed, page };
  }

  // ── 1. compose with / without a photo ────────────────────────────────────
  console.log('\nCompose: with and without a photo, drawn by the page');
  const withPhoto = await run({ photo: { uri: 'file:///cam.jpg', width: 4000, height: 3000 } });
  const noPhoto = await run({});
  ok(withPhoto.res.status === 'shared' && noPhoto.res.status === 'shared', 'both share');
  ok(withPhoto.res.hasPhoto === true && noPhoto.res.hasPhoto === false && withPhoto.res.hasPlan && noPhoto.res.hasPlan, 'hasPlan / hasPhoto reflect the input');
  ok(withPhoto.drawn.w === W.IMAGE_WIDTH && noPhoto.drawn.w === W.IMAGE_WIDTH, 'the image is the fixed share width (1080)');
  ok(withPhoto.drawn.h > noPhoto.drawn.h, 'the photo adds a section (taller image)');
  const drawnTags = (d) => d.calls.filter((x) => x[0] === 'drawImage').map((x) => x[1]).join();
  ok(drawnTags(withPhoto.drawn) === 'img400x400,img1080x1440', 'with photo: the plan crop, then the (scaled) photo');
  ok(drawnTags(noPhoto.drawn) === 'img400x400', 'without photo: only the plan crop');
  const capText = (d) => d.calls.filter((x) => x[0] === 'fillText').map((x) => x[1]).join(' | ');
  ok(/Lintel is cracked/.test(capText(withPhoto.drawn)), 'the caption draws the context');
  ok(['Boyland St', 'Sheet A-101', '2026-11-06'].every((s) => capText(withPhoto.drawn).includes(s)), 'the caption draws project, sheet id and date');
  const resize = withPhoto.ImageManipulator.calls[0];
  ok(!!resize && resize.actions.length === 1 && resize.actions[0].resize.width === W.IMAGE_WIDTH && resize.opts.base64 === true,
    'a 4000 px camera photo is scaled to 1080 on the device before it crosses into the page');
  const small = await run({ photo: { uri: 'file:///small.jpg', width: 800, height: 600 } });
  ok(small.ImageManipulator.calls[0].actions.length === 0 && small.res.hasPhoto, 'a photo narrower than 1080 is not upscaled');
  ok(withPhoto.composed === 1 && noPhoto.composed === 1, 'onComposed fires once the image exists (busy ends before the sheet)');

  // parity: the page draws EXACTLY what the web composer draws
  const wp = webCalls({
    planImage: { naturalWidth: 400, naturalHeight: 400, tag: 'img400x400' },
    photo: { naturalWidth: 1080, naturalHeight: 1440, tag: 'img1080x1440' },
    context: 'Lintel is cracked at the east wall', projectName: 'Boyland St', sheetLabel: 'A-101', date: '2026-11-06',
  });
  ok(JSON.stringify(wp.calls) === JSON.stringify(withPhoto.drawn.calls) && wp.out.height === withPhoto.drawn.h,
    'parity: the phone image is the web composer\'s layout, call for call (same measure)');
  const noCrop = await run({ planDataUri: null });
  ok(noCrop.res.status === 'shared' && noCrop.res.hasPlan === false && drawnTags(noCrop.drawn) === '', 'no plan crop on the note: caption-only image still shares');
  const badCrop = await run({ planDataUri: 'https://evil.example/x.png' });
  ok(badCrop.res.hasPlan === false && !badCrop.injected.some((js) => js.includes('evil.example')), 'a non-data: screenshot is never handed to the page');

  // ── 2. empty context ──────────────────────────────────────────────────────
  console.log('\nEmpty context');
  const empty = await run({ context: '   \n  ' });
  const emptyText = empty.drawn.calls.filter((x) => x[0] === 'fillText').map((x) => x[1]);
  ok(empty.res.status === 'shared', 'an empty context shares');
  ok(emptyText.length === 1 && emptyText[0].includes('Sheet A-101') && emptyText.every((l) => l.trim().length > 0),
    'empty context: one caption line (project | sheet | date), no blank line');
  const bare = await run({ context: '', projectName: '' });
  ok(bare.drawn.calls.filter((x) => x[0] === 'fillText').map((x) => x[1]).join() === 'Sheet A-101 | 2026-11-06', 'no project name: the caption leaves it out (wrapLines joins words with one space, as on the web)');

  // ── 3. the share sheet gets a FILE only ───────────────────────────────────
  console.log('\nShare: a file, nothing prefilled');
  const call = noPhoto.Sharing.calls[0];
  ok(noPhoto.Sharing.calls.length === 1, 'shareAsync called once');
  ok(call.length === 2 && /^file:\/\/.*\/cache\/plan-note-A-101-2026-11-06\.jpg$/.test(call[0]), `the first argument is the image FILE in the cache dir (${call[0]})`);
  ok(JSON.stringify(Object.keys(call[1]).sort()) === JSON.stringify(['UTI', 'mimeType']) && call[1].mimeType === 'image/jpeg' && call[1].UTI === 'public.jpeg',
    'options are ONLY {mimeType: image/jpeg, UTI: public.jpeg}: no message, text, url or dialogTitle');
  const wr = noPhoto.FileSystem.writes[0];
  ok(wr.uri === call[0] && wr.opts.encoding === 'base64' && wr.data.length > 0, 'the page\'s JPEG is written as base64 to exactly that file');

  // ── 4. cancel / failure ───────────────────────────────────────────────────
  console.log('\nCancel is quiet');
  ok(S.shareStatusKey('shared') === null, 'a dismissed / completed sheet shows nothing (expo-sharing resolves on both)');
  let threw = false; let cancel = null;
  try { cancel = await run({ share: async () => { throw Object.assign(new Error('User cancelled'), { code: 'ERR_CANCELED' }); } }); } catch (_) { threw = true; }
  ok(!threw && cancel.res.status === 'cancelled' && S.shareStatusKey(cancel.res.status) === null, 'a share that rejects as cancelled: status cancelled, no copy, no throw');
  const fail = await run({ share: async () => { throw new Error('No Activity found'); } });
  ok(fail.res.status === 'failed' && S.shareStatusKey('failed') === 'failed', 'any other share failure: says so (failed)');
  const unavail = await run({ available: false });
  ok(unavail.res.status === 'unavailable' && unavail.injected.length === 0 && unavail.Sharing.calls.length === 0,
    'no share sheet on the device: says so, and nothing is composed');
  const broken = await run({ breakDraw: true });
  ok(broken.res.status === 'compose-failed' && broken.Sharing.calls.length === 0 && S.shareStatusKey('compose-failed') === 'composeFailed',
    'the page cannot draw: compose-failed, nothing shared');
  // the page never answers: the bridge times out instead of hanging the button
  const timers = [];
  const deaf = S.createComposerBridge({ inject: () => {}, setTimer: (fn) => { timers.push(fn); return timers.length; }, clearTimer: () => {} });
  deaf.onMessage(JSON.stringify({ type: 'composer-ready' }));
  const pend = S.composeInPage({ bridge: deaf, planDataUri: null, context: 'x', sheetLabel: 'A', date: 'd' });
  await tick();
  timers.forEach((fn) => fn());
  let timedOut = false;
  try { await pend; } catch (e) { timedOut = /timed out/.test(e.message); }
  ok(timedOut, 'a page that never answers times out (no stuck "Preparing...")');
  const closedBridge = S.createComposerBridge({ inject: () => {} });
  closedBridge.onMessage(JSON.stringify({ type: 'composer-ready' }));
  const p2 = closedBridge.request({ type: 'prepare' });
  closedBridge.reset();
  let rejected = false;
  try { await p2; } catch (_) { rejected = true; }
  ok(rejected && closedBridge.isReady() === false, 'closing the panel rejects anything waiting and needs a fresh page');

  // ── 5. no network ─────────────────────────────────────────────────────────
  console.log('\nNo network in the share path');
  ok(net.length === 0, `no fetch / XHR / beacon / window.open in compose + share (saw ${JSON.stringify(net)})`);
  global.fetch = realFetch;
  global.XMLHttpRequest = realXHR;
  const modSrc = stripJs(read(MODULE));
  const PROVIDER = /wa\.me|api\.whatsapp\.com|whatsapp:\/\/|web\.whatsapp\.com|graph\.facebook\.com/i;
  ok(!PROVIDER.test(read(MODULE)) && !PROVIDER.test(viewerSrc), 'no messaging-provider host in the module or the viewer');
  ok(!/\bfetch\s*\(|XMLHttpRequest|sendBeacon|WebSocket|window\.open|location\.(href|assign|replace)/.test(modSrc), 'the module (page script included) has no fetch / XHR / beacon / socket / navigation');
  ok(!/https?:\/\//.test(S.COMPOSER_HTML), 'the page names no http(s) url');
  ok(/default-src 'none'/.test(S.COMPOSER_HTML) && !/connect-src/.test(S.COMPOSER_HTML) && /img-src data:/.test(S.COMPOSER_HTML),
    'the page\'s CSP: default-src \'none\' (so no connections), images from data: only');
  ok(!/react-native['"]|Linking|Share\.share/.test(modSrc), 'the module does not use Linking or the text Share API');

  // ── 7. EN and ES ──────────────────────────────────────────────────────────
  console.log('\nEN and ES copy');
  const keys = [...new Set([...viewerSrc.matchAll(/tShare\(\s*'([A-Za-z]+)'/g)].map((m) => m[1]))];
  const statusKeys = ['unavailable', 'failed', 'compose-failed'].map((s) => S.shareStatusKey(s));
  const all = [...new Set([...keys, ...statusKeys, 'cameraPermission', 'libraryPermission'])];
  const missing = all.filter((k) => !(en.planNoteShare && typeof en.planNoteShare[k] === 'string' && en.planNoteShare[k]) || !(es.planNoteShare && typeof es.planNoteShare[k] === 'string' && es.planNoteShare[k]));
  ok(keys.length >= 10 && missing.length === 0, `every key has EN and ES copy (${all.length} keys)${missing.length ? ` -- missing: ${missing.join(', ')}` : ''}`);
  const shareBlock = viewerSrc.slice(viewerSrc.indexOf('{shareOpen && ('), viewerSrc.indexOf('{/* Actions */}'));
  ok(shareBlock.length > 200 && !/>\s*[A-Za-z][^<>{}]*</.test(shareBlock.replace(/\{[^{}]*\}/g, '')), 'the panel has no hard-coded English between tags');

  // ── 8. OTA only ───────────────────────────────────────────────────────────
  console.log('\nOTA only: nothing the 1.3.0 binary lacks');
  // In package.json at 0e876968 (#198, the 1.3.0 build, 2026-08-23) and unchanged since #194.
  const IN_BINARY = {
    'expo-image-picker': '~17.0.11', 'expo-image-manipulator': '~14.0.8', 'expo-file-system': '~19.0.24',
    'expo-sharing': '~14.0.8', 'react-native-webview': '13.15.0',
  };
  const pkg = JSON.parse(read('package.json'));
  ok(Object.entries(IN_BINARY).every(([n, v]) => pkg.dependencies[n] === v), 'expo-image-picker, -image-manipulator, -file-system, -sharing and react-native-webview are at their 1.3.0 versions');
  const modImports = [...read(MODULE).matchAll(/from '([^']+)'/g)].map((m) => m[1]);
  ok(modImports.length === 1 && modImports[0] === './planNoteShare', `the module imports only ./planNoteShare (${modImports.join(', ')})`);
  const newPkgs = [...viewerSrc.matchAll(/from '([^.'][^']*)'/g), ...viewerSrc.matchAll(/require\('([^.'][^']*)'\)/g)]
    .map((m) => m[1].split('/').slice(0, m[1].startsWith('@') ? 2 : 1).join('/'));
  const KNOWN = new Set(['react', 'react-native', 'lucide-react-native', ...Object.keys(IN_BINARY)]);
  const unknown = [...new Set(newPkgs)].filter((n) => !KNOWN.has(n));
  ok(unknown.length === 0, `the viewer imports no package outside that set (${[...new Set(newPkgs)].join(', ')})`);
  ok(!/react-native-view-shot|@shopify\/react-native-skia|expo-gl|react-native-canvas|expo-media-library/.test(viewerSrc + read(MODULE)), 'no view-shot / Skia / GL / canvas / media-library module');

  console.log(`\n  ${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
