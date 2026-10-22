/**
 * THE FEATURE IS CALLED "COMPLIANCE" — counted from the source.
 *
 * The user-facing label "DOB Compliance" (and its Spanish forms, "Cumplimiento
 * DOB" / "Cumplimiento del DOB") was renamed to "Compliance" / "Cumplimiento".
 * This census reads every shipped screen and component under app/ and src/,
 * plus the server-rendered gate page backend/checkin.html, with comments
 * stripped, and fails on any surviving occurrence a user could see.
 *
 * Case-insensitive, and tolerant of a line break or a string concatenation
 * between the two words, because the label also appears inside prose
 * ("all its DOB compliance data") and as an all-caps title ("DOB COMPLIANCE").
 *
 * NOT IN SCOPE, deliberately: route and file names (`/project/:id/dob-logs`,
 * `dob-logs.jsx`), identifiers, API paths and database fields. Those were left
 * as they are; this test reads only what is left after comments are removed,
 * and none of those spell the two words with a space between them.
 * "NYC DOB Local Law 196 Compliance" on the gate is a different label (the
 * LL196 training requirement) and does not match.
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
const REPO = path.join(FRONTEND, '..');
const rel = (p) => path.relative(REPO, p).split(path.sep).join('/');

let failures = 0;
const check = (name, fn) => {
  try {
    fn();
    console.log(`  ok  ${name}`);
  } catch (e) {
    failures += 1;
    console.error(`FAIL  ${name}\n      ${e.message}`);
  }
};
const ok = (cond, msg) => { if (!cond) throw new Error(msg); };

/** Comments out, strings and JSX text kept; newlines kept for line numbers. */
function stripComments(src) {
  const blank = (s) => s.replace(/[^\n]/g, '');
  return src.split('\r\n').join('\n')
    .replace(/<!--[\s\S]*?-->/g, blank)
    .replace(/\{\s*\/\*[\s\S]*?\*\/\s*\}/g, blank)
    .replace(/\/\*[\s\S]*?\*\//g, blank)
    .replace(/(^|[^:'"`\\])\/\/.*$/gm, '$1');
}

const OLD_LABEL = /DOB[\s'"`+]*compliance|cumplimiento\s+(?:del?\s+)?DOB/gi;

function walk(dir, out = []) {
  for (const name of fs.readdirSync(dir)) {
    const p = path.join(dir, name);
    const st = fs.statSync(p);
    if (st.isDirectory()) walk(p, out);
    else if (/\.(jsx?|tsx?)$/.test(name) && !/\.test\./.test(name)) out.push(p);
  }
  return out;
}

const SOURCES = [
  ...walk(path.join(FRONTEND, 'app')),
  ...walk(path.join(FRONTEND, 'src')),
  path.join(REPO, 'backend', 'checkin.html'),
].map((abs) => ({ abs, rel: rel(abs), code: stripComments(fs.readFileSync(abs, 'utf8')) }));

function hits(code) {
  const out = [];
  let m;
  OLD_LABEL.lastIndex = 0;
  while ((m = OLD_LABEL.exec(code))) {
    out.push({ text: m[0].replace(/\s+/g, ' '), line: code.slice(0, m.index).split('\n').length });
  }
  return out;
}

check('the scanner can fail: it sees the old label in strings, not in comments', () => {
  const sample = [
    "// DOB Compliance in a comment is prose",
    "/* DOB Compliance */",
    "{/* DOB Compliance */}",
    "const a = { title: 'DOB Compliance' };",
    "<Text>DOB COMPLIANCE</Text>",
    "const b = 'all its DOB ' +",
    "  'compliance data';",
    "const c = 'Cumplimiento del DOB';",
    "const d = 'https://x.test/a';",
  ].join('\n');
  const found = hits(stripComments(sample));
  ok(found.length === 4, `expected 4 hits in the sample, got ${found.length}: ${JSON.stringify(found)}`);
  ok(found.every((h) => h.line >= 4), `a comment was counted: ${JSON.stringify(found)}`);
});

check('the census read the screens it is about', () => {
  ok(SOURCES.length > 200, `only ${SOURCES.length} files scanned`);
  for (const must of ['frontend/app/project/[id].jsx', 'frontend/app/project/[id]/dob-logs.jsx', 'backend/checkin.html']) {
    ok(SOURCES.some((f) => f.rel === must), `${must} was not scanned`);
  }
});

check('no user-visible "DOB Compliance" survives in UI source', () => {
  const bad = SOURCES.flatMap((f) => hits(f.code).map((h) => `${f.rel}:${h.line} "${h.text}"`));
  ok(bad.length === 0, `${bad.length} occurrence(s):\n      ${bad.join('\n      ')}`);
});

check('the project tile and the screen title carry the new label', () => {
  const tile = SOURCES.find((f) => f.rel === 'frontend/app/project/[id].jsx').code;
  ok(/title:\s*'Compliance',\s*icon:\s*Shield,\s*path:\s*`\/project\/\$\{projectId\}\/dob-logs`/.test(tile),
    'project detail has no Compliance tile pointing at the (unchanged) dob-logs route');
  const screen = SOURCES.find((f) => f.rel === 'frontend/app/project/[id]/dob-logs.jsx').code;
  ok(/<Text style=\{s\.titleLabel\}>COMPLIANCE<\/Text>/.test(screen), 'dob-logs screen title is not COMPLIANCE');
});

console.log(`\n${failures === 0 ? 'all passed' : `${failures} FAILED`}\n`);
process.exit(failures === 0 ? 0 : 1);
