import NfcManager, { NfcTech, Ndef } from 'react-native-nfc-manager';

/**
 * THE TWO TECHS A WRITE CAN LAND ON, and why both are requested.
 *
 * A BLANK tag is `NdefFormatable`, not `Ndef`. Android only exposes the `Ndef`
 * tech once a tag has actually been NDEF-formatted, so on a virgin tag
 * `Ndef.get(tag)` returns null, the library has no tech handle, and
 * `writeNdefMessage` reports "unsupported tag api" — an error that names the
 * write while the real problem is that there was nothing to write THROUGH.
 *
 * Confirmed on device rather than reasoned about. logcat, Pixel 10 Pro XL:
 *
 *   dispatchTag: TAG: Tech [android.nfc.tech.NfcV, android.nfc.tech.NdefFormatable]
 *   parseIntent ... action android.nfc.action.TAG_DISCOVERED
 *   ReactNativeJS: 'NFC register error:', [Error: unsupported tag api]
 *
 * The OS dispatched the tag and the app parsed the intent — so this was never
 * about Android 17, the New Architecture, or the SDK 54 migration. Three
 * hypotheses died before the readout; the readout answered it in one line.
 * The tag advertises NdefFormatable and this helper never asked for it.
 *
 * `requestTechnology` takes an ARRAY, tries each in order, and RESOLVES TO THE
 * NAME of the one it acquired — TagTechnologyRequest.connect() takes the first
 * non-null handle and passes that name back to JS. So the branch below is on
 * observed fact, not a guess about the tag.
 *
 * NdefFormatable is asked for FIRST. The two are mutually exclusive in
 * practice: a tag stops advertising NdefFormatable once it is formatted, so a
 * blank tag lands on format and a written tag falls through to write.
 *
 * NfcV (ISO 15693) does not change any of this. It is the TRANSPORT; Ndef and
 * NdefFormatable are the data layer above it, and Android exposes them
 * independently of whether the radio is ISO 14443A or ISO 15693. The tag's own
 * tech list above is what proves NdefFormatable is obtainable here.
 */
const WRITE_TECHS = [NfcTech.NdefFormatable, NfcTech.Ndef];

/**
 * Write `bytes` through whichever tech was acquired.
 *
 * NOT a shared abstraction over read and write — reading is a legitimately
 * different flow and one wrapper over two intents is how the wrong path gets
 * taken silently. This is only the write half, used by the two writers below.
 */
async function writeThroughTech(tech, bytes) {
  if (tech === 'NdefFormatable') {
    // format() writes the message AS PART OF formatting, so a virgin tag is
    // formatted and populated in one operation.
    await NfcManager.ndefFormatableHandlerAndroid.formatNdef(bytes);
  } else {
    await NfcManager.ndefHandler.writeNdefMessage(bytes);
  }
}

/**
 * Initialize NFC Manager
 * Call this once when app starts
 */
export async function initNfc() {
  try {
    await NfcManager.start();
    return true;
  } catch (ex) {
    console.warn('NFC initialization failed:', ex);
    return false;
  }
}

/**
 * Read NFC Tag ID
 * Returns the tag's unique identifier
 */
export async function readNfcTag() {
  try {
    await NfcManager.requestTechnology(NfcTech.Ndef);
    
    const tag = await NfcManager.getTag();
    
    // Get tag ID (usually in format like "04:A1:B2:C3:D4:E5:F6")
    const tagId = tag.id || '';
    
    await NfcManager.cancelTechnologyRequest();
    
    return {
      success: true,
      tagId: tagId,
      rawTag: tag,
    };
  } catch (ex) {
    console.warn('NFC read error:', ex);
    await NfcManager.cancelTechnologyRequest();
    return {
      success: false,
      error: ex.message || 'Failed to read NFC tag',
    };
  }
}

/**
 * Write URL to NFC Tag
 * This permanently programs the tag with a check-in URL
 * 
 * @param {string} projectId - The project ID
 * @param {string} tagId - The tag ID
 * @param {string} baseUrl - Base URL (e.g., "https://levelog.com")
 */
export async function writeNfcTag(projectId, tagId, baseUrl = 'https://levelog.com') {
  let tech = null;
  try {
    // Blank OR already formatted — see WRITE_TECHS above.
    tech = await NfcManager.requestTechnology(WRITE_TECHS);

    const url = `${baseUrl}/checkin/${projectId}/${tagId}`;
    const bytes = Ndef.encodeMessage([Ndef.uriRecord(url)]);

    if (!bytes) {
      throw new Error('Failed to encode NDEF message');
    }

    await writeThroughTech(tech, bytes);
    await NfcManager.cancelTechnologyRequest();

    return {
      success: true,
      url,
      tech,
      message: 'NFC tag programmed successfully',
    };
  } catch (ex) {
    console.warn('NFC write error:', tech, ex);
    await NfcManager.cancelTechnologyRequest();
    return {
      success: false,
      tech,
      // THE TECH GOES IN THE MESSAGE. Three rounds went to a bare
      // "unsupported tag api", which named the write and not the handle it
      // was missing.
      error: `${ex.message || 'Failed to write to NFC tag'}`
        + `${tech ? ` (tech: ${tech})` : ' (no tech acquired)'}`,
    };
  }
}

/**
 * Read AND Write NFC Tag in one operation
 * This is the main function for admin tag registration
 */
export async function registerNfcTag(projectId, baseUrl = 'https://levelog.com') {
  let tech = null;
  try {
    // Step 1: acquire whichever write tech this tag actually offers.
    tech = await NfcManager.requestTechnology(WRITE_TECHS);

    // Step 2: the UID, read BEFORE branching — both paths need it, and it is
    // what gets registered server-side whether the tag was formatted or not.
    const tag = await NfcManager.getTag();
    const tagId = tag?.id || '';

    if (!tagId) {
      throw new Error('Could not read tag ID');
    }

    // Steps 3 and 4: build the check-in URL and put it on the tag.
    const url = `${baseUrl}/checkin/${projectId}/${tagId}`;
    const bytes = Ndef.encodeMessage([Ndef.uriRecord(url)]);

    if (!bytes) {
      throw new Error('Failed to encode NDEF message');
    }

    await writeThroughTech(tech, bytes);
    await NfcManager.cancelTechnologyRequest();

    return {
      success: true,
      tagId,
      url,
      tech,
      message: 'NFC tag registered and programmed successfully',
    };
  } catch (ex) {
    console.warn('NFC register error:', tech, ex);
    await NfcManager.cancelTechnologyRequest();
    return {
      success: false,
      tech,
      // See writeNfcTag: the acquired tech goes in the message, because its
      // absence is what made this take three rounds to find.
      error: `${ex.message || 'Failed to register NFC tag'}`
        + `${tech ? ` (tech: ${tech})` : ' (no tech acquired)'}`,
    };
  }
}

/**
 * Cancel any ongoing NFC operation
 */
export async function cancelNfc() {
  try {
    await NfcManager.cancelTechnologyRequest();
  } catch (ex) {
    console.warn('NFC cancel error:', ex);
  }
}

/**
 * Check if device supports NFC
 */
export async function isNfcSupported() {
  try {
    return await NfcManager.isSupported();
  } catch (ex) {
    return false;
  }
}

/**
 * Check if NFC is enabled on device
 */
export async function isNfcEnabled() {
  try {
    return await NfcManager.isEnabled();
  } catch (ex) {
    return false;
  }
}
