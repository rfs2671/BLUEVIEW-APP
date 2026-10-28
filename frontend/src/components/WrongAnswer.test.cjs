/**
 * "Wrong?" under an assistant answer, run for real (no DOM): the component is
 * rendered by a tiny hook runner into a plain element tree, its buttons are
 * pressed, and the API client is the shipped one over a recording HTTP client.
 *   1. it shows on an answer with an answer_log_id, not on one without;
 *   2. tap -> an optional note box with Send;
 *   3. Send, empty and with words, POSTs /api/answers/{id}/dispute with {} / {note};
 *   4. success shows exactly "Flagged for review", and it stays flagged;
 *   5. a failed send keeps the box (and the words) and says "Couldn't send -- try again";
 *   6. no review status, approve / deny or reviewer is ever shown.
 * Run:  node src/components/WrongAnswer.test.cjs
 */
const fs = require('fs');
const path = require('path');
const babel = require('@babel/core');
const { loadEsm } = require('../utils/esmHarness.cjs');

let passed = 0; let failed = 0;
function ok(c, l) { if (c) { passed += 1; console.log(`  PASS  ${l}`); } else { failed += 1; console.log(`  FAIL  ${l}`); } }
const FRONTEND = path.join(__dirname, '..', '..');

// ── the real API client over a recording axios ─────────────────────────────
const calls = [];
let nextPost = () => Promise.resolve({ data: { status: 'Flagged for review' } });
const client = {
  interceptors: { request: { use() {} }, response: { use() {} } },
  defaults: { headers: { common: {} } },
  post(url, body) { calls.push({ url, body }); return nextPost(url, body); },
  get() { throw new Error('unexpected GET'); },
};
const asyncStorage = { getItem: async () => null, setItem: async () => {}, removeItem: async () => {},
  multiRemove: async () => {}, getAllKeys: async () => [] };
const api = loadEsm('src/utils/api.js', { stubs: {
  axios: { __esModule: true, default: { create: () => client, isAxiosError: () => false } },
  '@react-native-async-storage/async-storage': { __esModule: true, default: asyncStorage },
  'expo-constants': { __esModule: true, default: { expoConfig: { version: '1.0.0' } } },
} });
const D = loadEsm('src/utils/answerDispute.js');

// ── a minimal React: elements are plain objects, hooks are slots ───────────
let hooks; let idx; let rerender;
const React = {
  createElement(type, props, ...children) {
    return { type, props: { ...(props || {}), children: children.length <= 1 ? children[0] : children } };
  },
  Fragment: 'Fragment',
  useState(init) {
    const i = idx; idx += 1;
    if (!(i in hooks)) hooks[i] = typeof init === 'function' ? init() : init;
    return [hooks[i], (v) => { hooks[i] = typeof v === 'function' ? v(hooks[i]) : v; rerender(); }];
  },
};
const host = (name) => name;
const RN = { View: host('View'), Text: host('Text'), TextInput: host('TextInput'),
  Pressable: host('Pressable'), ActivityIndicator: host('ActivityIndicator'),
  StyleSheet: { create: (s) => s } };
const colors = { text: { muted: '#999', primary: '#000' }, glass: { border: '#ccc' },
  primary: '#E3C27A', onPrimary: '#141A1F', error: '#F28B6E' };

function loadComponent() {
  const file = path.join(FRONTEND, 'src/components/WrongAnswer.jsx');
  const { code } = babel.transformSync(fs.readFileSync(file, 'utf8'), {
    filename: file, configFile: false, babelrc: false,
    presets: [[require.resolve('@babel/preset-react'), { runtime: 'classic' }]],
    plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')],
  });
  const mod = { exports: {} };
  const req = (p) => ({
    react: { __esModule: true, default: React, ...React },
    'react-native': RN,
    '../context/ThemeContext': { useTheme: () => ({ colors }) },
    '../styles/theme': { spacing: { xs: 4, sm: 8, md: 16 }, borderRadius: { sm: 8 } },
    '../utils/api': api,
    '../utils/answerDispute': D,
  })[p] || (() => { throw new Error(`unstubbed ${p}`); })();
  new Function('exports', 'module', 'require', code)(mod.exports, mod, req);
  return mod.exports.default;
}
const WrongAnswer = loadComponent();

function mount(props) {
  hooks = {};
  const view = { tree: null };
  rerender = () => { idx = 0; view.tree = WrongAnswer(props); };
  rerender();
  return view;
}
function walk(node, out = []) {
  if (node == null || typeof node === 'boolean') return out;
  if (Array.isArray(node)) { node.forEach((n) => walk(n, out)); return out; }
  if (typeof node !== 'object') { out.push(String(node)); return out; }
  out.push(node);
  walk(node.props && node.props.children, out);
  return out;
}
const nodes = (v) => walk(v.tree).filter((n) => typeof n === 'object');
const textOf = (v) => walk(v.tree).filter((n) => typeof n === 'string').join(' | ');
const byLabel = (v, re) => nodes(v).find((n) => re.test(n.props.accessibilityLabel || ''));
const input = (v) => nodes(v).find((n) => n.type === 'TextInput');
const settle = async () => { for (let i = 0; i < 10; i += 1) await new Promise((r) => setImmediate(r)); };

(async () => {
  console.log('\n── Shown only on an answer the backend logged ──');
  ok(mount({ answerLogId: null }).tree === null, 'no answer_log_id: nothing shown');
  ok(mount({ answerLogId: '' }).tree === null, 'an empty id: nothing shown');
  let v = mount({ answerLogId: 'a1' });
  ok(textOf(v) === 'Wrong?', 'with an id: "Wrong?" and nothing else');
  const wrong = byLabel(v, /^Wrong\?/);
  ok(wrong && wrong.type === 'Pressable' && wrong.props.accessibilityRole === 'button', 'it is a labelled button');
  ok(!input(v), 'no box until it is tapped');

  console.log('\n── Tap: the optional note and Send ──');
  wrong.props.onPress();
  ok(input(v) && input(v).props.placeholder === "What’s wrong? (optional)", 'tap opens "What’s wrong? (optional)"');
  ok(input(v).props.accessibilityLabel === "What’s wrong? (optional)", 'the box is labelled');
  const sendBtn = byLabel(v, /^Send/);
  ok(sendBtn && sendBtn.type === 'Pressable' && /Send/.test(textOf(v)), 'a Send button');

  console.log('\n── Send, empty ──');
  calls.length = 0;
  sendBtn.props.onPress();
  await settle();
  ok(calls.length === 1 && calls[0].url === '/api/answers/a1/dispute', 'POST /api/answers/a1/dispute');
  ok(JSON.stringify(calls[0].body) === '{}', 'empty note: an empty body');
  ok(textOf(v) === 'Flagged for review', 'success shows exactly "Flagged for review"');
  ok(!input(v) && !byLabel(v, /^Wrong\?/), 'the control is replaced');
  v = mount({ answerLogId: 'a1' });
  ok(textOf(v) === 'Flagged for review', 'drawn again in this session: still flagged');

  console.log('\n── Send, with words ──');
  v = mount({ answerLogId: 'b/2' });
  byLabel(v, /^Wrong\?/).props.onPress();
  input(v).props.onChangeText('  The pour was moved to Friday.  ');
  calls.length = 0;
  byLabel(v, /^Send/).props.onPress();
  await settle();
  ok(calls.length === 1 && calls[0].url === '/api/answers/b%2F2/dispute', 'the id is path-encoded');
  ok(JSON.stringify(calls[0].body) === '{"note":"The pour was moved to Friday."}', 'the note, trimmed, as {note}');
  ok(textOf(v) === 'Flagged for review', 'then "Flagged for review"');

  console.log('\n── A failed send keeps the box ──');
  v = mount({ answerLogId: 'c3' });
  byLabel(v, /^Wrong\?/).props.onPress();
  input(v).props.onChangeText('wrong date');
  nextPost = () => Promise.reject(Object.assign(new Error('503'), { response: { status: 503 } }));
  byLabel(v, /^Send/).props.onPress();
  await settle();
  ok(/Couldn’t send — try again/.test(textOf(v)), 'it says "Couldn’t send — try again"');
  ok(input(v) && input(v).props.value === 'wrong date', 'the box stays, with their words');
  ok(!/Flagged for review/.test(textOf(v)) && !D.isFlagged('c3'), 'and it is not marked flagged');
  nextPost = () => Promise.resolve({ data: { status: 'Flagged for review' } });
  calls.length = 0;
  byLabel(v, /^Send/).props.onPress();
  await settle();
  ok(calls.length === 1 && calls[0].body.note === 'wrong date' && textOf(v) === 'Flagged for review',
    'sending again works');

  console.log('\n── Never a review status ──');
  const src = fs.readFileSync(path.join(FRONTEND, 'src/components/WrongAnswer.jsx'), 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
  ok(!/pending|approve|denied|deny|reviewer|response\.data|\.status\b/i.test(src),
    'the component reads no review state and shows no approve / deny / reviewer');

  console.log('\n── Wired into the answer ──');
  const PM = loadEsm('src/utils/projectMemory.js');
  ok(PM.answerState({ claims: [{ text: 'x' }], answer_log_id: 'abc' }).answerLogId === 'abc', 'a found answer keeps its id');
  ok(PM.answerState({ claims: [], answer_log_id: 'abc' }).answerLogId === 'abc', '"cannot find it" is an answer too');
  ok(PM.answerState({ claims: [{ text: 'x' }] }).answerLogId === null, 'no id: null');
  const screen = fs.readFileSync(path.join(FRONTEND, 'app/projects/[id]/search.jsx'), 'utf8');
  ok(/<WrongAnswer key=\{answer\.answerLogId \|\| 'none'\} answerLogId=\{answer\.answerLogId\} \/>/.test(screen),
    'Project Search draws it under the answer');

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
