import { Platform } from 'react-native';
import * as ImageManipulator from 'expo-image-manipulator';
import * as FileSystem from 'expo-file-system/legacy';

/**
 * Downscale + re-encode a captured photo until it fits under the upload cap.
 *
 * LIFTED OUT OF CameraCaptureModal ON PURPOSE. It used to run inside the
 * shutter handler, awaited, before the modal dismissed — so the CP stared at a
 * frozen live preview for the whole ladder below. The capture path now hands
 * the RAW camera URI to the screen immediately and the screen runs this in the
 * BACKGROUND, swapping the URI in place when it resolves. Nothing about the
 * ladder itself changed; only who awaits it, and when.
 *
 * Keeping it in its own module (rather than exporting it from
 * CameraCaptureModal) means daily_jobsite can import it without dragging
 * react-native-vision-camera — which throws at module scope on web — into the
 * web bundle.
 */

const MAX_BYTES = 150 * 1024;

export const PHOTO_MAX_BYTES = MAX_BYTES;

export async function compressUnderCap(srcUri) {
  // Web never reaches the in-process camera (daily_jobsite routes web taps to
  // the image library), and FileSystem.getInfoAsync cannot stat a blob: URI.
  if (Platform.OS === 'web') return srcUri;

  let width = 1280;
  let quality = 0.6;
  let out = await ImageManipulator.manipulateAsync(
    srcUri, [{ resize: { width } }],
    { compress: quality, format: ImageManipulator.SaveFormat.JPEG },
  );
  let info = await FileSystem.getInfoAsync(out.uri);
  let tries = 0;
  while ((info?.size ?? 0) > MAX_BYTES && tries < 5) {
    tries += 1;
    if (quality > 0.3) quality = Math.max(0.3, quality - 0.15);
    else width = Math.round(width * 0.8);
    out = await ImageManipulator.manipulateAsync(
      srcUri, [{ resize: { width } }],
      { compress: quality, format: ImageManipulator.SaveFormat.JPEG },
    );
    info = await FileSystem.getInfoAsync(out.uri);
  }
  return out.uri;
}

export default compressUnderCap;
