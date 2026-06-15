import React, { useRef, useState, useEffect } from 'react';
import {
  Modal, View, Text, Pressable, StyleSheet, ActivityIndicator, Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { CameraView, useCameraPermissions } from 'expo-camera';
import { X, RefreshCw } from 'lucide-react-native';

/**
 * In-process camera capture.
 *
 * Replaces expo-image-picker's launchCameraAsync for the native photo
 * path. launchCameraAsync hands off to the OS camera *Activity*, which
 * backgrounds our app; on memory pressure (or "Don't keep activities")
 * Android destroys the process, and the return forces a full React
 * Native cold boot — the 20-30s "slow camera" the field reported.
 *
 * A mounted <CameraView> captures IN-PROCESS: the app never leaves the
 * foreground, is never killed, never reloads. Capture is instant on
 * every device, including low-RAM field phones.
 *
 * Contract: onCapture(uri) receives a file:// URI — identical shape to
 * what launchCameraAsync's asset.uri produced — so the daily_jobsite
 * save flow is unchanged (URI in state, base64 deferred to handleSave).
 */
export default function CameraCaptureModal({ visible, onClose, onCapture }) {
  const cameraRef = useRef(null);
  const [permission, requestPermission] = useCameraPermissions();
  const [facing, setFacing] = useState('back');
  const [capturing, setCapturing] = useState(false);

  // Ask for permission the first time the modal is opened without it.
  useEffect(() => {
    if (visible && permission && !permission.granted && permission.canAskAgain) {
      requestPermission();
    }
  }, [visible, permission]);

  const handleShutter = async () => {
    if (!cameraRef.current || capturing) return;
    setCapturing(true);
    try {
      const photo = await cameraRef.current.takePictureAsync({ quality: 0.4, exif: false });
      if (photo?.uri) onCapture(photo.uri);
      onClose();
    } catch (e) {
      console.warn('takePictureAsync failed:', e?.message);
    } finally {
      setCapturing(false);
    }
  };

  const toggleFacing = () => setFacing((f) => (f === 'back' ? 'front' : 'back'));

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose}>
      <View style={styles.container}>
        {!permission ? (
          // Permission state still loading.
          <View style={styles.center}>
            <ActivityIndicator size="large" color="#fff" />
          </View>
        ) : !permission.granted ? (
          <SafeAreaView style={styles.center} edges={['top', 'bottom']}>
            <Text style={styles.msg}>Camera access is required to take photos.</Text>
            <Pressable style={styles.primaryBtn} onPress={requestPermission}>
              <Text style={styles.primaryBtnText}>Grant Access</Text>
            </Pressable>
            <Pressable style={styles.secondaryBtn} onPress={onClose}>
              <Text style={styles.secondaryBtnText}>Cancel</Text>
            </Pressable>
          </SafeAreaView>
        ) : (
          <CameraView ref={cameraRef} style={styles.camera} facing={facing}>
            <SafeAreaView style={styles.overlay} edges={['top', 'bottom']}>
              <View style={styles.topBar}>
                <Pressable style={styles.iconBtn} onPress={onClose} hitSlop={12}>
                  <X size={26} strokeWidth={2} color="#fff" />
                </Pressable>
              </View>

              <View style={styles.bottomBar}>
                <Pressable
                  style={styles.iconBtn}
                  onPress={toggleFacing}
                  hitSlop={12}
                  disabled={capturing}
                >
                  <RefreshCw size={24} strokeWidth={2} color="#fff" />
                </Pressable>

                <Pressable
                  style={styles.shutter}
                  onPress={handleShutter}
                  disabled={capturing}
                >
                  {capturing ? (
                    <ActivityIndicator color="#000" />
                  ) : (
                    <View style={styles.shutterInner} />
                  )}
                </Pressable>

                {/* Spacer to keep the shutter centered opposite the flip button. */}
                <View style={styles.iconBtn} />
              </View>
            </SafeAreaView>
          </CameraView>
        )}
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#000' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 32, backgroundColor: '#000' },
  msg: { color: '#fff', fontSize: 15, textAlign: 'center', marginBottom: 24, lineHeight: 22 },
  primaryBtn: {
    backgroundColor: '#3b82f6', paddingHorizontal: 28, paddingVertical: 12,
    borderRadius: 8, marginBottom: 12,
  },
  primaryBtnText: { color: '#fff', fontSize: 15, fontWeight: '600' },
  secondaryBtn: { paddingHorizontal: 28, paddingVertical: 12 },
  secondaryBtnText: { color: '#94a3b8', fontSize: 15 },

  camera: { flex: 1 },
  overlay: { flex: 1, justifyContent: 'space-between', backgroundColor: 'transparent' },
  topBar: {
    flexDirection: 'row', justifyContent: 'flex-start',
    paddingHorizontal: 20, paddingTop: 8,
  },
  bottomBar: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: 36, paddingBottom: 24,
  },
  iconBtn: {
    width: 50, height: 50, borderRadius: 25,
    alignItems: 'center', justifyContent: 'center',
    backgroundColor: 'rgba(0,0,0,0.35)',
  },
  shutter: {
    width: 72, height: 72, borderRadius: 36,
    backgroundColor: 'rgba(255,255,255,0.25)',
    borderWidth: 4, borderColor: '#fff',
    alignItems: 'center', justifyContent: 'center',
  },
  shutterInner: {
    width: 56, height: 56, borderRadius: 28, backgroundColor: '#fff',
  },
});
