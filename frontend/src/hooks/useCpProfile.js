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
 *
 * PER ACCOUNT, since 2026-10-10. The cache was one device-wide key that
 * survived logout, and autoSave wrote it to whoever signed in next: Shawn's
 * signature reached thirty of Michael's filed logs. The cache is now keyed by
 * user id (utils/cpProfileCache), and a save is refused unless the account
 * signed in now is the one the values were loaded for.
 */

import { useState, useEffect, useRef } from 'react';
import { cpProfileAPI, getStoredUser } from '../utils/api';
import { readCpProfile, writeCpProfile } from '../utils/cpProfileCache';
import { toCredential } from '../utils/signatureAffirmed';

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
  // WHOSE VALUES THESE ARE. Set from the signed-in account when the profile
  // loads, and asked again before every save: a value loaded for one account
  // is never written to another. See utils/cpProfileCache for the defect.
  const ownerRef = useRef(null);

  useEffect(() => {
    let cancelled = false;

    const loadProfile = async () => {
      const owner = (await getStoredUser())?.id || null;
      if (cancelled) return;
      ownerRef.current = owner;

      // ── Step 1: THIS ACCOUNT'S saved profile (instant, works offline) ──
      const cached = await readCpProfile(owner);
      if (cached && !cancelled) {
        if (cached.cp_name) {
          setCpName(cached.cp_name);
          nameRef.current = cached.cp_name;
        }
        if (cached.cp_signature) {
          setCpSignature(cached.cp_signature);
          sigRef.current = cached.cp_signature;
        }
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

        await writeCpProfile(owner, {
          cp_name: profile?.cp_name || '',
          cp_signature: profile?.cp_signature || null,
        });

        setProfileLoaded(true);
      } catch (apiError) {
        // 404 for brand-new CP, or offline → we already have this account's cache
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
   * Persists to BOTH local cache AND backend -- for the account it was loaded
   * for, and only while that account is still the one signed in.
   */
  const autoSave = async (name, signature) => {
    if (!name?.trim() || !signature) return;
    // NOT THIS ACCOUNT'S, NOT SAVED. An unknown owner, or an account that
    // changed since the profile loaded, means these values cannot be shown
    // to belong to whoever is signed in now.
    const current = (await getStoredUser())?.id || null;
    if (!ownerRef.current || current !== ownerRef.current) return;
    // Persist the credential WITHOUT any per-document affirmation stamp.
    const credential = stripAffirmation(signature);
    const nameChanged = name !== nameRef.current;
    const sigChanged = credential !== sigRef.current;
    if (!nameChanged && !sigChanged) return;

    // Always update this account's cache first (instant, works offline)
    nameRef.current = name;
    sigRef.current = credential;
    await writeCpProfile(current, { cp_name: name, cp_signature: credential });

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
