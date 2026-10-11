/**
 * PROJECT → WHATSAPP → VOICE LOG (admins): every voice note of the job.
 *
 * Run:  node src/utils/voiceLog.test.cjs
 */

const fs = require('fs');
const path = require('path');
const { loadEsm } = require('./esmHarness.cjs');

let passed = 0;
let failed = 0;
const ok = (cond, label) => {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
};

const V = loadEsm('src/utils/voiceLog.js');
const read = (p) => fs.readFileSync(path.join(__dirname, '..', '..', p), 'utf8');

console.log('a row');
const g = { id: 'r1', where: 'group', place: '588 – Site', at: '2026-10-11T18:57:00+00:00',
  who: 'Yoel', lang: 'yi', confidence: 0.62, duration_sec: 4.2, transcript: 'מאָרגן',
  english: 'Tomorrow', status: 'flagged', reason: 'yiddish', forwarded: true, audio: true,
  message_row_id: 'r1', produced: [] };
ok(V.whenLabel(g.at) === 'Sun Oct 11, 2:57 PM', `New York time (${V.whenLabel(g.at)})`);
ok(V.headLine(g) === 'forwarded by Yoel · 588 – Site · Yiddish · 62% · 4s', V.headLine(g));
ok(V.headLine({ ...g, where: 'dm', forwarded: false }) === 'Yoel · DM · Yiddish · 62% · 4s', 'a DM');
ok(V.statusLine(g) === 'Flagged — yiddish', 'flagged with why');
ok(V.statusLine({ status: 'not_processed', reason: 'shorter than 2 seconds' })
   === 'Not processed — shorter than 2 seconds', 'not processed with why');
ok(V.statusLine({ status: 'transcribed' }) === 'Transcribed', 'transcribed');

console.log('produced');
ok(V.producedLines(g)[0].text === 'Produced: nothing', 'nothing');
ok(V.producedRoute('p1', V.producedLines(g)[0]) === null, 'nothing goes nowhere');
const lines = V.producedLines({ produced: [
  { kind: 'item', id: 'a1', type: 'commitment', label: 'Send the window shop drawings', status: 'open' },
  { kind: 'event', id: 'e1', label: 'Electrical inspection', date: '2026-10-14' }] });
ok(lines[0].text === 'Produced: commitment “Send the window shop drawings” · open', lines[0].text);
ok(lines[1].text === 'Produced: event “Electrical inspection” (2026-10-14)', lines[1].text);
ok(V.producedRoute('p1', lines[0]) === '/projects/p1/whatsapp-groups', 'an item opens Attention');
ok(V.producedRoute('p1', lines[1]) === '/projects/p1/upcoming', 'an event opens Upcoming');

console.log('the screen');
const screen = read('app/projects/[id]/voice-log.jsx');
ok(/getVoiceLog/.test(screen) && /producedLines/.test(screen) && /PLAY_LABEL/.test(screen),
   'lists, produced, play');
ok(/voice-log/.test(read('app/projects/[id]/whatsapp-groups.jsx')), 'linked from the WhatsApp tab');
ok(V.emptyText(false) === 'No voice notes yet.' && /filters/.test(V.emptyText(true)), 'empty texts');
const merged = V.appendPage([{ id: 'a', where: 'group' }], { notes: [
  { id: 'a', where: 'group' }, { id: 'a', where: 'dm' }, { id: 'b', where: 'group' }] });
ok(merged.map((n) => `${n.where}-${n.id}`).join() === 'group-a,dm-a,group-b', 'a page appends, no repeats');
ok(/next_before/.test(screen) && /LOAD_MORE/.test(screen), 'Load more on the screen');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed) process.exit(1);
