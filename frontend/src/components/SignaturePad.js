import React, { useRef, useState, useEffect } from 'react';
import { View, StyleSheet, Text, Pressable, PanResponder } from 'react-native';
import { Trash2, Check, PenTool } from 'lucide-react-native';
import { colors, spacing, borderRadius, typography } from '../styles/theme';

/**
 * SignaturePad - A drawable signature component
 */
const SignaturePad = ({
  onSignatureCapture,
  signerName,
  onNameChange,
  signedAt,
  title = 'Signature',
  disabled = false,
  existingSignature = null,
}) => {
  const [paths, setPaths] = useState([]);
  const [currentPath, setCurrentPath] = useState([]);
  const [isSigned, setIsSigned] = useState(!!existingSignature);
  const [signatureData, setSignatureData] = useState(existingSignature);
  const containerRef = useRef(null);
  const [containerLayout, setContainerLayout] = useState({ x: 0, y: 0, width: 0, height: 0 });

  useEffect(() => {
    if (existingSignature) {
      setIsSigned(true);
      setSignatureData(existingSignature);
    }
  }, [existingSignature]);

  const panResponder = useRef(
    PanResponder.create({
      onStartShouldSetPanResponder: () => !disabled && !isSigned,
      onMoveShouldSetPanResponder: () => !disabled && !isSigned,
      onPanResponderGrant: (evt) => {
        const { locationX, locationY } = evt.nativeEvent;
        setCurrentPath([{ x: locationX, y: locationY }]);
      },
      onPanResponderMove: (evt) => {
        const { locationX, locationY } = evt.nativeEvent;
        setCurrentPath((prev) => [...prev, { x: locationX, y: locationY }]);
      },
      onPanResponderRelease: () => {
        if (currentPath.length > 0) {
          setPaths((prev) => [...prev, currentPath]);
          setCurrentPath([]);
        }
      },
    })
  ).current;

  const handleClear = () => {
    setPaths([]);
    setCurrentPath([]);
    setIsSigned(false);
    setSignatureData(null);
    if (onSignatureCapture) {
      onSignatureCapture(null);
    }
  };

  const handleConfirm = () => {
    if (paths.length === 0 || !signerName?.trim()) {
      return;
    }

    const timestamp = new Date().toISOString();
    const signature = {
      paths: paths,
      signer_name: signerName,
      signed_at: timestamp,
    };

    setIsSigned(true);
    setSignatureData(signature);

    if (onSignatureCapture) {
      onSignatureCapture(signature);
    }
  };

  const renderPaths = () => {
    const allPaths = [...paths, currentPath].filter((p) => p.length > 0);

    return allPaths.map((path, pathIndex) => {
      if (path.length < 2) return null;

      let d = `M ${path[0].x} ${path[0].y}`;
      for (let i = 1; i < path.length; i++) {
        d += ` L ${path[i].x} ${path[i].y}`;
      }

      return (
        <View key={pathIndex} style={StyleSheet.absoluteFill}>
          <svg width="100%" height="100%" style={{ position: 'absolute' }}>
            <path d={d} stroke="#000000" strokeWidth="2" fill="none" strokeLinecap="round" />
          </svg>
        </View>
      );
    });
  };

  const formatTimestamp = (timestamp) => {
    if (!timestamp) return '';
    const date = new Date(timestamp);
    return date.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <View style={styles.titleRow}>
          <PenTool size={16} strokeWidth={1.5} color="#999999" />
          <Text style={styles.title}>{title}</Text>
        </View>
        {isSigned && signatureData?.signed_at && (
          <Text style={styles.timestamp}>{formatTimestamp(signatureData.signed_at)}</Text>
        )}
      </View>

      {/* Name Input */}
      <View style={styles.nameSection}>
        <Text style={styles.label}>PRINTED NAME</Text>
        <View style={styles.nameInput}>
          <Text
            style={[
              styles.nameText,
              !signerName && styles.namePlaceholder,
              isSigned && styles.nameTextSigned,
            ]}
          >
            {signerName || 'Enter name...'}
          </Text>
          {!isSigned && !disabled && (
            <Pressable
              onPress={() => {
                // In a real app, this would open a text input modal
                const name = prompt('Enter signer name:');
                if (name && onNameChange) {
                  onNameChange(name);
                }
              }}
              style={styles.editNameBtn}
            >
              <Text style={styles.editNameText}>Edit</Text>
            </Pressable>
          )}
        </View>
      </View>

      {/* Signature Area */}
      <View
        ref={containerRef}
        onLayout={(e) => setContainerLayout(e.nativeEvent.layout)}
        style={[styles.signatureArea, isSigned && styles.signatureAreaSigned]}
        {...(isSigned ? {} : panResponder.panHandlers)}
      >
        {isSigned ? (
          <View style={styles.signedContent}>
            {signatureData?.paths ? (
              <View style={styles.signaturePreview}>
                <svg width="100%" height="100%">
                  {signatureData.paths.map((path, pathIndex) => {
                    if (path.length < 2) return null;
                    let d = `M ${path[0].x} ${path[0].y}`;
                    for (let i = 1; i < path.length; i++) {
                      d += ` L ${path[i].x} ${path[i].y}`;
                    }
                    return (
                      <path
                        key={pathIndex}
                        d={d}
                        stroke="#000000"
                        strokeWidth="2"
                        fill="none"
                        strokeLinecap="round"
                      />
                    );
                  })}
                </svg>
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
                  (paths.length === 0 || !signerName?.trim()) && styles.actionBtnDisabled,
                ]}
                disabled={paths.length === 0 || !signerName?.trim()}
              >
                <Check size={16} strokeWidth={1.5} color="#fff" />
                <Text style={styles.confirmText}>Confirm Signature</Text>
              </Pressable>
            </>
          )}
        </View>
      )}
    </View>
  );
};

const styles = StyleSheet.create({
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
  nameInput: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: 'rgba(255, 255, 255, 0.05)',
    borderRadius: borderRadius.md,
    padding: spacing.sm,
  },
  nameText: {
    fontSize: 15,
    color: colors.text.primary,
  },
  namePlaceholder: {
    color: colors.text.muted,
    fontStyle: 'italic',
  },
  nameTextSigned: {
    fontWeight: '500',
  },
  editNameBtn: {
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    backgroundColor: 'rgba(255, 255, 255, 0.1)',
    borderRadius: borderRadius.sm,
  },
  editNameText: {
    fontSize: 12,
    color: colors.text.secondary,
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
    backgroundColor: 'rgba(255, 255, 255, 0.05)',
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.glass.border,
  },
  actionBtnDisabled: {
    opacity: 0.5,
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
});

export default SignaturePad;
