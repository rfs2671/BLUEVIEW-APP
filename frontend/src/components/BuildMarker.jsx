import React from 'react';
import { View, Text } from 'react-native';
import Constants from 'expo-constants';
import * as Updates from 'expo-updates';

// Self-report the EXACT running bundle so "is my phone on the right code?" is
// never a question again. `bundle: embedded` = running the JS baked into the APK;
// a short id = running an OTA on top. Bump BUILD_TAG on every push so the running
// app names which fix-batch it contains — glance at the marker and KNOW.
export const BUILD_TAG = 'cam-snapshot-fast-capture';

export default function BuildMarker() {
  const version = Constants.expoConfig?.version ?? Constants.manifest?.version ?? '?';
  let updateId = 'embedded';
  let channel = 'n/a';
  let runtime = '?';
  let created = 'embedded';
  try {
    updateId = Updates.updateId ? String(Updates.updateId).slice(0, 8) : 'embedded';
    channel = Updates.channel ?? 'n/a';
    runtime = Updates.runtimeVersion ?? '?';
    created = Updates.createdAt
      ? new Date(Updates.createdAt).toISOString().slice(5, 16).replace('T', ' ')
      : 'embedded';
  } catch (_e) { /* expo-updates not available in some contexts */ }
  return (
    <View style={{ paddingVertical: 6, opacity: 0.6 }}>
      <Text selectable style={{ fontSize: 10, color: '#94a3b8', textAlign: 'center' }}>
        v{version} · rt {runtime} · {channel} · {BUILD_TAG}
      </Text>
      <Text selectable style={{ fontSize: 10, color: '#94a3b8', textAlign: 'center' }}>
        bundle: {updateId} · {created}
      </Text>
    </View>
  );
}
