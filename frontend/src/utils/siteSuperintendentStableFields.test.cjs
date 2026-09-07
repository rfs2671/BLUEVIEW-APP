/**
 * THE KEYBOARD MUST NOT CLOSE AFTER ONE CHARACTER.
 *
 * WHAT HAPPENED. `Field`, `CorrectionChoice` and `EntryList` were declared
 * INSIDE the `SiteSuperintendentLog` function body and used as JSX element
 * types (`<Field ... />`). A function expression declared in a render body is
 * a NEW function object on every render. React compares element types by
 * REFERENCE: a new type is a different component, so the old subtree is
 * UNMOUNTED and a fresh one mounted. The `TextInput` inside it is destroyed
 * and recreated, and a destroyed input is not a focused input.
 *
 * Per keystroke: onChangeText -> setState -> re-render -> new `Field`
 * identity -> remount -> keyboard dismissed. The site superintendent reported
 * exactly that: one character, then tap the field again. Eleven items of
 * statutory prose, one character at a time.
 *
 * THIS FILE IS A PROXY, AND SAYS SO. It asserts the CAUSE (unstable element
 * identity by construction), not the EFFECT (focus survives a keystroke). A
 * screen that dropped focus for some other reason — a key that changes per
 * render, a remount driven from a parent — would pass every assertion here.
 * The effect is proved by executing the screen and driving real keystrokes
 * into it: `node scripts/focus-survives-keystroke.cjs --dist dist`. That job
 * is the evidence; this one is the regression brake, and it is cheap enough to
 * run on every commit while the browser job is not.
 *
 * WHY A GUARD AND NOT A CONVENTION. Hoisting makes identity stable BY
 * CONSTRUCTION; nothing about the fixed file tells the next editor that
 * dropping a small `const Row = ({...}) => (...)` back into the body would
 * silently return the bug. This test is that telling.
 *
 * Run:  node src/utils/siteSuperintendentStableFields.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
const read = (...p) => fs.readFileSync(path.join(FRONTEND, ...p), 'utf8')
  .split('\r\n').join('\n');

const RAW = read('app', 'logbooks', 'site_superintendent_log.jsx');

/**
 * Comments stripped. This screen documents itself at length and quotes its own
 * JSX in prose — `<Field .../>` and the words "declared inside" both appear in
 * comments — so every assertion below reads CODE. A raw search would match the
 * explanation and pass against the defect it explains.
 */
const CODE = RAW
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/(?<!:)\/\/.*$/gm, '');

/** The balanced-brace body that follows an anchor; '' when the anchor is absent. */
function braceBlock(src, anchor) {
  const at = src.indexOf(anchor);
  if (at < 0) return '';
  const open = src.indexOf('{', at);
  if (open < 0) return '';
  let depth = 0;
  for (let i = open; i < src.length; i += 1) {
    if (src[i] === '{') depth += 1;
    else if (src[i] === '}') {
      depth -= 1;
      if (depth === 0) return src.slice(at, i + 1);
    }
  }
  return '';
}

const SCREEN_ANCHOR = 'export default function SiteSuperintendentLog()';
const DECLARATION = braceBlock(CODE, SCREEN_ANCHOR);
/**
 * The body WITHOUT its own signature. Left in, `SiteSuperintendentLog` reports
 * itself as a component declared inside `SiteSuperintendentLog` — a permanent
 * failure that no fix can clear, which is the kind of assertion people delete.
 */
const BODY = DECLARATION.slice(DECLARATION.indexOf('{'));
/** Everything that is NOT the screen function body — i.e. module scope. */
const MODULE_SCOPE = BODY ? CODE.split(BODY).join('\n/*screen*/\n') : CODE;

let failures = 0;
const ok = (c, m) => {
  if (c) { console.log(`  ok  ${m}`); } else { failures += 1; console.log(`FAIL  ${m}`); }
};

/**
 * A COMPONENT SHAPE, not merely a capitalised name. `STEPS` and `TOTAL_STEPS`
 * are SCREAMING_CASE constants and are not components; the shape that matters
 * is PascalCase — an initial capital followed by a lower-case letter — bound to
 * a function, which is the only thing JSX can use as an element type.
 */
const PASCAL = '[A-Z][a-z][A-Za-z0-9]*';
const declaredComponents = (src) => {
  const found = new Set();
  const arrow = new RegExp(`\\b(?:const|let|var)\\s+(${PASCAL})\\s*=\\s*(?:React\\.)?(?:memo\\s*\\(\\s*)?(?:function\\b|\\(|[A-Za-z_$][\\w$]*\\s*=>)`, 'g');
  const fn = new RegExp(`\\bfunction\\s+(${PASCAL})\\s*\\(`, 'g');
  let m;
  while ((m = arrow.exec(src)) !== null) found.add(m[1]);
  while ((m = fn.exec(src)) !== null) found.add(m[1]);
  return found;
};

console.log('\n1. THE SCREEN BODY DECLARES NO COMPONENTS');
{
  ok(BODY.length > 0, `the screen function is found by anchor: ${SCREEN_ANCHOR}`);

  const inner = [...declaredComponents(BODY)];
  ok(
    inner.length === 0,
    'no PascalCase function is declared inside SiteSuperintendentLog'
    + (inner.length ? ` — found: ${inner.join(', ')}` : ''),
  );

  // NAMED, because these three are the ones that did it and the ones a future
  // edit is most likely to drag back in. A generic sweep that silently stopped
  // matching would still report green.
  ['Field', 'CorrectionChoice', 'EntryList'].forEach((name) => {
    const declaredInBody = new RegExp(`\\b(?:const|let|var|function)\\s+${name}\\b`).test(BODY);
    ok(!declaredInBody, `${name} is not declared inside the screen body`);
  });
}

console.log('\n2. THEY ARE DECLARED AT MODULE SCOPE INSTEAD');
{
  const moduleComponents = declaredComponents(MODULE_SCOPE);
  ['Field', 'CorrectionChoice', 'EntryList'].forEach((name) => {
    ok(moduleComponents.has(name), `${name} is declared at module scope`);
  });
}

console.log('\n3. EVERY JSX ELEMENT TYPE RESOLVES TO A MODULE-LEVEL BINDING');
{
  // THE GENERAL FORM OF THE DEFECT. Naming the three that broke stops those
  // three; this stops the NEXT one, whatever it is called. Anything used as
  // `<Name ...>` must be imported or declared at module scope — the only two
  // places a binding is created once per module rather than once per render.
  const imported = new Set();
  const importRe = /import\s+([\s\S]*?)\s+from\s+['"][^'"]+['"]/g;
  let im;
  while ((im = importRe.exec(CODE)) !== null) {
    im[1].replace(/[{}]/g, ' ').split(',').forEach((piece) => {
      const name = piece.trim().split(/\s+as\s+/).pop().trim();
      if (name) imported.add(name);
    });
  }
  const moduleLevel = new Set([...imported, ...declaredComponents(MODULE_SCOPE)]);

  const used = new Set();
  const jsxRe = new RegExp(`<(${PASCAL})[\\s/>]`, 'g');
  let jm;
  while ((jm = jsxRe.exec(CODE)) !== null) used.add(jm[1]);

  ok(used.size >= 8, `the sweep actually found JSX element types (${used.size} distinct)`);
  const unresolved = [...used].filter((n) => !moduleLevel.has(n));
  ok(
    unresolved.length === 0,
    'no JSX element type is bound anywhere but module scope'
    + (unresolved.length ? ` — found: ${unresolved.join(', ')}` : ''),
  );
}

console.log('\n4. NOTHING THE HOISTED COMPONENTS READ IS LEFT TO A CLOSURE');
{
  // A HOIST THAT DROPS A CAPTURE IS WORSE THAN THE BUG IT FIXES. `s` (the
  // pinned stepper styles), `locked` (the read-only state) and `t` (the
  // translator) were all read from the enclosing scope. At module level those
  // names do not exist, so each has to arrive as a prop — and the screen has to
  // pass it at every call site or the field is editable on a filed log.
  const paramsOf = (name) => {
    const at = MODULE_SCOPE.indexOf(`const ${name} = `);
    if (at < 0) return '';
    const open = MODULE_SCOPE.indexOf('({', at);
    const close = MODULE_SCOPE.indexOf('})', open);
    return open < 0 || close < 0 ? '' : MODULE_SCOPE.slice(open, close);
  };
  const DESTRUCTURED = { Field: ['s', 'locked'], CorrectionChoice: ['s', 'locked', 't'], EntryList: ['s', 'locked', 't'] };
  Object.entries(DESTRUCTURED).forEach(([name, names]) => {
    const params = paramsOf(name);
    ok(params.length > 0, `${name}'s destructured prop list is readable at module scope`);
    names.forEach((n) => ok(
      new RegExp(`[{,]\\s*${n}\\s*[,}]`).test(params),
      `${name} takes \`${n}\` as a prop rather than closing over it`,
    ));
  });

  // EVERY `<Field`/`<CorrectionChoice`/`<EntryList` CALL SITE PASSES THEM.
  // One that forgets `locked` renders an editable input on a frozen statutory
  // record, and one that forgets `s` renders unstyled ink on the pinned light
  // canvas — both silent.
  const callSites = (name) => {
    const out = [];
    const re = new RegExp(`<${name}\\b`, 'g');
    let m;
    while ((m = re.exec(CODE)) !== null) {
      // Balanced to the closing `/>` of this element, tolerating nested braces.
      let depth = 0;
      for (let i = m.index; i < CODE.length; i += 1) {
        if (CODE[i] === '{') depth += 1;
        else if (CODE[i] === '}') depth -= 1;
        else if (depth === 0 && CODE[i] === '>') { out.push(CODE.slice(m.index, i + 1)); break; }
      }
    }
    return out;
  };

  const REQUIRED = {
    Field: ['s', 'locked'],
    CorrectionChoice: ['s', 'locked', 't'],
    EntryList: ['s', 'locked', 't'],
  };
  Object.entries(REQUIRED).forEach(([name, props]) => {
    const sites = callSites(name);
    ok(sites.length > 0, `${name} has call sites to check (${sites.length})`);
    props.forEach((p) => {
      // WORD-BOUNDED. `site.includes('s=')` matches `entries=` and `setEntries=`,
      // so every <EntryList> reported that it passed `s` while passing neither
      // `s` nor `locked` — a vacuous green on the exact prop whose absence
      // leaves a filed log editable.
      const re = new RegExp(`\\b${p}=`);
      const missing = sites.filter((site) => !re.test(site)).length;
      ok(missing === 0, `every <${name}> passes ${p} (${missing} missing)`);
    });
  });

  // TEN, NOT TWELVE, NOT FIFTEEN — AND EVERY DEPARTURE IS NAMED.
  //
  // The count is here to notice a call site that quietly stops passing `s` or
  // `locked` by disappearing, so it has to move whenever the screen's field
  // list really changes. It has now moved twice, and each time the reason is
  // written down rather than the number simply lowered:
  //
  //   15 -> 12  `arrived_at`, `departed_at` and a finding's `observed_at`
  //             became TimeField pickers, asserted on the line below.
  //    9 -> 10  ITEM 8 GAINED A SECOND CALL SITE, NOT A REPLACEMENT. The
  //             competent person is a PICK now, and the two Fields are the
  //             two states a pick has: the read-only one on a filed log, and
  //             the typed one behind the picker's explicit second tap. Both
  //             carry `locked` -- the first as true because a picker over a
  //             frozen statutory record would offer to change what cannot
  //             change, the second as false because it only exists while he
  //             is entering a name by hand.
  //   12 ->  9  the PRINTED NAME, the INSPECTION DATE and the second
  //             ACTIVITIES box were removed as duplicates. The name was asked at the top of the screen and
  //             again on the signature pad, where it arrives prefilled from
  //             the session and stays editable. The inspection date defaulted
  //             to the log's own date at all three entry points and had no
  //             reader anywhere outside this screen. The activities box asked
  //             for what the box above it already asked for -- its own
  //             placeholder said "Areas and floors you inspected" under a
  //             label reading "WHAT YOU DID, AND WHERE".
  //
  // Both removals are asserted by their own tests — the name by the pad still
  // receiving `onNameChange`, the date by `inspectedOn` being absent from the
  // screen (siteSuperintendentSign.test.cjs section 5). Lowering the number
  // without those would let a Field deleted for some other reason ride in.
  ok(callSites('Field').length === 10, `Field is used at 10 call sites (found ${callSites('Field').length})`);
  ok(callSites('TimeField').length === 3,
    `and the three that left are TimeField pickers (found ${callSites('TimeField').length})`);
  // NOT A FREE-TEXT BOX ANYWHERE NEAR A TIME. `placeholder="HH:MM"` was the
  // tell: a text input asking a superintendent to type a clock time, on the
  // two fields BC 3301.13.13 exists to record.
  ok(!/placeholder="HH:MM"/.test(CODE),
    'no field on this screen still asks him to TYPE a time');
}

console.log(
  failures === 0
    ? '\nPASS — the screen builds its inputs from module-level components.'
    : `\n${failures} FAILED`,
);
process.exit(failures === 0 ? 0 : 1);
