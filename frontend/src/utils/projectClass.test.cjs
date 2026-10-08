const fs=require('fs'),path=require('path');
let p=0,f=0; const ok=(c,l)=>{if(c){p++;console.log('  PASS ',l);}else{f++;console.log('  FAIL ',l);}};
const src=fs.readFileSync(path.join(__dirname,'projectClass.js'),'utf8');
const M=new Function(src.replace(/export const /g,'const ').replace(/export default[\s\S]*$/,'')
 +'\nreturn {VALID_PROJECT_CLASSES,classificationAssessed,isMajorClass};')();

console.log('\n-- an absence is not an answer --');
[undefined,null,{},{project_class:null},{project_class:''},{project_class:'junk'},
 {project_class:'REGULAR'}].forEach((bad)=>ok(!M.classificationAssessed(bad),
  `unassessed: ${JSON.stringify(bad)}`));
['regular','major_a','major_b'].forEach((c)=>ok(M.classificationAssessed({project_class:c}),
  `${c} is assessed`));

console.log('\n-- unassessed is NOT major, and not regular either --');
ok(!M.isMajorClass({}), 'an unassessed project is not treated as major');
ok(!M.isMajorClass({project_class:'regular'}), 'and regular is not major');
ok(M.isMajorClass({project_class:'major_a'}) && M.isMajorClass({project_class:'major_b'}),
  'both major classes are');
// The bug in one line: neither predicate may answer "regular" for an absence.
ok(!M.classificationAssessed({}) && !M.isMajorClass({}),
  'an absent class answers NEITHER question — it is a third state');

console.log('\n-- the screens read the predicate, not project_class --');
const SS=fs.readFileSync(path.join(__dirname,'..','..','app','admin','safety-staff.jsx'),'utf8');
ok(/isMajorClass\(p\) \|\| !classificationAssessed\(p\)/.test(SS),
  'the project list INCLUDES unassessed projects — they were invisible before');
ok(/const classAssessed = classificationAssessed\(selectedProject\)/.test(SS),
  'and the classification is its own state on the screen');
ok(/needsSSC = staffKnown && classAssessed/.test(SS)
  && /needsSSM = staffKnown && classAssessed/.test(SS),
  'no staffing verdict is computed before the class is known');
ok(/!classAssessed && \(/.test(SS) && /Classification not assessed/.test(SS),
  'and the screen EXPLAINS rather than silently answering no');
ok(/Site Safety Coordinator/.test(SS) && /Site Safety Manager/.test(SS),
  'naming what each class would require, so the absence is actionable');
// EXPLAIN, DO NOT GATE.
ok(!/if \(!classAssessed\) return null/.test(SS),
  'it never blocks the screen an admin opened to understand something');

// ── THE SECOND SUBJECT WAS app/admin/superintendent.jsx, AND IT IS DELETED ──
//
// Five assertions read that file (operator ruling, 2026-10-08: "OUTSIDE SUPERS:
// DELETE THE TAB. There is no such case."). What they said, verbatim in effect:
//
//   !/\|\| 'regular'\)\.toLowerCase\(\)/      the client-side coercion is gone
//   SU_CODE.length > 0                        the strip produced something
//   !/not_assessed/ on SU_CODE                no NOT ASSESSED badge survives
//   /CLASS_BADGES\[cls\] \|\| CLASS_BADGES\.regular/
//                                             an unknown key renders REGULAR
//
// and the note beside them recorded that the last two USED TO BE THE EXACT
// OPPOSITE and were right at the time: an absent class meant nobody had
// assessed the §3310 classification, so rendering REGULAR asserted a finding
// nobody had made. The operator then ruled that a project STARTS regular and an
// admin changes it when the project changes, which left no unassessed state to
// badge. That history is kept here because it is the reason the polarity is
// what it is, and nothing about the ruling above revisits it.
//
// ── TWO OF THEM ARE RE-POINTED, AND WIDER THAN BEFORE ───────────────────────
//
// The coercion rule and the no-NOT-ASSESSED-badge rule were never facts about
// one screen; they were facts about how any screen may read `project_class`.
// Asserted on ONE file, they went green the moment that file was deleted, which
// is the weaker reading. They are now asked of every screen and utility, so a
// third reader of `project_class` is covered the day it is written.
//
// ── AND ONE IS NOT, BECAUSE IT HAS NO SUBJECT LEFT ──────────────────────────
//
// `CLASS_BADGES[cls] || CLASS_BADGES.regular` was the deleted screen's badge
// map, and admin/safety-staff.jsx — the only other CLASS_BADGES in the repo —
// is a DIFFERENT shape on purpose: two keys (major_a, major_b), no `regular`
// entry, and `if (!spec) return null`, so it renders no badge at all for a
// regular or absent class rather than defaulting to one. Re-pointing the
// assertion there would have asserted a default that screen deliberately does
// not have. It is recorded, not relocated.
const SOURCES = (() => {
  const out = [];
  const walk = (dir) => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, e.name);
      if (e.isDirectory()) { if (e.name !== 'node_modules') walk(full); continue; }
      if (!/\.(jsx?|tsx?)$/.test(e.name)) continue;
      if (/\.test\.(c?js|tsx?)$/.test(e.name)) continue;
      out.push(full);
    }
  };
  walk(path.join(__dirname, '..', '..', 'app'));
  walk(path.join(__dirname, '..'));
  return out;
})();
// COMMENT-STRIPPED, for the reason the old note gave about one file and which
// now applies to all of them: projectClass.js's own header NAMES the
// `(p.project_class || 'regular')` pattern as the thing it exists to prevent,
// and a raw scan would read that explanation as the thing it explains.
const STRIP = (s) => s
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
  .replace(/(?<!:)\/\/.*$/gm, '');
ok(SOURCES.length > 20, `the source sweep found files at all (${SOURCES.length})`);
{
  const bad = SOURCES.filter((f) => /\|\| *'regular'\) *\.toLowerCase\(\)/
    .test(STRIP(fs.readFileSync(f, 'utf8'))));
  ok(bad.length === 0,
    "the `|| 'regular').toLowerCase()` fallback undoes the API fix "
    + `client-side: ${bad.map((f) => path.basename(f)).join(', ')}`);
}
{
  const bad = SOURCES.filter((f) => /not_assessed/
    .test(STRIP(fs.readFileSync(f, 'utf8'))));
  ok(bad.length === 0,
    'a NOT ASSESSED badge survives — there is no unassessed state to show: '
    + `${bad.map((f) => path.basename(f)).join(', ')}`);
}

console.log(`\n${p} passed, ${f} failed`);
if(f>0)process.exit(1);
console.log('ALL PASSED');
