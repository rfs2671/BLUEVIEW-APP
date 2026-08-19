const fs = require('fs'); const path = require('path');
let p=0,f=0; const ok=(c,l)=>{if(c){p++;console.log('  PASS ',l);}else{f++;console.log('  FAIL ',l);}};
const src = fs.readFileSync(path.join(__dirname,'dayStateModel.js'),'utf8');
const M = new Function(src.replace(/export const /g,'const ').replace(/export function /g,'function ')
  .replace(/export default[\s\S]*$/,'') +
  '\nreturn {DAY_WORKED,DAY_RAIN,DAY_SHUTDOWN,DAY_STATES,dayState,isNoWorkDay,isDayStateId,crewWorkRequired,retainedWork};')();

console.log('\n-- three states, mutually exclusive, worked by default --');
ok(M.DAY_STATES.length === 3, 'exactly three states — no fourth was invented');
ok(M.DAY_STATES[0] === M.DAY_WORKED, 'worked is first, and is the default');
ok(new Set(M.DAY_STATES).size === 3, 'and they are distinct');
[null, undefined, '', 'junk', 0, {}, 'RAIN_NO_WORK'].forEach((bad) => {
  ok(M.dayState(bad) === M.DAY_WORKED,
    `an unrecognised value (${String(bad)}) reads as worked, never as a washout`);
});
ok(M.dayState(M.DAY_RAIN) === M.DAY_RAIN && M.dayState(M.DAY_SHUTDOWN) === M.DAY_SHUTDOWN,
  'a real state survives normalisation');
ok(!M.isNoWorkDay(undefined),
  'a legacy log with no day state is a day somebody worked — never asserted as rain');
ok(M.isNoWorkDay(M.DAY_RAIN) && M.isNoWorkDay(M.DAY_SHUTDOWN), 'both no-work states read as such');

console.log('\n-- the day state is NOT an activity --');
// The ranker reads yesterday's activity_ids. A rain pseudo-activity on every
// crew would feed the graph a day of work that never happened.
ok(M.isDayStateId('rain_no_work') && M.isDayStateId('shutdown'),
  'both ids are recognised as day state, not activity');
['site_cleanup','material_delivery','inspection','hoisting','excavation'].forEach((id) => {
  ok(!M.isDayStateId(id), `${id} is a real activity and is NOT day state`);
});

console.log('\n-- #167 relaxes for activity/location, and only then --');
ok(M.crewWorkRequired(M.DAY_WORKED), 'a worked day still demands what each crew did');
ok(!M.crewWorkRequired(M.DAY_RAIN) && !M.crewWorkRequired(M.DAY_SHUTDOWN),
  'a no-work day does not — the gate would block the day the log exists to record');
ok(M.crewWorkRequired(undefined), 'and an unknown state fails CLOSED, still demanding work');

console.log('\n-- the morning is not erased --');
const half = [{work_description:'Formwork', work_locations:'Fl 3'}, {work_description:''}];
ok(M.retainedWork(half, M.DAY_RAIN).length === 1,
  'work typed before the day turned is RETAINED and reported, not cleared');
ok(M.retainedWork(half, M.DAY_WORKED).length === 0,
  'and nothing is flagged on an ordinary day');
ok(M.retainedWork([{work_locations:'Fl 3'}], M.DAY_RAIN).length === 1,
  'a location alone counts as work he described');
[null, undefined, 'x'].forEach((bad) => ok(Array.isArray(M.retainedWork(bad, M.DAY_RAIN)),
  'garbage in returns a list rather than throwing'));
// There must be no clearing helper at all — the shape is the guarantee.
ok(!/clearWork|resetActivities|wipe/.test(src), 'no clearing function exists to be called by mistake');

console.log(`\n${p} passed, ${f} failed`);
if (f > 0) process.exit(1);
console.log('ALL PASSED');
