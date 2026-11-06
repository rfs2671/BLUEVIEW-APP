import { File } from 'expo-file-system';
import { StorageAccessFramework as SAF } from 'expo-file-system/legacy';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { mimeTypeFor, shareFileName } from './fileDownloadPlan';

/**
 * ANDROID: A DOWNLOADED FILE GOES STRAIGHT INTO DOWNLOADS, NO SHARE SHEET.
 *
 * An app cannot write into the public Downloads folder by path (scoped
 * storage), and the MediaStore route needs native code the 1.3.0 binary does
 * not carry. What the binary does carry is the Storage Access Framework: the
 * person grants a folder ONCE, the grant is persistable, and every later save
 * lands there without a prompt.
 *
 * ANDROID 11+ WILL NOT GRANT THE DOWNLOADS ROOT ITSELF ("Can't use this
 * folder"). The picker opens IN Downloads and the person picks or creates a
 * folder there (the prompt suggests "LeveLog"); the file manager and the
 * Downloads view show it under Downloads.
 *
 * The folder is remembered under DIR_KEY. A remembered folder that has been
 * deleted, or whose grant was revoked, is forgotten and asked for again in the
 * same tap. A failure in a folder granted just now is thrown: the caller
 * falls back to the share sheet so the file is never stranded.
 *
 * OTA-SAFE: expo-file-system 19 (both APIs) and AsyncStorage are in the 1.3.0
 * binary (SDK 54 since #194).
 */

export const DIR_KEY = 'bv_android_save_dir';

/** "Download/LeveLog" from a SAF tree URI; '' when it cannot be read. */
export function folderLabel(dirUri) {
  let s = String(dirUri || '');
  try { s = decodeURIComponent(s); } catch (_e) { /* keep raw */ }
  const m = /\/tree\/[^:/]*:([^]*?)(?:\/document\/|$)/.exec(s);
  return m && m[1] ? m[1].replace(/\/+$/, '') : '';
}

async function rememberedFolder() {
  try { return await AsyncStorage.getItem(DIR_KEY); } catch (_e) { return null; }
}

async function forgetFolder() {
  try { await AsyncStorage.removeItem(DIR_KEY); } catch (_e) { /* ignore */ }
}

async function pickFolder(confirmFirstPick) {
  if (typeof confirmFirstPick === 'function' && !(await confirmFirstPick())) return null;
  const res = await SAF.requestDirectoryPermissionsAsync(SAF.getUriForDirectoryInRoot('Download'));
  if (!res || !res.granted || !res.directoryUri) return null;
  try { await AsyncStorage.setItem(DIR_KEY, res.directoryUri); } catch (_e) { /* asked again next time */ }
  return res.directoryUri;
}

// Bytes, not base64: a plan set runs to 100+ MB and a base64 string of it is
// a third larger again, held in JS. A file created but not filled is removed,
// so a failed save never leaves an empty "plan.pdf" in Downloads.
async function writeInto(dirUri, srcUri, name, mimeType) {
  const dest = await SAF.createFileAsync(dirUri, name, mimeType);
  try {
    const bytes = await new File(srcUri).bytes();
    new File(dest).write(bytes);
  } catch (e) {
    try { await SAF.deleteAsync(dest, { idempotent: true }); } catch (_e) { /* ignore */ }
    throw e;
  }
  return dest;
}

/**
 * Save the downloaded `srcUri` (a file:// in the app's cache) into the
 * person's Downloads folder.
 *
 * Resolves { saved: true, name, folder } or { saved: false, name } when the
 * person declined to choose a folder. Throws when a freshly granted folder
 * could not be written.
 */
export async function saveToAndroidDownloads(srcUri, file, { confirmFirstPick } = {}) {
  const name = shareFileName(file);
  const mimeType = mimeTypeFor(name);

  const known = await rememberedFolder();
  if (known) {
    try {
      await writeInto(known, srcUri, name, mimeType);
      return { saved: true, name, folder: folderLabel(known) };
    } catch (_e) {
      await forgetFolder();
    }
  }

  const picked = await pickFolder(confirmFirstPick);
  if (!picked) return { saved: false, name };
  await writeInto(picked, srcUri, name, mimeType);
  return { saved: true, name, folder: folderLabel(picked) };
}
