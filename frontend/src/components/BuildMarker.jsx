import React from 'react';
import { View, Text } from 'react-native';
import Constants from 'expo-constants';
import * as Updates from 'expo-updates';
import { bundleAgeLabel } from '../utils/bundleAge';

// Self-report the EXACT running bundle so "is my phone on the right code?" is
// never a question again. `bundle: embedded` = running the JS baked into the APK;
// a short id = running an OTA on top. Bump BUILD_TAG on every push so the running
// app names which fix-batch it contains — glance at the marker and KNOW.
export const BUILD_TAG = 'cam-stage-timing';

export default function BuildMarker() {
  const version = Constants.expoConfig?.version ?? Constants.manifest?.version ?? '?';
  let updateId = 'embedded';
  let channel = 'n/a';
  let runtime = '?';
  let created = 'embedded';
  // AN ID IS NOT A VERDICT. `bundle: a3f91c02` tells a reader nothing unless
  // they already know which ids are current; "built 34 days ago" tells anyone.
  // This line exists because six source traces were built for a stale-bundle
  // fault while this component was on screen the whole time. See
  // src/utils/bundleAge.js.
  let age = null;
  try {
    updateId = Updates.updateId ? String(Updates.updateId).slice(0, 8) : 'embedded';
    channel = Updates.channel ?? 'n/a';
    runtime = Updates.runtimeVersion ?? '?';
    created = Updates.createdAt
      ? new Date(Updates.createdAt).toISOString().slice(5, 16).replace('T', ' ')
      : 'embedded';
    age = bundleAgeLabel(Updates.createdAt);
  } catch (_e) { /* expo-updates not available in some contexts */ }
  return (
    <View style={{ paddingVertical: 4, opacity: 0.35 }}>
      <Text selectable style={{ fontSize: 9, color: '#94a3b8', textAlign: 'center' }}>
        v{version} · rt {runtime} · {channel} · {BUILD_TAG}
      </Text>
      <Text selectable style={{ fontSize: 9, color: '#94a3b8', textAlign: 'center' }}>
        bundle: {updateId} · {created}
      </Text>
      {/* Null for an embedded bundle, and NOT defaulted: no createdAt means the
          JS shipped with the binary, which is the stranded case itself. */}
      {!!age && (
        <Text selectable style={{ fontSize: 9, color: '#94a3b8', textAlign: 'center' }}>
          {age}
        </Text>
      )}
    </View>
  );
}
