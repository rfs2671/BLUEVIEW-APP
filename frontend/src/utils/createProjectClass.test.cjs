/**
 * THE CREATE FORM MUST NOT ASSERT A CLASSIFICATION.
 *
 * server.py:9282 treats ANY client-supplied project_class as an ADMIN OVERRIDE
 * and stamps classification_source = "admin". The form defaulted to 'regular'
 * and sent it on every create, so every project made here recorded a human
 * §3310 decision that nobody made — and the server's own measure-and-classify
 * path never ran.
 */
const fs=require('fs'),path=require('path');
let p=0,f=0; const ok=(c,l)=>{if(c){p++;console.log('  PASS ',l);}else{f++;console.log('  FAIL ',l);}};
const src=fs.readFileSync(path.join(__dirname,'..','..','app','projects','index.jsx'),'utf8');

console.log('\n-- the field starts unset --');
ok(/project_class: null,\n  \}\);/.test(src.replace(/\r/g,'')) || /project_class: null,/.test(src),
  'initial state is null, not a real class');
ok(!/project_class: 'regular'/.test(src),
  "no 'regular' default survives anywhere in the form");
ok(/setNewProject\(\{ address: '', project_class: null \}\)/.test(src),
  'and the reset after a successful create does not reinstate one');

console.log('\n-- nothing is sent unless he chose --');
ok(/\.\.\.\(newProject\.project_class \? \{ project_class: newProject\.project_class \} : \{\}\)/.test(src),
  'the key is OMITTED when unset — a key with any value is an override');
// The old form sent it unconditionally; that line must be gone.
ok(!/^\s*project_class: newProject\.project_class,\s*$/m.test(src),
  'the unconditional send is gone');

console.log('\n-- "not assessed" is offered, and is the default --');
// ANCHORED AFTER the null key: 'major_b' also appears in the LIST render far
// earlier in the file, so an unanchored indexOf produced an empty slice and two
// assertions passed on nothing.
const iNull = src.indexOf('{ key: null');
const opts = src.slice(iNull, src.indexOf('major_b', iNull));
ok(/key: null/.test(opts), 'an explicit unset option exists');
ok(/Not assessed/.test(opts), 'and is labelled as such');
ok(src.indexOf('{ key: null') < src.indexOf("{ key: 'regular'"),
  'it is FIRST, so the unset state is the one he starts on');
ok(/key=\{String\(opt\.key\)\}/.test(src),
  'the null key still yields a usable React key');

console.log(`\n${p} passed, ${f} failed`);
if(f>0)process.exit(1);
console.log('ALL PASSED');
