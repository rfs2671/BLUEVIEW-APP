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

const SU=fs.readFileSync(path.join(__dirname,'..','..','app','admin','superintendent.jsx'),'utf8');
ok(!/\|\| 'regular'\)\.toLowerCase\(\)/.test(SU),
  "the `|| 'regular'` fallback is gone — it undid the API fix client-side");
ok(/not_assessed: \{ label: 'NOT ASSESSED'/.test(SU), 'a NOT ASSESSED badge exists');
ok(/CLASS_BADGES\[cls\] \|\| CLASS_BADGES\.not_assessed/.test(SU),
  'and an unknown key falls back to NOT ASSESSED, never to a real class');

console.log(`\n${p} passed, ${f} failed`);
if(f>0)process.exit(1);
console.log('ALL PASSED');
