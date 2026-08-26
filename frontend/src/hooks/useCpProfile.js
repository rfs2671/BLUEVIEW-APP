/**
 * useCpProfile.js
 * Place at: frontend/src/hooks/useCpProfile.js
 *
 * FIX: Signature wasn't surviving app restarts because the original only
 * cached to backend (which fails offline). Now uses two-tier cache:
 *   1. AsyncStorage (instant, survives offline)
 *   2. Backend API (background sync)
 *
 * On mount: loads from AsyncStorage first → signature appears immediately.
 * Then fetches from backend in background to stay in sync.
 * autoSave() writes to BOTH.
 */

import { useState, useEffect, useRef } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { cpProfileAPI } from '../utils/api';
import { toCredential } from '../utils/signatureAffirmed';

const CP_PROFILE_CACHE_KEY = 'blueview_cp_profile';

/**
 * The profile signature is a REUSABLE CREDENTIAL, never a per-document
 * attestation. Strip every per-document stamp before caching it, so an
 * affirmed signature saved from one logbook can never flow back into the
 * profile and make the NEXT document render as already VERIFIED without its
 * own affirmation. See SignaturePad's affirmation flow.
 *
 * THE FIELD LIST IS NOT WRITTEN HERE ANY MORE, and that is the fix. This was
 * `const { affirmed, affirmedAt, ...credential } = sig` — correct when the
 * attestation had two fields. `affirmedLang` was added to the attestation by a
 * later commit and nobody widened this, so the credential kept carrying it:
 * two logs filed on 2026-08-25 asserted the signer was shown English on
 * documents he never affirmed at all.
 *
 * The list now lives beside the predicate that defines what "affirmed" means
 * (PER_DOCUMENT_SIGNATURE_FIELDS in utils/signatureAffirmed), so widening the
 * attestation and widening the strip are the same edit instead of two.
 */
const stripAffirmation = toCredential;

export function useCpProfile() {
  const [cpName, setCpName] = useState('');
  const [cpSignature, setCpSignature] = useState(null);
  const [profileLoaded, setProfileLoaded] = useState(false);

  const nameRef = useRef('');
  const sigRef = useRef(null);

  useEffect(() => {
    let cancelled = false;

    const loadProfile = async () => {
      // ── Step 1: Load from local cache (instant, works offline) ──
      try {
        const cached = await AsyncStorage.getItem(CP_PROFILE_CACHE_KEY);
        if (cached && !cancelled) {
          const parsed = JSON.parse(cached);
          if (parsed?.cp_name) {
            setCpName(parsed.cp_name);
            nameRef.current = parsed.cp_name;
          }
          if (parsed?.cp_signature) {
            setCpSignature(parsed.cp_signature);
            sigRef.current = parsed.cp_signature;
          }
        }
      } catch (e) {
        // Cache miss is fine
      }

      // ── Step 2: Fetch from backend (background, updates cache) ──
      try {
        const profile = await cpProfileAPI.getProfile();
        if (cancelled) return;

        if (profile?.cp_name) {
          setCpName(profile.cp_name);
          nameRef.current = profile.cp_name;
        }
        if (profile?.cp_signature) {
          setCpSignature(profile.cp_signature);
          sigRef.current = profile.cp_signature;
        }

        // Update local cache with fresh backend data
        try {
          await AsyncStorage.setItem(CP_PROFILE_CACHE_KEY, JSON.stringify({
            cp_name: profile?.cp_name || '',
            cp_signature: profile?.cp_signature || null,
          }));
        } catch (cacheError) {
          // Non-blocking
        }

        setProfileLoaded(true);
      } catch (apiError) {
        // 404 for brand-new CP, or offline → we already have cache
        if (!cancelled) {
          setProfileLoaded(true);
        }
      }
    };

    loadProfile();
    return () => { cancelled = true; };
  }, []);

  /**
   * Call after any successful log save/submit.
   * Persists to BOTH local cache AND backend.
   */
  const autoSave = async (name, signature) => {
    if (!name?.trim() || !signature) return;
    // Persist the credential WITHOUT any per-document affirmation stamp.
    const credential = stripAffirmation(signature);
    const nameChanged = name !== nameRef.current;
    const sigChanged = credential !== sigRef.current;
    if (!nameChanged && !sigChanged) return;

    // Always update local cache first (instant, works offline)
    nameRef.current = name;
    sigRef.current = credential;
    try {
      await AsyncStorage.setItem(CP_PROFILE_CACHE_KEY, JSON.stringify({
        cp_name: name,
        cp_signature: credential,
      }));
    } catch (e) {
      // Non-blocking
    }

    // Then sync to backend (may fail if offline — that's OK)
    try {
      await cpProfileAPI.updateProfile({ cp_name: name, cp_signature: credential });
    } catch (e) {
      console.warn('CP profile auto-save to backend failed (non-blocking):', e?.message);
    }
  };

  return {
    cpName,
    setCpName,
    cpSignature,
    setCpSignature,
    profileLoaded,
    autoSave,
  };
}
