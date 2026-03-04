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

const CP_PROFILE_CACHE_KEY = 'blueview_cp_profile';

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
    const nameChanged = name !== nameRef.current;
    const sigChanged = signature !== sigRef.current;
    if (!nameChanged && !sigChanged) return;

    // Always update local cache first (instant, works offline)
    nameRef.current = name;
    sigRef.current = signature;
    try {
      await AsyncStorage.setItem(CP_PROFILE_CACHE_KEY, JSON.stringify({
        cp_name: name,
        cp_signature: signature,
      }));
    } catch (e) {
      // Non-blocking
    }

    // Then sync to backend (may fail if offline — that's OK)
    try {
      await cpProfileAPI.updateProfile({ cp_name: name, cp_signature: signature });
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
