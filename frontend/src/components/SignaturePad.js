import React, { useRef, useState, useEffect, useCallback } from 'react';
import { View, StyleSheet, Text, Pressable, PanResponder, TextInput, Platform } from 'react-native';
import { Trash2, Check, PenTool } from 'lucide-react-native';
import { useTheme } from '../context/ThemeContext';
import { spacing, borderRadius, typography } from '../styles/theme';

/**
 * Renders a set of paths as tiny absolutely-positioned dots inside a container.
 * Works identically on web and native — no SVG needed.
 */
function PathRenderer({ paths, strokeColor = '#000000', strokeWidth = 2 }) {
  if (!paths || paths.length === 0) return null;

  return (
    <View style={StyleSheet.absoluteFill} pointerEvents="none">
      {paths.map((path, pathIndex) => {
        if (!path || path.length < 2) return null;
        // Draw line segments as small View rectangles
        return path.slice(1).map((point, i) => {
          const prev = path[i];
          const dx = point.x - prev.x;
          const dy = point.y - prev.y;
          const length = Math.sqrt(dx * dx + dy * dy);
          if (length === 0) return null;
          const angle = Math.atan2(dy, dx) * (180 / Math.PI);

          return (
            <View
              key={`${pathIndex}-${i}`}
              style={{
                position: 'absolute',
                left: prev.x,
                top: prev.y - strokeWidth / 2,
                width: length + 1,
                height: strokeWidth,
                backgroundColor: strokeColor,
                borderRadius: strokeWidth / 2,
                transform: [{ rotate: `${angle}deg` }],
                transformOrigin: 'left center',
              }}
            />
          );
        });
      })}
    </View>
  );
}

const SignaturePad = ({
  onSignatureCapture,
  signerName,
  onNameChange,
  signedAt,
  title = 'Signature',
  disabled = false,
  existingSignature = null,
  // autoLock=false keeps the pad editable even when existingSignature
  // is passed — used on forms where the caller wants the signer to
  // retype/redraw each time instead of inheriting a cached signature.
  autoLock = true,
}) => {
  const { isDark, colors } = useTheme();
  const styles = buildStyles(colors, isDark);

  const [paths, setPaths] = useState([]);
  const [currentPath, setCurrentPath] = useState([]);
  const [isSigned, setIsSigned] = useState(autoLock ? !!existingSignature : false);
  const [signatureData, setSignatureData] = useState(existingSignature);
  const containerRef = useRef(null);

  // ── Refs to avoid stale closures in PanResponder ──
  const pathsRef = useRef([]);
  const currentPathRef = useRef([]);
  const isSignedRef = useRef(!!existingSignature);
  const disabledRef = useRef(disabled);

  useEffect(() => { disabledRef.current = disabled; }, [disabled]);
  useEffect(() => { isSignedRef.current = isSigned; }, [isSigned]);

  useEffect(() => {
    if (existingSignature) {
      setIsSigned(true);
      setSignatureData(existingSignature);
      isSignedRef.current = true;
    }
  }, [existingSignature]);

  const panResponder = useRef(
    PanResponder.create({
      onStartShouldSetPanResponder: () => !disabledRef.current && !isSignedRef.current,
      onMoveShouldSetPanResponder: () => !disabledRef.current && !isSignedRef.current,
      onPanResponderGrant: (evt) => {
        const { locationX, locationY } = evt.nativeEvent;
        const newPoint = [{ x: locationX, y: locationY }];
        currentPathRef.current = newPoint;
        setCurrentPath(newPoint);
      },
      onPanResponderMove: (evt) => {
        const { locationX, locationY } = evt.nativeEvent;
        const updated = [...currentPathRef.current, { x: locationX, y: locationY }];
        currentPathRef.current = updated;
        setCurrentPath(updated);
      },
      onPanResponderRelease: () => {
        if (currentPathRef.current.length > 0) {
          const newPaths = [...pathsRef.current, currentPathRef.current];
          pathsRef.current = newPaths;
          setPaths(newPaths);
          currentPathRef.current = [];
          setCurrentPath([]);
        }
      },
    })
  ).current;

  const handleClear = useCallback(() => {
    pathsRef.current = [];
    currentPathRef.current = [];
    setPaths([]);
    setCurrentPath([]);
    setIsSigned(false);
    setSignatureData(null);
    isSignedRef.current = false;
    onSignatureCapture?.(null);
  }, [onSignatureCapture]);

  const canConfirm = paths.length > 0 && signerName?.trim();

  const handleConfirm = useCallback(() => {
    if (!canConfirm) return;

    const sigData = {
      paths: pathsRef.current,
      signerName: signerName?.trim(),
      timestamp: new Date().toISOString(),
    };

    setSignatureData(sigData);
    setIsSigned(true);
    isSignedRef.current = true;
    onSignatureCapture?.(sigData);
  }, [canConfirm, signerName, onSignatureCapture]);

  // ── Render active drawing paths (current stroke + completed strokes) ──
  const renderPaths = () => {
    const allPaths = currentPath.length > 0 ? [...paths, currentPath] : paths;
    return <PathRenderer paths={allPaths} strokeColor="#000000" strokeWidth={2} />;
  };

  return (
    <View style={styles.container}>
      {/* Header */}
      <View style={styles.header}>
        <View style={styles.titleRow}>
          <PenTool size={16} strokeWidth={1.5} color={colors.text.muted} />
          <Text style={styles.title}>{title}</Text>
        </View>
        {isSigned && signatureData?.timestamp && (
          <Text style={styles.timestamp}>
            {new Date(signatureData.timestamp).toLocaleTimeString()}
          </Text>
        )}
      </View>

      {/* Name Input */}
      <View style={styles.nameSection}>
        <Text style={styles.label}>SIGNER NAME</Text>
        {isSigned ? (
          <View style={styles.nameDisplay}>
            <Text style={[styles.nameText, isSigned && styles.nameTextSigned]}>
              {signerName || 'No name'}
            </Text>
          </View>
        ) : (
          <TextInput
            style={styles.nameTextInput}
            value={signerName || ''}
            onChangeText={(text) => onNameChange && onNameChange(text)}
            placeholder="Enter your name..."
            placeholderTextColor={colors.text.muted}
            autoCapitalize="words"
            autoCorrect={false}
          />
        )}
      </View>

      {/* Signature Area */}
      <View
        ref={containerRef}
        style={[styles.signatureArea, isSigned && styles.signatureAreaSigned]}
        {...(isSigned ? {} : panResponder.panHandlers)}
      >
        {isSigned ? (
          <View style={styles.signedContent}>
            {signatureData?.paths ? (
              <View style={styles.signaturePreview}>
                <PathRenderer
                  paths={signatureData.paths}
                  strokeColor="#000000"
                  strokeWidth={2}
                />
              </View>
            ) : (
              <Text style={styles.signedText}>✓ Signed</Text>
            )}
            <View style={styles.signedBadge}>
              <Check size={12} strokeWidth={2} color="#4ade80" />
              <Text style={styles.signedBadgeText}>VERIFIED</Text>
            </View>
          </View>
        ) : paths.length === 0 && currentPath.length === 0 ? (
          <View style={styles.placeholder}>
            <PenTool size={24} strokeWidth={1.5} color={colors.text.subtle} />
            <Text style={styles.placeholderText}>Draw signature here</Text>
          </View>
        ) : (
          renderPaths()
        )}
      </View>

      {/* Actions */}
      {!disabled && (
        <View style={styles.actions}>
          {isSigned ? (
            <Pressable onPress={handleClear} style={styles.clearBtn}>
              <Trash2 size={16} strokeWidth={1.5} color="#ef4444" />
              <Text style={styles.clearText}>Clear & Re-sign</Text>
            </Pressable>
          ) : (
            <>
              <Pressable
                onPress={handleClear}
                style={[styles.actionBtn, paths.length === 0 && styles.actionBtnDisabled]}
                disabled={paths.length === 0}
              >
                <Trash2 size={16} strokeWidth={1.5} color={colors.text.muted} />
                <Text style={styles.actionText}>Clear</Text>
              </Pressable>
              <Pressable
                onPress={handleConfirm}
                style={[
                  styles.actionBtn,
                  styles.confirmBtn,
                  !canConfirm && styles.actionBtnDisabled,
                ]}
                disabled={!canConfirm}
              >
                <Check size={16} strokeWidth={1.5} color="#fff" />
                <Text style={styles.confirmText}>Confirm Signature</Text>
              </Pressable>
            </>
          )}
        </View>
      )}

      {/* Hint if name is missing */}
      {!isSigned && paths.length > 0 && !signerName?.trim() && (
        <Text style={styles.hintText}>Enter your name above to enable confirm</Text>
      )}
    </View>
  );
};

function buildStyles(colors, isDark) {
  return StyleSheet.create({
    container: {
      backgroundColor: colors.glass.background,
      borderRadius: borderRadius.xl,
      borderWidth: 1,
      borderColor: colors.glass.border,
      padding: spacing.lg,
    },
    header: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      marginBottom: spacing.md,
    },
    titleRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.sm,
    },
    title: {
      fontSize: 16,
      fontWeight: '500',
      color: colors.text.primary,
    },
    timestamp: {
      fontSize: 12,
      color: colors.text.muted,
    },
    nameSection: {
      marginBottom: spacing.md,
    },
    label: {
      ...typography.label,
      color: colors.text.muted,
      marginBottom: spacing.xs,
    },
    nameDisplay: {
      backgroundColor: isDark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(0, 0, 0, 0.04)',
      borderRadius: borderRadius.md,
      padding: spacing.sm,
    },
    nameText: {
      fontSize: 15,
      color: colors.text.primary,
    },
    nameTextSigned: {
      fontWeight: '500',
    },
    nameTextInput: {
      backgroundColor: isDark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(0, 0, 0, 0.04)',
      borderRadius: borderRadius.md,
      padding: spacing.sm,
      fontSize: 15,
      color: colors.text.primary,
      borderWidth: 1,
      borderColor: colors.glass.border,
    },
    signatureArea: {
      height: 150,
      backgroundColor: '#ffffff',
      borderRadius: borderRadius.lg,
      borderWidth: 1,
      borderColor: colors.glass.border,
      borderStyle: 'dashed',
      overflow: 'hidden',
      position: 'relative',
    },
    signatureAreaSigned: {
      borderColor: 'rgba(0,0,0,0.2)',
      backgroundColor: '#ffffff',
      borderStyle: 'solid',
    },
    placeholder: {
      flex: 1,
      alignItems: 'center',
      justifyContent: 'center',
      gap: spacing.sm,
    },
    placeholderText: {
      fontSize: 14,
      color: '#999999',
    },
    signedContent: {
      flex: 1,
      alignItems: 'center',
      justifyContent: 'center',
    },
    signaturePreview: {
      width: '100%',
      height: '100%',
      position: 'absolute',
    },
    signedText: {
      fontSize: 24,
      color: '#000000',
      fontWeight: '300',
    },
    signedBadge: {
      position: 'absolute',
      bottom: spacing.sm,
      right: spacing.sm,
      flexDirection: 'row',
      alignItems: 'center',
      gap: 4,
      backgroundColor: 'rgba(74, 222, 128, 0.15)',
      paddingHorizontal: spacing.sm,
      paddingVertical: 4,
      borderRadius: borderRadius.full,
    },
    signedBadgeText: {
      fontSize: 10,
      fontWeight: '600',
      color: '#4ade80',
      letterSpacing: 0.5,
    },
    actions: {
      flexDirection: 'row',
      gap: spacing.sm,
      marginTop: spacing.md,
    },
    actionBtn: {
      flex: 1,
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'center',
      gap: spacing.xs,
      paddingVertical: spacing.md,
      backgroundColor: isDark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(0, 0, 0, 0.04)',
      borderRadius: borderRadius.lg,
      borderWidth: 1,
      borderColor: colors.glass.border,
    },
    actionBtnDisabled: {
      opacity: 0.4,
    },
    actionText: {
      fontSize: 14,
      color: colors.text.muted,
    },
    confirmBtn: {
      flex: 2,
      backgroundColor: '#4ade80',
      borderColor: '#4ade80',
    },
    confirmText: {
      fontSize: 14,
      fontWeight: '500',
      color: '#fff',
    },
    clearBtn: {
      flex: 1,
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'center',
      gap: spacing.xs,
      paddingVertical: spacing.md,
      backgroundColor: 'rgba(239, 68, 68, 0.1)',
      borderRadius: borderRadius.lg,
      borderWidth: 1,
      borderColor: 'rgba(239, 68, 68, 0.3)',
    },
    clearText: {
      fontSize: 14,
      color: '#ef4444',
    },
    hintText: {
      fontSize: 12,
      color: '#f59e0b',
      textAlign: 'center',
      marginTop: spacing.sm,
    },
  });
}

export default SignaturePad;
