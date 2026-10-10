// Run: node src/utils/projectMemory.test.cjs
const fs = require('fs');
const path = require('path');
const { loadEsm } = require('./esmHarness.cjs');
const M = loadEsm('src/utils/projectMemory.js');

let pass = 0, fail = 0;
function ok(cond, label) {
  if (cond) { pass++; console.log(`  PASS  ${label}`); } else { fail++; console.log(`  FAIL  ${label}`); }
}

ok(M.canSearch({ role: 'admin' }) && M.canSearch({ role: 'PM' }), 'admin and PM search');
ok(!M.canSearch({ role: 'superintendent' }) && !M.canSearch({ role: 'cp' }) && !M.canSearch(null),
  'others do not');
ok(M.canSearch({ role: 'cp', is_platform_operator: true }), 'the operator does');
ok(M.cleanQuery(' a ').error, 'one letter is not a search');
ok(M.cleanQuery('  who said   window ').query === 'who said window', 'spaces folded');
ok(M.chipText({ source: 'whatsapp', who: 'Mike Rivera', group: 'MEP', when: 'Oct 3, 7:42 AM' })
  === 'Mike Rivera · MEP · Oct 3, 7:42 AM', 'message chip');
ok(M.chipText({ source: 'daily_report', label: 'Observation', when: 'Sep 25' })
  === 'Daily report · Observation · Sep 25', 'daily report chip');
ok(M.chipText({ source: 'whatsapp', group: 'Site' }) === 'Someone · Site', 'no name: Someone');
ok(M.preview('x'.repeat(300)).length === 220 && M.preview('a  b') === 'a b', 'preview cut and folded');
ok(M.opensContext({ source: 'whatsapp', id: 'wa:1' }) && !M.opensContext({ source: 'attention', id: 'x' }),
  'messages and reports open in context; tracked items do not');
ok(M.answerState({ claims: [] }).text === M.NO_SOURCE, 'no claims: no source');
ok(M.answerState({ mode: 'timeline', claims: [{ text: 'x' }] }).timeline, 'timeline');
ok(M.answerState(null) === null, 'no answer asked');
ok(M.answerState({ claims: [{ text: 'x' }], lead: 'No record that the dumpster was swapped.' }).lead
   === 'No record that the dumpster was swapped.', 'lead carried');
ok(M.answerState({ claims: [{ text: 'x' }] }).lead === '', 'no lead');
ok(M.claimLine({ text: 'Pump planned (Roy Fishman, Sep 28) — not confirmed as done', planned: true,
                 relayed_by: 'Roy Fishman' }, false)
   === 'Pump planned (Roy Fishman, Sep 28) — not confirmed as done', 'a plan line has no relay note');
ok(M.claimLine({ text: 'The owner wanted a casement', relayed_by: 'Wendy Cho' }, false)
  === 'The owner wanted a casement (relayed by Wendy Cho)', 'relayed decision says who relayed it');
ok(M.claimLine({ text: 'Install planned', date: 'Oct 1' }, true) === 'Oct 1 — Install planned', 'timeline line');
const many = M.claimSources({ quote: 'q1', source: { id: 'wa:1', who: 'Dave' },
  also: [{ id: 'dr:1:a', source: 'daily_report', quote: 'q2' }] });
ok(many.length === 2 && many[0].quote === 'q1' && many[1].quote === 'q2', 'one fact, every source');
ok(M.claimSources({}).length === 0, 'no source, no chip');

const screen = fs.readFileSync(path.join(__dirname, '../../app/projects/[id]/search.jsx'), 'utf8');
ok(/memoryAPI\.search\(/.test(screen) && /memoryAPI\.context\(/.test(screen), 'the screen searches and opens context');
ok(/chipText\(/.test(screen), 'every result shows its source chip');
ok(/claimSources\(c\)/.test(screen) && /claimLine\(c, answer\.timeline\)/.test(screen),
  'an answer shows who relayed it and every source of a fact');
ok(/answer.lead/.test(screen), 'the answer shows its "No record that …" lead');
ok(!/sendWhatsApp|whatsappAPI\.send/.test(screen), 'the screen sends nothing to anyone');
ok(/setResults\(null\);\s*\n\s*setAnswer\(null\);/.test(screen),
  'a new search clears the last results before asking');
const api = fs.readFileSync(path.join(__dirname, 'api.js'), 'utf8');
ok(/\/memory\/search/.test(api) && /\/memory\/context\//.test(api), 'api paths');
const project = fs.readFileSync(path.join(__dirname, '../../app/project/[id].jsx'), 'utf8');
ok(!/\/projects\/\$\{projectId\}\/search/.test(project) && !/title: 'Search'/.test(project),
  'no Search tile on the project screen (search is in the WhatsApp DM assistant)');

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
