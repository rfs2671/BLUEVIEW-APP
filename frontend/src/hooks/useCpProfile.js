/**
 * useCpProfile.js
 * Place at: frontend/src/hooks/useCpProfile.js
 *
 * Shared hook used by all CP log forms.
 *
 * Behaviour:
 *  - On mount: loads cp_name + cp_signature from the backend profile.
 *  - autoSave(name, signature): silently saves to backend the first time
 *    the CP signs. Every subsequent call only saves if something changed.
 *    Called from each log form's handleSave() after a successful submit.
 *
 * No setup screen required. The profile is built automatically from the
 * first real signature the CP draws on any log form.
 */

import { useState, useEffect, useRef } from 'react';
import { cpProfileAPI } from '../utils/api';

export function useCpProfile() {
  const [cpName, setCpName] = useState('');
  const [cpSignature, setCpSignature] = useState(null);
  const [profileLoaded, setProfileLoaded] = useState(false);

  // Keep refs so autoSave closure always sees current values
  const nameRef = useRef('');
  const sigRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    cpProfileAPI.getProfile()
      .then((profile) => {
        if (cancelled) return;
        if (profile?.cp_name) {
          setCpName(profile.cp_name);
          nameRef.current = profile.cp_name;
        }
        if (profile?.cp_signature) {
          setCpSignature(profile.cp_signature);
          sigRef.current = profile.cp_signature;
        }
        setProfileLoaded(true);
      })
      .catch(() => {
        // Profile endpoint may 404 for brand-new CP — that's fine
        setProfileLoaded(true);
      });
    return () => { cancelled = true; };
  }, []);

  /**
   * Call this after any successful log save/submit.
   * Silently persists name + signature so future logs auto-fill.
   * Only fires a network request if something actually changed.
   */
  const autoSave = async (name, signature) => {
    if (!name?.trim() || !signature) return;
    const nameChanged = name !== nameRef.current;
    const sigChanged = signature !== sigRef.current;
    if (!nameChanged && !sigChanged) return; // nothing new to save

    try {
      await cpProfileAPI.updateProfile({ cp_name: name, cp_signature: signature });
      nameRef.current = name;
      sigRef.current = signature;
    } catch (e) {
      // Silent — don't show an error to the CP for a background save
      console.warn('CP profile auto-save failed (non-blocking):', e?.message);
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
