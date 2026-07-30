/**
 * Regression test for the Report Settings brace bug.
 *
 * fetchProject() reads report_email_list / report_send_time from the SERVER
 * (projectsAPI.getById) and must push them into state via setEmailList /
 * setSendTime. A missing `}` after the `throw` had trapped setProject /
 * setEmailList / setSendTime inside `if (!projectData) { … }`, so on the success
 * path they never ran and the screen reopened empty.
 *
 * This extracts the REAL fetchProject body verbatim from report-settings.jsx and
 * runs it with stubbed deps. It asserts the fetched values reach the setters —
 * which FAILS against the brace placement (setters trapped in the if) and passes
 * once the brace is fixed.
 *
 * Run:  node src/utils/reportSettingsFetch.test.cjs
 */
const fs = require('fs');
const path = require('path');

const file = path.join(__dirname, '..', '..', 'app', 'project', '[id]', 'report-settings.jsx');
const src = fs.readFileSync(file, 'utf8');

// Extract the `const fetchProject = async () => { … }` body verbatim.
const anchor = 'const fetchProject = async () => {';
const at = src.indexOf(anchor);
if (at < 0) throw new Error('fetchProject not found in report-settings.jsx');
const braceStart = src.indexOf('{', at + anchor.length - 1);
let depth = 0, i = braceStart;
for (; i < src.length; i += 1) {
  if (src[i] === '{') depth += 1;
  else if (src[i] === '}') { depth -= 1; if (depth === 0) { i += 1; break; } }
}
const body = src.slice(braceStart, i); // includes the outer { … }

// Build a callable with the component's closure vars injected as params.
// console / Error are globals; the rest are stubbed.
const make = new Function(
  'projectsAPI', 'setProject', 'setEmailList', 'setSendTime', 'setLoading', 'toast', 'projectId',
  `return (async () => ${body});`,
);

let passed = 0, failed = 0;
const ok = (c, l) => { if (c) { passed += 1; console.log('  PASS  ' + l); } else { failed += 1; console.log('  FAIL  ' + l); } };

(async () => {
  const captured = {};
  const SERVER = { report_email_list: ['rfs2671@gmail.com'], report_send_time: '17:00', id: 'p1' };
  const fetchProject = make(
    { getById: async () => SERVER },
    (v) => { captured.project = v; },
    (v) => { captured.emailList = v; },
    (v) => { captured.sendTime = v; },
    () => {},
    { error: () => {}, success: () => {}, info: () => {} },
    'p1',
  );
  await fetchProject();

  ok(Array.isArray(captured.emailList) && captured.emailList[0] === 'rfs2671@gmail.com',
    'fetched report_email_list reaches setEmailList');
  ok(captured.sendTime === '17:00', 'fetched report_send_time reaches setSendTime');
  ok(captured.project === SERVER, 'fetched project reaches setProject');

  console.log(`\n${passed} passed, ${failed} failed`);
  if (failed > 0) process.exit(1);
  console.log('ALL PASSED');
})().catch((e) => { console.error(e); process.exit(2); });
