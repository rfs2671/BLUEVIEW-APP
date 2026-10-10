// Run: node src/utils/upcoming.test.cjs
const fs = require('fs');
const path = require('path');
const { loadEsm } = require('./esmHarness.cjs');
const M = loadEsm('src/utils/upcoming.js');

let pass = 0, fail = 0;
function ok(cond, label) {
  if (cond) { pass++; console.log(`  PASS  ${label}`); } else { fail++; console.log(`  FAIL  ${label}`); }
}

ok(M.canSeeUpcoming({ role: 'admin' }) && M.canSeeUpcoming({ role: 'pm' }), 'admin and PM');
ok(!M.canSeeUpcoming({ role: 'cp' }) && !M.canSeeUpcoming(null), 'not others');

const evs = [
  { id: 'b', date: '2026-12-04', time: null, title: 'DOB permit expires', status: 'open', day_label: 'Fri Dec 4' },
  { id: 'a', date: '2026-12-04', time: '09:00', time_label: '9am', title: 'Con Ed', status: 'open', day_label: 'Fri Dec 4' },
  { id: 'c', date: '2026-12-01', title: 'Hearing', status: 'open', day_label: 'Tue Dec 1' },
  { id: 'd', date: '2026-12-02', title: 'Gone', status: 'dismissed' },
];
const days = M.byDay(evs);
ok(days.map((d) => d.label).join('|') === 'Tue Dec 1|Fri Dec 4', 'grouped by day, in order');
ok(days[1].events.map((e) => e.id).join('') === 'ab', 'timed first, untimed last');
ok(!days.some((d) => d.events.some((e) => e.id === 'd')), 'dismissed not shown');
ok(M.byDay(null).length === 0, 'nothing: no days');
ok(M.eventLine(evs[1]) === '9am — Con Ed' && M.eventLine(evs[0]) === 'DOB permit expires', 'event line');
ok(M.evidenceLine({ source: 'chat', quote: 'Con Ed coming Dec 4', who: 'Roy' }) === '“Con Ed coming Dec 4” — Roy',
  'chat events show their words and who said them');
ok(M.evidenceLine({ source: 'city', quote: 'x' }) === '', 'city events have no quote line');
ok(M.movedLine({ history: [{ action: 'created' }, { action: 'rescheduled', frm: '2026-12-02', to: '2026-12-04' }] })
  === 'Moved from 2026-12-02', 'a moved event says so');
ok(M.movedLine({ history: [] }) === '', 'not moved: nothing');
ok(M.cleanEdit({ date: '2026-12-09', time: '07:30' }).patch.time === '07:30', 'a good edit');
ok(M.cleanEdit({ date: '12/9', time: '' }).error, 'a bad date is refused here');
ok(M.cleanEdit({ date: '2026-12-09', time: '7am' }).error, 'a bad time is refused here');
ok(M.cleanEdit({ date: '', time: '' }).patch.time === '', 'clearing the time is allowed');

const screen = fs.readFileSync(path.join(__dirname, '../../app/projects/[id]/upcoming.jsx'), 'utf8');
ok(/upcomingAPI\.list\(/.test(screen) && /upcomingAPI\.dismiss\(/.test(screen) && /upcomingAPI\.edit\(/.test(screen),
  'the screen lists, dismisses and edits');
ok(/upcomingAPI\.makeFeed\(/.test(screen) && /upcomingAPI\.revokeFeed\(/.test(screen), 'and makes / revokes the feed');
ok(/evidenceLine\(/.test(screen) && /e\.chip/.test(screen), 'source chip and the words it came from');
ok(!/sendWhatsApp|whatsappAPI\.send/.test(screen), 'the screen sends nothing to anyone');
const project = fs.readFileSync(path.join(__dirname, '../../app/project/[id].jsx'), 'utf8');
ok(/\/projects\/\$\{projectId\}\/upcoming/.test(project) && /canSeeUpcoming\(user\)/.test(project),
  'the project screen opens it for admins and PMs');
const api = fs.readFileSync(path.join(__dirname, 'api.js'), 'utf8');
ok(/\/upcoming`/.test(api) && /\/api\/me\/calendar-feed/.test(api), 'api paths');
const panel = fs.readFileSync(path.join(__dirname, '../components/WhatsAppAssistantPanel.jsx'), 'utf8');
ok(/upcoming_reminders/.test(panel), 'the day-before DM can be turned off');

console.log(`\n${pass} passed, ${fail} failed`);
if (fail) process.exit(1);
