/**
 * WHICH KEYS THE FILED DOCUMENT READS, WHICHEVER RENDERER PRINTS IT.
 *
 * ── WHY THIS MODULE EXISTS ───────────────────────────────────────────────
 *
 * Four frontend suites cross-check the DEVICE against the RENDERER: the form
 * writes a payload, the PDF reads it, and a key the renderer reads that the
 * model never writes is the bug those files catch. Each did it by slicing the
 * type's arm out of `server.py`:
 *
 *     SERVER.indexOf(`elif log_type == "${logType}":`)
 *
 * Seven types render through `lib/legal_render` now and five of those arms
 * were deleted, so those slices return nothing and the assertions report a
 * renderer that reads zero keys. Not one of them is about a rule that broke.
 *
 * ── AND THE SLICE HAS BEEN WRONG BEFORE THAT ─────────────────────────────
 *
 * `elif` is not a stable prefix: the chain's FIRST arm is spelled `if`, and
 * which type is first changes every time one converts. `hot_work` became the
 * first arm in this change and four assertions about it failed while its
 * branch sat untouched. The end anchor has moved twice for the same reason.
 *
 * ── WHAT THIS RETURNS ────────────────────────────────────────────────────
 *
 * `rendererKeys(type)` — every key the filed document reads for that type,
 * from whichever renderer prints it:
 *
 *   * CONVERTED: the declaration in `lib/legal_render/schema.py`, read from
 *     its `("path", "Label", "formatter")` triples and its `path` bindings.
 *     This is not a regex over prose — it is the list itself, and it is the
 *     same list the engine binds.
 *   * BRANCHED: the arm of the per-type chain, located AFTER the dispatch and
 *     accepting either `if` or `elif`, ending at the next arm or at the
 *     generic tail.
 *
 * A caller does not have to know which, which is the point: six more types
 * convert and no test file above this one changes.
 */
const fs = require('fs');
const path = require('path');

const BACKEND = path.resolve(__dirname, '..', '..', '..', 'backend');

// NEWLINES NORMALISED ON READ. This checkout is on Windows and git hands these
// files back with CRLF; every anchor below is written with a bare newline, and
// an `indexOf` that spans a line break then silently finds nothing — which
// reads exactly like a branch that was deleted.
const read = (p) => fs.readFileSync(p, 'utf8').split('\r\n').join('\n');
const SERVER = read(path.join(BACKEND, 'server.py'));
const SCHEMA = read(path.join(BACKEND, 'lib', 'legal_render', 'schema.py'));
// THE PRIMITIVES, because a column bound to "." is handed the whole row and
// the keys it reads live in the row formatter rather than in the declaration.
const PRIMITIVES = read(
  path.join(BACKEND, 'lib', 'legal_render', 'primitives.py'));
// AND THE FORMATTERS, which hold the closed vocabularies a filed record is
// printed in -- the three attendee provenances, the three answers, the
// verdicts. A branch used to hold each of those as its own helper.
const FORMATTERS = read(
  path.join(BACKEND, 'lib', 'legal_render', 'formatters.py'));

/** Every type the declarative engine has a schema for. */
function convertedTypes() {
  return new Set(
    [...SCHEMA.matchAll(/\n {4}"([a-z_]+)": \{\n/g)].map((m) => m[1]),
  );
}

/**
 * The declaration block for one type: from its own key to the next type's, or
 * to the end of the SCHEMAS map.
 */
function declaration(logType) {
  const open = `\n    "${logType}": {\n`;
  const a = SCHEMA.indexOf(open);
  if (a < 0) return '';
  const rest = SCHEMA.slice(a + 1);
  const m = /\n {4}"[a-z_]+": \{\n/.exec(rest.slice(open.length));
  return m ? rest.slice(0, open.length + m.index) : rest;
}

/**
 * The per-type chain arm for one type.
 *
 * ANCHORED AFTER THE DISPATCH, and accepting `if` or `elif`. The bare string
 * `if log_type == "preshift_signin"` appears TWICE in that file — once above
 * the dispatch, where the caller resolves async work, and once as an arm —
 * and a leftmost match finds the wrong one. That has now cost four separate
 * assertions in this repository.
 */
function pdfBranch(logType) {
  const d = SERVER.indexOf('if log_type in legal_render.CONVERTED_TYPES:');
  const from = d < 0 ? 0 : d;
  const open = new RegExp(`\\n {4}(?:el)?if log_type == "${logType}":`);
  const m = open.exec(SERVER.slice(from));
  if (!m) return '';
  const a = from + m.index + 1;
  const next = /\n {4}(?:el)?if log_type == "[a-z_]+":|\n {4}else:/
    .exec(SERVER.slice(a + 10));
  return next ? SERVER.slice(a, a + 10 + next.index) : SERVER.slice(a);
}

/**
 * Every key the filed document reads for `logType`.
 *
 * Returned SORTED and de-duplicated, and never empty for a type the app
 * defines — an empty result is a broken read rather than a renderer that
 * prints nothing, and `rendererKeys` is only ever used with an assertion that
 * says so.
 */
function rendererKeys(logType) {
  const keys = new Set();
  if (convertedTypes().has(logType)) {
    const decl = declaration(logType);
    // THE DOTTED PATHS A DECLARATION BINDS. `data.x` and `data.x.y` both name
    // `x` as the key the payload has to carry; the engine walks the rest.
    for (const m of decl.matchAll(/"data\.([a-z_]+)[a-z_.]*"/g)) {
      keys.add(m[1]);
    }
    // A TABLE'S COLUMNS ARE KEYS OF THE ROW, not of `data`, so they carry no
    // prefix — `("card_number", "Card #", "text")`. Taken from the triples,
    // which is where a column's binding actually is.
    for (const m of decl.matchAll(/\("([a-z_]+)", "[^"]*", "[a-z_]+"\)/g)) {
      keys.add(m[1]);
    }
  } else {
    const branch = pdfBranch(logType);
    for (const m of branch.matchAll(
      /(?:data|d|e|entry|a|w|row|q|gi)\.get\("([a-z_]+)"/g)) {
      keys.add(m[1]);
    }
    // AND THE ITEM LISTS A BRANCH DECLARES INLINE. hot_work names its seven
    // precautions as `("area_cleared", "Area Cleared of Combustibles (35 ft)")`
    // and reads them in a loop, so a `.get(` scan finds NONE of them and
    // reports a renderer that reads nothing. Same shape as a declaration's
    // triples, one element shorter.
    for (const m of branch.matchAll(/\("([a-z_]+)", "[^"]*"\)/g)) {
      keys.add(m[1]);
    }
  }
  return [...keys].sort();
}

/**
 * The keys of `data` the sheet reads — the payload's OWN top level.
 *
 * THREE DIFFERENT QUESTIONS, AND CONFLATING THEM COSTS SIX ASSERTIONS EACH
 * TIME. `rendererKeys` is everything the document reads, project block
 * included; `rowKeys` is the columns of one table; this is what the editor's
 * `draftBody` has to put in `data`. A caller checking a payload wants this
 * one, and handed the widest list it demands that a toolbox payload carry
 * `address` and `bbl`.
 */
function dataKeys(logType) {
  if (convertedTypes().has(logType)) {
    return [...new Set(
      [...declaration(logType).matchAll(/"data\.([a-z_0-9]+)[a-z_0-9.]*"/g)]
        .map((m) => m[1]),
    )].sort();
  }
  return [...new Set(
    [...pdfBranch(logType).matchAll(/data\.get\("([a-z_0-9]+)"/g)]
      .map((m) => m[1]),
  )].sort();
}

/**
 * A LABEL SET, as `[{key, label}]`, in declared ORDER.
 *
 * The item lists a branch used to declare inline -- scaffold's nineteen
 * maintenance questions, the daily log's inspection items -- are LABEL_SETS in
 * `schema.py` now. The frontend suites compare them against the device's own
 * list word for word, because the CP answers the question the SCREEN asks and
 * the inspector reads the question the SHEET prints; if those two sentences
 * differ, the record says something nobody agreed to.
 *
 * ORDER IS PART OF THE CLAIM, so this returns a list and never a map.
 */
function labelSet(name) {
  const open = `\n    "${name}": [\n`;
  const a = SCHEMA.indexOf(open);
  if (a < 0) return [];
  const rest = SCHEMA.slice(a + open.length);
  const end = rest.indexOf('\n    ],');
  const block = end < 0 ? rest : rest.slice(0, end);
  // THE LABEL MAY BE WRAPPED. A long question is written across two lines in
  // the declaration, so the newline between key and label is optional here —
  // pinning it to one line dropped four of scaffold's nineteen and reported
  // the renderer as asking fifteen questions.
  return [...block.matchAll(/\("([a-z_0-9]+)",\s*"([^"]+)"\)/g)]
    .map((m) => ({ key: m[1], label: m[2] }));
}

/**
 * Every `("path", "Label", "formatter")` triple a declaration names, in order.
 *
 * Returned with the path VERBATIM -- `data.general_info.phone`, not `phone` --
 * because a caller comparing against the device's key list needs to know which
 * map the field comes out of.
 */
function declFields(logType) {
  return [...declaration(logType).matchAll(
    /\("([a-z_0-9.]+)",\s*"([^"]*)",\s*"([a-z_]+)"\)/g)]
    .map((m) => ({ path: m[1], label: m[2], formatter: m[3] }));
}

/**
 * The keys of a ROW, for the table bound to `dataPath`.
 *
 * NOT THE SAME QUESTION AS `rendererKeys`. That one answers "what does this
 * document read off the record", which includes the project block and the
 * top-level fields; a caller checking that every roster ROW carries what the
 * register prints needs the columns and nothing else. Handing it the wider
 * list made six assertions demand that an OSHA entry carry `address` and
 * `cp_name`.
 *
 * Returned in declared ORDER, because a table's columns are read left to
 * right and that is part of what the document says.
 */
function rowKeys(logType, dataPath) {
  if (convertedTypes().has(logType)) {
    const decl = declaration(logType);
    const at = decl.indexOf(`"path": "${dataPath}"`);
    if (at < 0) return [];
    const open = decl.indexOf('"columns": [', at);
    if (open < 0) return [];
    const block = decl.slice(open, decl.indexOf('\n            }', open));
    const keys = [...block.matchAll(/\("([a-z_0-9]+)", "[^"]*", "[a-z_]+"\)/g)]
      .map((m) => m[1]);
    // PLUS WHAT A ROW FORMATTER READS, ONE LEVEL DEEPER.
    //
    // A column bound to `"."` is handed the WHOLE ROW -- that is what a row
    // formatter is for, and `osha_cert_type` is one: it decides the Cert Type
    // label from `certification_type` and `unverified` together, which no
    // single-value formatter could. Scanning only the column triples reports
    // those keys as dropped when they were relocated, and the old branch-based
    // version of this had the same step for the same reason.
    for (const m of block.matchAll(/\("\.", "[^"]*", "([a-z_0-9]+)"\)/g)) {
      const fn = new RegExp(`\\ndef ${m[1]}\\(`).exec(PRIMITIVES);
      if (!fn) continue;
      const body = PRIMITIVES.slice(fn.index,
        PRIMITIVES.indexOf('\ndef ', fn.index + 5));
      for (const k of body.matchAll(/\.get\("([a-z_0-9]+)"/g)) {
        if (!keys.includes(k[1])) keys.push(k[1]);
      }
    }
    return keys;
  }
  // A BRANCH BUILDS ITS ROWS IN A LOOP, so the row variable is the anchor.
  const branch = pdfBranch(logType);
  const key = dataPath.split('.').pop();
  const at = branch.indexOf(`.get("${key}"`);
  if (at < 0) return [];
  const block = branch.slice(at);
  return [...new Set(
    [...block.matchAll(/(?:e|entry|a|w|row|q)\.get\("([a-z_0-9]+)"/g)]
      .map((m) => m[1]),
  )];
}

/**
 * The fields a ROW must carry to be printed at all, for the table bound to
 * `dataPath`.
 *
 * A row naming nobody is not a row: a seed row the CP never filled printed as
 * a blank line on a signed attendance record, and every roster now drops it.
 * The branches stated that as `if not str(a.get("name") or "").strip():
 * continue`; the declaration states it as `row_requires`.
 *
 * THIS IS THE FIELD THE DEVICE'S OWN FILING RULE MUST AGREE WITH. A row the
 * gate accepts and the sheet silently drops is a record the two disagree
 * about.
 */
function rowRequires(logType, dataPath) {
  if (convertedTypes().has(logType)) {
    const decl = declaration(logType);
    const at = decl.indexOf(`"path": "${dataPath}"`);
    if (at < 0) return [];
    const m = /"row_requires": \[([^\]]*)\]/.exec(decl.slice(at));
    if (!m) return [];
    return [...m[1].matchAll(/"([a-z_0-9]+)"/g)].map((x) => x[1]);
  }
  const branch = pdfBranch(logType);
  const m = /has\((?:e|a|w|row), k\) for k in\s*\n?\s*\(([^)]*)\)/.exec(branch)
    || /if not str\((?:e|a|w|row)\.get\("([a-z_0-9]+)"/.exec(branch);
  if (!m) return [];
  return [...m[1].matchAll(/"?([a-z_0-9]+)"?/g)].map((x) => x[1]);
}

/** Which renderer prints this type, as a word, for a failure message. */
function rendererOf(logType) {
  return convertedTypes().has(logType) ? 'the declaration' : 'the branch';
}

module.exports = {
  SERVER, SCHEMA, PRIMITIVES, FORMATTERS, convertedTypes, declaration, pdfBranch, rendererKeys,
  rendererOf, labelSet, declFields, rowKeys, rowRequires, dataKeys,
};
