/**
 * The original message behind a quote: what the sheet and the cards say.
 *   node frontend/src/utils/sourceMessage.test.cjs
 */
const fs = require('fs');
const path = require('path');
const { loadEsm } = require('./esmHarness.cjs');

let pass = 0; let fail = 0;
function ok(c, label) { if (c) { pass += 1; console.log('  PASS ', label); } else { fail += 1; console.log('  FAIL ', label); } }

const S = loadEsm('src/utils/sourceMessage.js');
ok(S.quoteText('el colado es mañana', true) === '🎤 “el colado es mañana”', 'a voice quote is marked 🎤, words as said');
ok(S.quoteText('send it Friday', false) === '“send it Friday”', 'a typed quote is not');
ok(S.voiceLine({ lang: 'es', duration_sec: 6.2, confidence: 0.91 }) === '🎤 Spanish · 6s · 91% sure', 'language, length, how sure');
ok(S.voiceLine({ lang: 'yi' }) === '🎤 Yiddish', 'Yiddish');
ok(/Yiddish voice note/.test(S.reviewNote({ lang: 'yi', review: true })), 'Yiddish voice is flagged');
ok(/may be wrong/.test(S.reviewNote(null, 'low_confidence_voice')), 'a low-confidence transcript is flagged');
ok(S.reviewNote({ lang: 'es', review: false }) === null, 'a confident one is not');
ok(S.englishLine({ english: 'The pour is tomorrow' }, 'El colado es mañana') === 'In English: “The pour is tomorrow”', 'the English, when it differs');
ok(S.englishLine({ english: 'Pour tomorrow' }, 'pour tomorrow') === null, 'not when it is the same words');
ok(S.headLine({ who: 'Carlos', at: '2026-10-14T11:15:00Z' }) === 'Carlos · Oct 14, 7:15 AM', 'who and when, New York time');

const U = loadEsm('src/utils/upcoming.js');
ok(U.evidenceLine({ source: 'chat', quote: 'la grúa llega mañana', who: 'Carlos', voice: true })
   === '🎤 “la grúa llega mañana” — Carlos', 'an Upcoming event from a voice note');
const M = loadEsm('src/utils/projectMemory.js');
ok(M.chipText({ who: 'Carlos', group: 'Site', when: 'Sep 24, 8:30 AM', voice: true })
   === 'Carlos · Site · 🎤 Sep 24, 8:30 AM', 'a search result from a voice note');

const read = (p) => fs.readFileSync(path.join(__dirname, '..', '..', p), 'utf8');
const sheet = read('src/components/whatsapp/SourceSheet.jsx');
ok(/whatsappAPI\.getSource\(projectId, rowId\)/.test(sheet), 'the sheet loads the source message');
ok(/Linking\.openURL\(v\.audio_url\)/.test(sheet), 'Play opens the audio link');
ok(!/useToast/.test(sheet), 'no toast inside the Modal (it would paint behind it)');
const card = read('src/components/whatsapp/AttentionCard.jsx');
ok(/setSource\(\{ rowId: it\.message_row_id/.test(card) && /setSource\(\{ rowId: e\.message_row_id/.test(card),
  'an item and each change open their original message');
ok(/quoteText\(it\.quote, it\.voice\)/.test(card), 'and mark voice quotes');
ok(/setSourceRow\(e\.message_row_id\)/.test(read('app/projects/[id]/upcoming.jsx')), 'Upcoming opens it');
ok(/setSourceRow\(r\.message_row_id\)/.test(read('app/projects/[id]/search.jsx')), 'Search plays a voice result');
const api = fs.readFileSync(path.join(__dirname, 'api.js'), 'utf8');
ok(api.includes('/whatsapp/messages/${encodeURIComponent(rowId)}/source'), 'api path');

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
