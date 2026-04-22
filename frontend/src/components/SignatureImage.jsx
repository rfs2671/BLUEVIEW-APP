import React, { useEffect, useState } from 'react';
import { Image, View, Text, StyleSheet } from 'react-native';
import { signaturesAPI } from '../utils/api';

/**
 * SignatureImage — renders a worker's stored signature.
 *
 * The backend /api/signatures/{signin_id} endpoint is session-authed,
 * so we can't point a plain <Image src> at it — axios picks up the
 * session's bearer token from the client-side interceptor, the image
 * doesn't. Fetch the bytes via axios, convert to a data URL, render.
 * Result is memoized in-module so re-renders don't re-fetch.
 *
 * Four distinguishable render states, matching the backend's four
 * distinguishable error states:
 *   - loading               (empty view, no text)
 *   - ok                    (signature renders)
 *   - missing  (404)        "No signature on file"
 *   - forbidden (403)       "No access"
 *   - unavailable (5xx)     "Signature temporarily unavailable — refresh to retry"
 *
 * Legacy fallback: if signInId is null but fallbackBase64 is provided
 * (pre-gate-migration workers whose signature lives inline on
 * workers.signature), render that directly. Once a worker migrates,
 * signInId takes over.
 */

const cache = new Map(); // signInId -> dataUrl (session-scoped)

export default function SignatureImage({
  signInId,
  fallbackBase64,
  style,
  placeholderText,
}) {
  const [dataUrl, setDataUrl] = useState(null);
  const [status, setStatus] = useState('loading');

  useEffect(() => {
    let cancelled = false;

    // Legacy path: no signin_id, but we have an inline base64 signature.
    if (!signInId) {
      if (fallbackBase64) {
        const url = String(fallbackBase64).startsWith('data:')
          ? fallbackBase64
          : `data:image/png;base64,${fallbackBase64}`;
        setDataUrl(url);
        setStatus('ok');
      } else {
        setStatus('missing');
      }
      return () => {
        cancelled = true;
      };
    }

    // Session cache hit
    if (cache.has(signInId)) {
      setDataUrl(cache.get(signInId));
      setStatus('ok');
      return () => {
        cancelled = true;
      };
    }

    (async () => {
      try {
        const blob = await signaturesAPI.fetchImage(signInId);
        if (cancelled) return;

        const toDataUrl = (val) => new Promise((resolve, reject) => {
          if (!val) return reject(new Error('empty'));
          if (typeof val === 'string') {
            // Already a base64 string (RN environments occasionally
            // return strings instead of Blobs for responseType: 'blob')
            return resolve(`data:image/png;base64,${val}`);
          }
          if (typeof Blob !== 'undefined' && val instanceof Blob) {
            const reader = new FileReader();
            reader.onloadend = () => resolve(reader.result);
            reader.onerror = () => reject(new Error('reader_fail'));
            reader.readAsDataURL(val);
            return;
          }
          // ArrayBuffer fallback
          if (val?.byteLength !== undefined) {
            try {
              const bytes = new Uint8Array(val);
              let binary = '';
              for (let i = 0; i < bytes.byteLength; i++) {
                binary += String.fromCharCode(bytes[i]);
              }
              return resolve(`data:image/png;base64,${btoa(binary)}`);
            } catch (e) {
              return reject(e);
            }
          }
          reject(new Error('unsupported_blob_type'));
        });

        const url = await toDataUrl(blob);
        if (cancelled) return;
        cache.set(signInId, url);
        setDataUrl(url);
        setStatus('ok');
      } catch (err) {
        if (cancelled) return;
        const code = err?.response?.status;
        if (code === 404) setStatus('missing');
        else if (code === 403) setStatus('forbidden');
        else setStatus('unavailable');
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [signInId, fallbackBase64]);

  if (status === 'loading') {
    return <View style={[s.frame, style]} />;
  }
  if (status === 'ok' && dataUrl) {
    return (
      <Image
        source={{ uri: dataUrl }}
        style={[s.frame, style]}
        resizeMode="contain"
      />
    );
  }

  // Distinguishable empty / error states so a CP can tell the
  // difference between "no sign-in today" and "storage down".
  let msg;
  switch (status) {
    case 'forbidden':
      msg = 'No access';
      break;
    case 'unavailable':
      msg = 'Signature temporarily unavailable — refresh to retry';
      break;
    case 'missing':
    default:
      msg = placeholderText || 'No signature on file';
  }
  return (
    <View style={[s.frame, s.placeholder, style]}>
      <Text style={s.placeholderText} numberOfLines={2}>
        {msg}
      </Text>
    </View>
  );
}

const s = StyleSheet.create({
  frame: {
    width: '100%',
    minHeight: 60,
  },
  placeholder: {
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'rgba(0,0,0,0.03)',
    borderRadius: 6,
    paddingHorizontal: 10,
    paddingVertical: 12,
  },
  placeholderText: {
    fontSize: 11,
    color: '#94a3b8',
    textAlign: 'center',
  },
});
