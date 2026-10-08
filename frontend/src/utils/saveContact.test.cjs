/**
 * INTEGRATIONS → WHATSAPP → "SAVE TO CONTACTS".
 *
 * It did nothing on Android: the old path opened a file:// URI with Linking,
 * which Android refuses, and returned "ok" anyway. Now: expo-contacts' native
 * form when the installed app has it; otherwise (and when Contacts access is
 * refused) the .vcf through the share sheet; a download on the web.
 *
 * Run:  node src/utils/saveContact.test.cjs
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

function world({ nativeContacts = true, granted = true, sharing = true } = {}) {
  const calls = [];
  const contacts = {
    requestPermissionsAsync: async () => { calls.push('perm'); return { granted }; },
    presentFormAsync: async (id, contact, opts) => {
      calls.push(['form', id, contact, opts]);
    },
  };
  const stubs = {
    'react-native': { Platform: { OS: 'android' } },
    'expo-modules-core': {
      requireOptionalNativeModule: (name) => (nativeContacts && name === 'ExpoContacts' ? {} : null),
    },
    'expo-contacts': contacts,
    'expo-file-system/legacy': {
      cacheDirectory: 'file:///cache/',
      EncodingType: { UTF8: 'utf8' },
      writeAsStringAsync: async (uri, text) => { calls.push(['write', uri, text]); },
    },
    'expo-sharing': {
      isAvailableAsync: async () => sharing,
      shareAsync: async (uri, opts) => { calls.push(['share', uri, opts]); },
    },
  };
  const S = loadEsm('src/utils/saveContact.js', { stubs });
  const args = {
    phone: '+1 (555) 999-0000',
    getVCardText: async () => 'BEGIN:VCARD\nFN:Levelog Assistant\nEND:VCARD',
    downloadVCard: async () => { calls.push('download'); },
  };
  return { S, calls, args };
}

(async () => {
  console.log('the app has expo-contacts (next store build)');
  {
    const { S, calls, args } = world();
    const how = await S.saveLevelogContact(args);
    const form = calls.find((c) => Array.isArray(c) && c[0] === 'form');
    ok(how === 'form', 'opens the native new-contact form');
    ok(calls[0] === 'perm', 'asks for Contacts access first');
    ok(form && form[2].name === 'Levelog Assistant', 'named "Levelog Assistant"');
    ok(form && form[2].phoneNumbers[0].number === '+15559990000', 'with the Levelog number');
    ok(form && form[3].isNew === true, 'as a new contact');
    ok(!calls.some((c) => Array.isArray(c) && c[0] === 'share'), 'no share sheet');
  }

  console.log('\nContacts access refused');
  {
    const { S, calls, args } = world({ granted: false });
    const how = await S.saveLevelogContact(args);
    ok(how === 'denied_shared', 'reported (the card shows a toast)');
    ok(calls.some((c) => Array.isArray(c) && c[0] === 'share'), 'and the contact card is shared instead');
    ok(!calls.some((c) => Array.isArray(c) && c[0] === 'form'), 'no form');
  }

  console.log('\nthe app installed today (no ExpoContacts native module)');
  {
    const { S, calls, args } = world({ nativeContacts: false });
    ok(S.loadContacts() === null, 'expo-contacts is not even required (it would throw)');
    const how = await S.saveLevelogContact(args);
    const write = calls.find((c) => Array.isArray(c) && c[0] === 'write');
    const share = calls.find((c) => Array.isArray(c) && c[0] === 'share');
    ok(how === 'shared', 'shares the .vcf');
    ok(write && write[1] === 'file:///cache/levelog-assistant.vcf' && /Levelog Assistant/.test(write[2]),
       "writes the server's contact card to the cache");
    ok(share && share[2].mimeType === 'text/x-vcard' && share[2].UTI === 'public.vcard',
       'as a vCard, so Contacts offers to open it');
    ok(!calls.includes('perm'), 'asks for no permission');
  }

  console.log('\nno share sheet at all');
  {
    const { S, args } = world({ nativeContacts: false, sharing: false });
    let threw = false;
    try { await S.saveLevelogContact(args); } catch (e) { threw = true; }
    ok(threw, 'throws, so the card shows "Could not save contact" (never a silent no-op)');
  }

  console.log('\nweb');
  {
    const { S, calls, args } = world();
    const how = await S.saveLevelogContact({ ...args, platform: 'web' });
    ok(how === 'downloaded' && calls.includes('download') && !calls.includes('perm'),
       'downloads the .vcf');
  }

  console.log('\nwiring');
  {
    const read = (p) => fs.readFileSync(path.join(__dirname, '..', '..', p), 'utf8');
    const card = read('src/components/WhatsAppCard.jsx');
    const api = read('src/utils/api.js');
    ok(/saveLevelogContact\(\{/.test(card), 'the card uses it');
    ok(/how === 'denied_shared'[\s\S]{0,40}toast\.info/.test(card), 'refused access: a toast');
    ok(!/Linking\.openURL\(fileUri\)/.test(api), 'the file:// Linking path is gone');
    const appJson = JSON.parse(read('app.json'));
    const plugin = appJson.expo.plugins.find((p) => Array.isArray(p) && p[0] === 'expo-contacts');
    ok(plugin && /Levelog Assistant/.test(plugin[1].contactsPermission),
       'expo-contacts plugin with the iOS permission text');
    ok(appJson.expo.android.permissions.includes('WRITE_CONTACTS'), 'Android Contacts permission');
  }

  console.log(`\n${passed} passed, ${failed} failed`);
  if (failed) process.exit(1);
})();
