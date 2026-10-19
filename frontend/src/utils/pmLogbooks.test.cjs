// Run: node src/utils/pmLogbooks.test.cjs
//
// THE SITE MANAGER / PM CAN REACH LOG BOOKS, READ FILED LOGS, AND ADD
// PHOTOGRAPHS — AND IS NEVER INVITED TO WRITE ONE.
//
// The server always allowed it (ROLES_WITH_READ_ONLY_LOGBOOKS: read + append
// photographs; refuse create/edit/finalize/amend/delete), but nothing in his
// nav or on his project screen linked to /logbooks.
const fs = require('fs');
const path = require('path');
const { loadEsm } = require('./esmHarness.cjs');
const M = loadEsm('src/utils/pmLogbooks.js');

const FRONTEND = path.join(__dirname, '..', '..');
const read = (rel) => fs.readFileSync(path.join(FRONTEND, rel), 'utf8');
let pass = 0, fail = 0;
function ok(cond, label) {
  if (cond) { pass++; console.log(`  PASS  ${label}`); } else { fail++; console.log(`  FAIL  ${label}`); }
}

// ── who ──
ok(M.readsLogbooksOnly({ role: 'pm' }) && M.readsLogbooksOnly({ role: ' PM ' }), 'a PM reads log books only');
ok(!M.readsLogbooksOnly({ role: 'cp' }) && !M.readsLogbooksOnly({ role: 'superintendent' })
  && !M.readsLogbooksOnly({ role: 'admin' }) && !M.readsLogbooksOnly(null), 'filers and admins are unchanged');
ok(M.canOpenLogBooksTile({ role: 'pm' }) && !M.canOpenLogBooksTile({ role: 'admin' }), 'the project tile is the PM\'s');

// ── which jobs (the server's project_access_ok split) ──
const jobs = [{ id: 'a', name: '588' }, { _id: 'b', name: '9 Menahan' }, { id: 'c', name: '12 Main' }];
const assigned = M.pmLogbookProjects({ role: 'pm', assigned_projects: ['b', 'c'] }, jobs);
ok(assigned.map((p) => p.name).join(',') === '9 Menahan,12 Main', 'assigned PM: his jobs only (id or _id)');
ok(M.pmLogbookProjects({ role: 'pm', pm_access: 'assigned' }, jobs).length === 0, 'assigned PM with no jobs: none');
ok(M.pmLogbookProjects({ role: 'pm', pm_access: 'full', assigned_projects: [] }, jobs).length === 3,
  '"Same as admin" PM: every job');
ok(M.pmLogbookProjects({ role: 'cp' }, jobs).length === 3, 'others pass through to the screen\'s own rule');
ok(M.pmLogbookProjects({ role: 'pm' }, null).length === 0, 'no list, no crash');

// ── what opens ──
ok(M.pmMayOpen('submitted'), 'a filed log opens (read-only view + photographs)');
ok(!M.pmMayOpen('draft') && !M.pmMayOpen('pending') && !M.pmMayOpen('period_done') && !M.pmMayOpen(null),
  'a draft, an unstarted or a weekly-elsewhere log does not');

// ── the way in ──
const project = read('app/project/[id].jsx');
ok(/canOpenLogBooksTile\(user\)\s*\?\s*\[\{\s*title: 'Log Books'[^\]]*path: `\/logbooks\?projectId=\$\{projectId\}`/.test(project),
  'project screen: a Log Books tile for the PM, opening that job');
ok(/\n\s+BookOpen,\n\} from 'lucide-react-native';/.test(project), 'the tile\'s icon is imported');

// ── the hub ──
const hub = read('app/logbooks/index.jsx');
ok(/const \{ projectId: requestedProjectId \} = useLocalSearchParams\(\)/.test(hub), 'hub reads ?projectId=');
ok(/if \(readOnly\) return pmLogbookProjects\(user, arr\);/.test(hub), 'hub lists the PM\'s jobs only');
ok(/picked = initialProject\(cachedVisible\)/.test(hub) && /const first = initialProject\(visibleProjects\)/.test(hub),
  'hub opens on the job he tapped, cached and live');
ok(/if \(readOnly && !pmMayOpen\(filed \? 'submitted' : null\)\) \{[\s\S]{0,500}?PM_NOT_FILED_TITLE[\s\S]{0,40}?return;/.test(hub),
  'an unfiled log is named, not opened');
ok(/const openable = readOnly\s*\?\s*pmMayOpen\(status\)/.test(hub), 'tile chevron/lock follows the PM rule');
ok(/!readOnly && selectedProject && activations\.length > 0/.test(hub), 'site switches hidden from the PM');
ok(/setNotifications\(readOnly \? \{\s*\.\.\.notifs, attestation_gaps: \[\], unaffirmed_logbooks: 0, stale_unsigned_logbooks: 0,/.test(hub),
  '"yours to sign" worklists hidden from the PM');
ok(/\{!readOnly && \(\s*<GlassButton\s*title="Open Tool Box Talk"/.test(hub), 'no "Open Tool Box Talk" for the PM');
ok(/\{readOnly \? <FloatingNav \/> : <CpNav \/>\}/.test(hub), 'the PM keeps his own nav');
ok(/photoTarget && \(\s*<Pressable\s*onPress=\{\(\) => router\.push\(`\/logbooks\/photos\?logbookId=/.test(hub)
  && !/readOnly[^\n]*photoTarget/.test(hub), 'Photographs row is NOT gated on role');

// ── the editor and the lock bar ──
const stepper = read('src/components/logbookStepper/LogbookStepper.jsx');
ok(/const pmNotice = \(readsLogbooksOnly\(user\) && !locked && !loading\)/.test(stepper)
  && /const unavailable = unavailableProp \|\| pmNotice;/.test(stepper) && /if \(unavailable\) \{/.test(stepper),
  'editor: an unfiled log is the no-form notice (no fields, footer or lock bar) for the PM');
const lockBar = read('src/components/LogbookLockBar.jsx');
ok(/\{!readOnly && \(\s*<Pressable style=\{\[s\.btn, s\.amendBtn\]\} onPress=\{\(\) => setAmendOpen\(true\)\}/.test(lockBar),
  'lock bar: no Amend for the PM');
ok(/if \(canFinalize && logId && !signFreezes && !readOnly\)/.test(lockBar), 'lock bar: no Finalize for the PM');

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
