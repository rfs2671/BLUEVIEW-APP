/**
 * "Save to Contacts" for the Levelog number (Integrations → WhatsApp).
 *
 * WHY IT DID NOTHING ON ANDROID. The old path wrote the .vcf to the cache and
 * called Linking.openURL('file://…'). Android (7+) refuses to hand a file://
 * URI to another app, so canOpenURL said no, the call returned "ok", and the
 * card showed nothing at all.
 *
 * Now, on a phone, in order:
 *   1. expo-contacts' native "new contact" form, pre-filled with
 *      "Levelog Assistant" and the number — when the installed app has the
 *      module. It ships with the next store build; an app installed before
 *      that has no ExpoContacts native module, and importing expo-contacts
 *      there throws, so it is looked up first and only then required.
 *   2. Otherwise (or if Contacts access is refused): the contact card as a
 *      .vcf, written to the cache and handed to the share sheet
 *      (expo-sharing), which opens it in Contacts.
 * On the web the .vcf is downloaded, as before.
 *
 * Returns what happened, for the card's toast:
 *   'form' | 'shared' | 'downloaded' | 'denied_shared'
 * Throws when nothing could be shown.
 */
import { Platform } from 'react-native';

export const CONTACT_NAME = 'Levelog Assistant';

/** expo-contacts, or null when this app build does not include it. */
export function loadContacts() {
  try {
    // eslint-disable-next-line global-require
    const core = require('expo-modules-core');
    if (!core.requireOptionalNativeModule
        || !core.requireOptionalNativeModule('ExpoContacts')) {
      return null;
    }
    // eslint-disable-next-line global-require
    return require('expo-contacts');
  } catch (e) {
    return null;
  }
}

/** The contact the native form opens with. */
export function contactFor(phone) {
  const digits = String(phone || '').replace(/\D/g, '');
  return {
    contactType: 'person',
    name: CONTACT_NAME,
    firstName: 'Levelog',
    lastName: 'Assistant',
    phoneNumbers: digits ? [{ label: 'WhatsApp', number: `+${digits}` }] : [],
  };
}

async function shareVCard(getVCardText) {
  // eslint-disable-next-line global-require
  const FileSystem = require('expo-file-system/legacy');
  // eslint-disable-next-line global-require
  const Sharing = require('expo-sharing');
  if (!(await Sharing.isAvailableAsync())) {
    throw new Error('Sharing is not available on this device.');
  }
  const text = await getVCardText();
  const uri = `${FileSystem.cacheDirectory}levelog-assistant.vcf`;
  await FileSystem.writeAsStringAsync(uri, text, {
    encoding: FileSystem.EncodingType.UTF8,
  });
  await Sharing.shareAsync(uri, {
    mimeType: 'text/x-vcard',
    UTI: 'public.vcard',
    dialogTitle: `Save ${CONTACT_NAME}`,
  });
}

/**
 * @param {object} o
 * @param {string} o.phone          the Levelog number
 * @param {() => Promise<string>} o.getVCardText   the server's .vcf
 * @param {() => Promise<void>} o.downloadVCard    web download
 * @param {() => any} [o.contacts]  for tests: what loadContacts returns
 */
export async function saveLevelogContact({
  phone, getVCardText, downloadVCard, contacts = loadContacts, platform = Platform.OS,
}) {
  if (platform === 'web') {
    await downloadVCard();
    return 'downloaded';
  }
  const Contacts = contacts();
  if (Contacts) {
    const perm = await Contacts.requestPermissionsAsync();
    if (perm && perm.granted) {
      await Contacts.presentFormAsync(null, contactFor(phone), { isNew: true });
      return 'form';
    }
    await shareVCard(getVCardText);
    return 'denied_shared';
  }
  await shareVCard(getVCardText);
  return 'shared';
}
