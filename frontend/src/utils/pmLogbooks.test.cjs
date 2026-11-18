// Run: node src/utils/pmLogbooks.test.cjs
//
// THE SITE MANAGER / PM CAN REACH LOG BOOKS, READ FILED LOGS, AND ADD
// PHOTOGRAPHS — AND IS NEVER INVITED TO WRITE ONE.
//
// The server always allowed it (read + append photographs; refuse create/edit/
// finalize/amend), but nothing in his nav or on his project screen linked to
// /logbooks.
//
// OPERATOR RULING 2026-11-18: only the SUPERINTENDENT and the CP fill in and
// sign a log (ROLES_THAT_FILE_LOGBOOKS, an allow-list). A PM at EITHER level and
// an admin read and add photographs. The "Same as admin" PM is no longer exempt.
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
ok(M.readsLogbooksOnly({ role: 'pm' }) && M.readsLogbooksOnly({ role: ' PM ', pm_access: 'assigned' }),
  'a PM on "Assigned jobs only" (or with no level stored) reads log books only');
ok(M.readsLogbooksOnly({ role: 'pm', pm_access: 'full' }),
  'a PM on "Same as admin" reads log books only too (ruling 2026-11-18: no exemption)');
ok(M.canOpenLogBooksTile({ role: 'pm', pm_access: 'full' }), 'and he still gets the tile');
ok(M.readsLogbooksOnly({ role: 'admin' }) && M.readsLogbooksOnly({ role: ' Admin ' }),
  'an admin reads log books only');
ok(M.readsLogbooksOnly({ role: 'owner' }) && M.readsLogbooksOnly({ role: 'worker' }),
  'an allow-list: a role nobody listed reads only');
ok(!M.readsLogbooksOnly({ role: 'cp' }) && !M.readsLogbooksOnly({ role: ' Superintendent ' }),
  'the superintendent and the CP file');
ok(!M.readsLogbooksOnly({ role: 'site_device', site_mode: true }), 'the gate tablet is unchanged');
ok(!M.readsLogbooksOnly(null), 'no user yet: not read-only (auth still loading)');
ok(JSON.stringify(M.ROLES_THAT_FILE_LOGBOOKS) === JSON.stringify(['superintendent', 'cp']),
  'the filers are the two the operator named');
// THE SERVER'S LIST, READ FROM THE SERVER. Two copies of one rule drift; this
// holds them to the same membership.
const serverPy = fs.readFileSync(path.join(FRONTEND, '..', 'backend', 'server.py'), 'utf8');
ok(/\nROLES_THAT_FILE_LOGBOOKS = \(ROLE_SUPERINTENDENT, "cp"\)\r?\n/.test(serverPy),
  'server.py names the same two filers');
ok(M.canOpenLogBooksTile({ role: 'pm' }) && !M.canOpenLogBooksTile({ role: 'admin' }), 'the project tile is the PM\'s');

// ── which jobs (the server's project_access_ok split) ──
const jobs = [{ id: 'a', name: '588' }, { _id: 'b', name: '9 Menahan' }, { id: 'c', name: '12 Main' }];
const assigned = M.pmLogbookProjects({ role: 'pm', assigned_projects: ['b', 'c'] }, jobs);
ok(assigned.map((p) => p.name).join(',') === '9 Menahan,12 Main', 'assigned PM: his jobs only (id or _id)');
ok(M.pmLogbookProjects({ role: 'pm', pm_access: 'assigned' }, jobs).length === 0, 'assigned PM with no jobs: none');
ok(M.pmLogbookProjects({ role: 'pm', pm_access: 'full', assigned_projects: [] }, jobs).length === 3,
  '"Same as admin" PM: every job');
ok(M.pmLogbookProjects({ role: 'cp' }, jobs).length === 3, 'others pass through to the screen\'s own rule');
ok(M.pmLogbookProjects({ role: 'admin', assigned_projects: [] }, jobs).length === 3,
  'an admin (read-only now) still lists every job: read-only is not assigned-only');
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
ok(/\(!readOnly \|\| isAdminUser\) && selectedProject && activations\.length > 0/.test(hub),
  'site switches hidden from the assigned PM, kept for an admin (configuring the job is not filing)');
ok(/setNotifications\(readOnly \? \{\s*\.\.\.notifs, attestation_gaps: \[\], unaffirmed_logbooks: 0, stale_unsigned_logbooks: 0,/.test(hub),
  '"yours to sign" worklists hidden from the PM');
ok(/\{!readOnly && \(\s*<GlassButton\s*title="Open Tool Box Talk"/.test(hub), 'no "Open Tool Box Talk" for the PM');
ok(/\{canOpenLogBooksTile\(user\) \? <FloatingNav \/> : <CpNav \/>\}/.test(hub), 'every PM keeps his own nav');

// ── the two editors that own no LogbookStepper ──
const preshift = read('app/logbooks/preshift_signin.jsx');
ok(/if \(readsLogbooksOnly\(user\) && !locked\) \{\s*return \(/.test(preshift)
  && preshift.indexOf('if (readsLogbooksOnly(user) && !locked)') < preshift.indexOf("title={saving ? 'Saving...' : 'Save Draft'}"),
  'pre-shift: an open sheet is the notice, before Save Draft / Submit can render');
const orient = read('app/logbooks/subcontractor_orientation.jsx');
ok(/\{!readOnly && \(\s*<GlassButton\s*title="\+ Add Manual Orientation"/.test(orient)
  && /\{!readOnly && showAddForm && \(/.test(orient), 'orientation: no Add Manual Orientation for him');
ok(/\{!readOnly && !isSigned && !isLocked && \(\s*<OrientationSignaturePanel/.test(orient)
  && /\{!readOnly && !isSigned && !isLocked && !String\(d\.worker_trade/.test(orient),
  'orientation: no sign panel and no Assign trade for him');
ok(/photoTarget && \(\s*<Pressable\s*onPress=\{\(\) => router\.push\(`\/logbooks\/photos\?logbookId=/.test(hub)
  && !/readOnly[^\n]*photoTarget/.test(hub), 'Photographs row is NOT gated on role');

// ── the editor and the lock bar ──
const stepper = read('src/components/logbookStepper/LogbookStepper.jsx');
ok(/Filing is done by the superintendent or the CP\./.test(M.PM_NOT_FILED_BODY)
  && /Filing is done by the superintendent or the CP\./.test(M.PM_LOGBOOKS_NOTE),
  'the copy names who files');
ok(/const pmNotice = \(readsLogbooksOnly\(user\) && !locked && !loading\)/.test(stepper)
  && /const unavailable = unavailableProp \|\| pmNotice;/.test(stepper) && /if \(unavailable\) \{/.test(stepper),
  'editor: an unfiled log is the no-form notice (no fields, footer or lock bar) for the PM');
const lockBar = read('src/components/LogbookLockBar.jsx');
ok(/\{!readOnly && \(\s*<Pressable style=\{\[s\.btn, s\.amendBtn\]\} onPress=\{\(\) => setAmendOpen\(true\)\}/.test(lockBar),
  'lock bar: no Amend for the PM');
ok(/if \(canFinalize && logId && !signFreezes && !readOnly\)/.test(lockBar), 'lock bar: no Finalize for the PM');

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
