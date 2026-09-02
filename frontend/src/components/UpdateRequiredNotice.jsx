import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet } from 'react-native';
import Constants from 'expo-constants';
import {
  isUpdateRequired,
  getUpdateRequired,
  registerUpdateRequiredHandler,
} from '../utils/updateRequired';

/**
 * ONE SENTENCE INSTEAD OF TWELVE OPAQUE ERRORS.
 *
 * Rendered at the root, above every screen, and only after the server has
 * actually returned 426 — see src/utils/updateRequired.js for why the state is
 * never guessed at. Until a floor is configured on the backend (none is), no
 * 426 is ever sent and this renders null on every device.
 *
 * IT DOES NOT JUDGE THE INSTALL ITSELF. BuildMarker owns the advisory verdict
 * and stays non-blocking; this owns the refusal, which is already blocking
 * because the API is refusing. Two components reaching opposite verdicts about
 * the same phone is exactly the confusion this area exists to end, so only one
 * of them runs isBehindMinimum and it is not this one.
 *
 * WHY IT COVERS THE SCREEN. Every authenticated request is failing. A banner
 * over a dashboard of empty cards and spinners would leave the CP trying
 * things; the honest presentation of "nothing here works" is a screen that
 * says so and names the fix.
 */
export default function UpdateRequiredNotice() {
  const [required, setRequired] = useState(isUpdateRequired());

  useEffect(() => {
    // Re-render the moment the first 426 lands, rather than waiting for
    // whatever the next navigation happens to be.
    registerUpdateRequiredHandler(() => setRequired(true));
    setRequired(isUpdateRequired());
    return () => registerUpdateRequiredHandler(null);
  }, []);

  if (!required) return null;

  const detail = getUpdateRequired() || {};
  const installed = Constants.expoConfig?.version
    ?? Constants.manifest?.version
    ?? null;

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Update required</Text>
      <Text style={styles.message}>
        This version of LeveLog is no longer supported by the server, so it
        cannot load or file anything. Install the latest build from the store
        to continue.
      </Text>
      {/* THE NUMBERS, SO A SUPPORT THREAD ENDS IN ONE MESSAGE. The whole
          reason this feature exists is that on 2026-08-28 six source traces
          were built before anyone read a version off a screen. */}
      <Text selectable style={styles.detail}>
        {`installed ${detail.reported || installed || 'unknown'}`}
        {detail.minimumSupported ? ` · minimum ${detail.minimumSupported}` : ''}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  // Absolute rather than a replacement for the stack: the tree underneath
  // keeps its state, so an install updated in place comes back to where it
  // was instead of to a cold start.
  container: {
    ...StyleSheet.absoluteFillObject,
    zIndex: 9999,
    elevation: 9999,
    backgroundColor: '#050a12',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 32,
  },
  title: {
    color: '#fff',
    fontSize: 22,
    fontWeight: '700',
    marginBottom: 12,
  },
  message: {
    color: '#94a3b8',
    fontSize: 15,
    textAlign: 'center',
    lineHeight: 22,
    marginBottom: 20,
  },
  detail: {
    color: '#64748b',
    fontSize: 12,
    textAlign: 'center',
  },
});
