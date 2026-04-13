import NfcManager, { NfcTech, Ndef } from 'react-native-nfc-manager';

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
  try {
    // Request NDEF technology for writing
    await NfcManager.requestTechnology(NfcTech.Ndef);
    
    // Create the check-in URL
    const url = `${baseUrl}/checkin/${projectId}/${tagId}`;
    
    // Create NDEF record with the URL
    const bytes = Ndef.encodeMessage([Ndef.uriRecord(url)]);
    
    if (!bytes) {
      throw new Error('Failed to encode NDEF message');
    }
    
    // Write to the tag
    await NfcManager.ndefHandler.writeNdefMessage(bytes);
    
    await NfcManager.cancelTechnologyRequest();
    
    return {
      success: true,
      url: url,
      message: 'NFC tag programmed successfully',
    };
  } catch (ex) {
    console.warn('NFC write error:', ex);
    await NfcManager.cancelTechnologyRequest();
    return {
      success: false,
      error: ex.message || 'Failed to write to NFC tag',
    };
  }
}

/**
 * Read AND Write NFC Tag in one operation
 * This is the main function for admin tag registration
 */
export async function registerNfcTag(projectId, baseUrl = 'https://levelog.com') {
  try {
    // Step 1: Request NDEF technology
    await NfcManager.requestTechnology(NfcTech.Ndef);
    
    // Step 2: Read the tag to get its ID
    const tag = await NfcManager.getTag();
    const tagId = tag.id || '';
    
    if (!tagId) {
      throw new Error('Could not read tag ID');
    }
    
    // Step 3: Create the check-in URL
    const url = `${baseUrl}/checkin/${projectId}/${tagId}`;
    
    // Step 4: Write the URL to the tag
    const bytes = Ndef.encodeMessage([Ndef.uriRecord(url)]);
    
    if (!bytes) {
      throw new Error('Failed to encode NDEF message');
    }
    
    await NfcManager.ndefHandler.writeNdefMessage(bytes);
    
    // Step 5: Clean up
    await NfcManager.cancelTechnologyRequest();
    
    return {
      success: true,
      tagId: tagId,
      url: url,
      message: 'NFC tag registered and programmed successfully',
    };
  } catch (ex) {
    console.warn('NFC register error:', ex);
    await NfcManager.cancelTechnologyRequest();
    return {
      success: false,
      error: ex.message || 'Failed to register NFC tag',
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
