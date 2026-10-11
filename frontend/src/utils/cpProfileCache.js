/**
 * THE SIGNER'S SAVED NAME AND SIGNATURE, ON THE DEVICE, PER ACCOUNT.
 *
 * THE DEFECT, 588 Thomas, found 2026-10-10. This lived under ONE device-wide
 * key, `blueview_cp_profile`, and logout did not clear it. Shawn (a CP) and
 * Michael (the superintendent) used the same phone: Shawn's name and
 * signature drawing were cached on 2026-09-16, and when Michael logged in on
 * 2026-09-22 his editors loaded them from the cache and `autoSave` wrote them
 * to HIS profile. Thirty of Michael's filed logs carry Shawn's signature
 * drawing -- seven of them under Michael's name.
 *
 * SO THE CACHE IS KEYED BY THE ACCOUNT. A value saved for one user id is never
 * read for another, the old shared key is deleted on sight and never read,
 * and logout removes every saved profile on the device.
 *
 * Nothing here talks to the server; useCpProfile does, and it asks this
 * module only for the account it has.
 */

import AsyncStorage from '@react-native-async-storage/async-storage';

/** The device-wide key the defect lived under. Deleted, never read. */
export const LEGACY_CP_PROFILE_KEY = 'blueview_cp_profile';
export const CP_PROFILE_KEY_PREFIX = 'blueview_cp_profile:';

export const cpProfileKey = (userId) => {
  const id = String(userId || '').trim();
  return id ? `${CP_PROFILE_KEY_PREFIX}${id}` : null;
};

/**
 * This account's saved {cp_name, cp_signature}, or null.
 *
 * NO ACCOUNT, NO PROFILE. Without a user id there is nobody the values could
 * belong to, so nothing is returned -- the pad starts empty, which is the
 * honest state, rather than starting with whoever used the phone last.
 */
export async function readCpProfile(userId) {
  try { await AsyncStorage.removeItem(LEGACY_CP_PROFILE_KEY); } catch (e) { /* best effort */ }
  const key = cpProfileKey(userId);
  if (!key) return null;
  try {
    const raw = await AsyncStorage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    // BELT AND BRACES: the owner travels inside the value too, so a value that
    // somehow sits under the wrong key is still refused.
    if (!parsed || String(parsed.user_id || '') !== String(userId)) return null;
    return { cp_name: parsed.cp_name || '', cp_signature: parsed.cp_signature || null };
  } catch (e) {
    return null;
  }
}

export async function writeCpProfile(userId, { cp_name, cp_signature }) {
  const key = cpProfileKey(userId);
  if (!key) return false;
  try {
    await AsyncStorage.setItem(key, JSON.stringify({
      user_id: String(userId), cp_name: cp_name || '', cp_signature: cp_signature || null,
    }));
    return true;
  } catch (e) {
    return false;
  }
}

/**
 * Every saved profile on the device, gone. Called on logout.
 *
 * ALL OF THEM, NOT ONLY THE LEAVING USER'S. A phone handed to the next person
 * should hold no signature at all; keying by account stops the cross-over,
 * and clearing on logout stops a signature sitting on a shared device.
 */
export async function clearAllCpProfiles() {
  try {
    const keys = await AsyncStorage.getAllKeys();
    const ours = (keys || []).filter((k) => k === LEGACY_CP_PROFILE_KEY
      || String(k).startsWith(CP_PROFILE_KEY_PREFIX));
    if (ours.length) await AsyncStorage.multiRemove(ours);
  } catch (e) {
    try { await AsyncStorage.removeItem(LEGACY_CP_PROFILE_KEY); } catch (e2) { /* best effort */ }
  }
}
