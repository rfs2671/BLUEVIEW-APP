// Run: node src/utils/projectReports.test.cjs
const { loadEsm } = require('./esmHarness.cjs');
const M = loadEsm('src/utils/projectReports.js');

let pass = 0, fail = 0;
function ok(cond, label) {
  if (cond) { pass++; console.log(`  PASS  ${label}`); } else { fail++; console.log(`  FAIL  ${label}`); }
}

ok(M.canSeeReports({ role: 'admin' }) && M.canSeeReports({ role: 'pm' }), 'admin and PM see Reports');
ok(!M.canSeeReports({ role: 'cp' }) && !M.canSeeReports(null), 'others do not');
ok(M.periodLabel('2026-10-01', '2026-10-14') === 'Oct 1 – Oct 14, 2026', 'period in one year');
ok(M.periodLabel('2026-12-21', '2027-01-03') === 'Dec 21, 2026 – Jan 3, 2027', 'period across years');
ok(M.periodLabel(null, '2026-10-14') === '', 'no dates, no label');
ok(M.scheduleLabel('biweekly') === 'Every 2 weeks (Monday 8am)', 'bi-weekly says when');
ok(M.scheduleLabel('monthly') === 'Monthly (1st of the month, 8am)', 'monthly says when');
ok(M.scheduleLabel('nonsense') === 'Off', 'unknown schedule reads as off');
ok(M.sourceLabel('schedule') === 'Scheduled' && M.sourceLabel('dm') === 'Asked in WhatsApp'
   && M.sourceLabel('app') === 'Made in the app', 'where a report came from');
ok(M.pdfName({ title: '588 Thomas S Boyland St — Oct 1–14' }) === '588-Thomas-S-Boyland-St-Oct-114.pdf',
   'a safe file name');
const body = M.scheduleBody('weekly', ['a', 'a', 7]);
ok(body.schedule === 'off' && body.pm_ids.join(',') === 'a,7', 'schedule body: known schedule, unique PMs');
ok(M.RANGE_CHOICES.map((r) => r.key).join('|') === 'last 2 weeks|this month|last month', 'generate periods');

// Project → Reports, B: presets, schedules in any combination, recipients, delivery, the list.
ok(M.PRESETS.map((p) => p.key).join('|')
   === 'last_7_days|last_2_weeks|this_month|last_month|this_quarter|whole_project|custom', 'generate presets');
ok(M.KINDS.map((k) => k.key).join('|') === 'daily|weekly|biweekly|monthly|quarterly', 'schedule kinds');
ok(M.toggled(['weekly'], 'monthly').sort().join() === 'monthly,weekly'
   && M.toggled(['weekly', 'monthly'], 'weekly').join() === 'monthly', 'toggle in and out');
const sb = M.settingsBody(['quarterly', 'nope', 'daily'], ['u1', 'u1', 2], { email: 1 });
ok(sb.schedules.join() === 'daily,quarterly' && sb.recipient_ids.join() === 'u1,2'
   && sb.delivery.whatsapp === false && sb.delivery.email === true, 'settings body: known kinds in order');
ok(M.rangeProblem('2026-10-01', '2026-10-14') === '', 'a good custom range');
ok(/MM\/DD\/YYYY/.test(M.rangeProblem('', '2026-10-14')), 'a missing date says the format');
ok(/before/.test(M.rangeProblem('2026-10-14', '2026-10-01')), 'end before start');
ok(/400/.test(M.rangeProblem('2024-01-01', '2026-10-01')), 'too long');
ok(M.whoLine({ kind_label: 'Weekly', source: 'schedule', source_label: 'Scheduled', requested_by: 'Schedule' })
   === 'Weekly · Scheduled', 'a scheduled report');
ok(M.whoLine({ source: 'dm', source_label: 'Asked in WhatsApp', requested_by: 'Pat PM' })
   === 'Asked in WhatsApp by Pat PM', 'who asked');
ok(M.madeLabel('2026-10-15T20:00:00Z') === 'Oct 15, 2026', 'when it was made, New York');
ok(M.shareText({ title: 'Progress report', link: 'https://x/r.pdf' }) === 'Progress report\nhttps://x/r.pdf'
   && M.shareText({ title: 't' }) === '', 'share text only with a link');
const fs = require('fs');
const screen = fs.readFileSync(require('path').join(__dirname, '..', '..', 'app/projects/[id]/reports.jsx'), 'utf8');
ok(/DateInput/.test(screen) && /toStoredDate/.test(screen), 'custom dates through the shared DateInput');
ok(/PRESETS/.test(screen) && /KINDS/.test(screen) && /recipient_ids/.test(screen)
   && /delivery/.test(screen), 'the screen: presets, schedules, recipients, delivery');
ok(/'Open'/.test(screen) && /'Download'/.test(screen) && /'Share'/.test(screen)
   && /whoLine/.test(screen), 'the list: open, download, share, who asked');
ok(/can_edit/.test(screen), 'edit only when the server says so');
ok(!/Bearer \$\{token\}`\s*\)/.test(screen) || /headers: \{ Authorization/.test(screen),
   'the token only in a header');

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
