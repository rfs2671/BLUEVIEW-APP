import React, { useRef, useState, useEffect, useCallback } from 'react';
import { View, StyleSheet, Text, Pressable, PanResponder, TextInput, Platform } from 'react-native';
import { Trash2, Check, PenTool, AlertTriangle } from 'lucide-react-native';
import { useTheme } from '../context/ThemeContext';
import { spacing, borderRadius, typography } from '../styles/theme';
import { semantic, withAlpha } from '../styles/semanticColors';
import { useT, useLocale } from '../i18n';

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

// A signature counts as affirmed for THIS document only when it carries a
// per-document affirmation stamp. An inherited profile credential does NOT.
function sigIsAffirmed(sig) {
  return !!(sig && typeof sig === 'object' && sig.affirmed === true);
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
  // Locale OVERRIDE for the affirmation copy. It used to default to 'en' and
  // was the ONLY way to reach the Spanish strings — and all 13 screens that
  // render this pad pass nothing, so Spanish was unreachable in the shipped
  // app. The default is now undefined: unset means "follow the app-wide
  // locale" (src/i18n), which starts at 'en', so an unset caller renders
  // exactly what it rendered before. Passing lang still pins one locale.
  lang,
}) => {
  const { isDark, colors } = useTheme();
  const styles = buildStyles(colors, isDark);

  // THE PAD OWNS ITS OWN LANGUAGE.
  //
  // The thing being translated is the sentence a person SIGNS, so it belongs to
  // that signature — not to a session-wide mode somebody set on another screen
  // an hour earlier. The toggle used to live in app/logbooks/review.jsx and
  // called the app-wide setLocale, which meant it changed this pad remotely,
  // from a screen that does not even render one.
  //
  // Local state, so there is no session state to lose: a CP who picks Spanish
  // and force-closes the app is not silently back in English on a signature he
  // has already read once. An explicit `lang` prop still wins and hides the
  // toggle — a caller that pins a locale means it.
  const [padLang, setPadLang] = useState(lang);
  // Resolved to a CONCRETE locale, never undefined, because it is recorded onto
  // the signature: "the affirmation was shown in en" is a fact, `undefined` is
  // not. Precedence: an explicit prop, then this pad's own choice, then the app
  // locale (which has no control today and is always 'en' — see setLocale).
  const appLocale = useLocale();
  const activeLang = lang ?? padLang ?? appLocale;
  const t = useT('signature', activeLang);

  const [paths, setPaths] = useState([]);
  const [currentPath, setCurrentPath] = useState([]);
  const [isSigned, setIsSigned] = useState(autoLock ? !!existingSignature : false);
  const [signatureData, setSignatureData] = useState(existingSignature);
  // Affirmed FOR THIS DOCUMENT. An inherited profile signature starts
  // UNAFFIRMED; a signature persisted as affirmed on this doc (a reopened
  // draft) starts affirmed; drawing or tapping Affirm this session affirms it.
  // Never render VERIFIED unless this is true.
  const [isAffirmed, setIsAffirmed] = useState(sigIsAffirmed(existingSignature));
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
      setIsAffirmed(sigIsAffirmed(existingSignature));
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
    setIsAffirmed(false);
    isSignedRef.current = false;
    onSignatureCapture?.(null);
  }, [onSignatureCapture]);

  const canConfirm = paths.length > 0 && signerName?.trim();

  const handleConfirm = useCallback(() => {
    if (!canConfirm) return;

    // A fresh draw is inherently affirmed for THIS document — stamp it now.
    const now = new Date().toISOString();
    const sigData = {
      paths: pathsRef.current,
      signerName: signerName?.trim(),
      timestamp: now,
      affirmed: true,
      affirmedAt: now,
      // WHAT THE SIGNER WAS SHOWN, frozen at this instant. See handleAffirm.
      affirmedLang: activeLang,
    };

    setSignatureData(sigData);
    setIsSigned(true);
    setIsAffirmed(true);
    isSignedRef.current = true;
    onSignatureCapture?.(sigData);
  }, [canConfirm, signerName, onSignatureCapture, activeLang]);

  // ONE explicit affirmative action per document: keep the inherited credential
  // image but stamp a FRESH affirmation timestamp onto THIS record and emit it.
  //
  // affirmedLang records WHAT THE SIGNER WAS SHOWN, captured here and FROZEN.
  // It is written once, next to affirmedAt, from the locale rendering at this
  // instant — and never read back out of state afterwards. That matters: the
  // toggle stays usable after signing, so a field that tracked live state would
  // silently rewrite what the record claims a person was shown. A record that
  // changes after the fact is worse than no record.
  //
  // Precedent for storing it at all: subcontractor_orientation.jsx already
  // stores language_provided and renders it back.
  const handleAffirm = useCallback(() => {
    const now = new Date().toISOString();
    const base = (signatureData && typeof signatureData === 'object')
      ? signatureData
      : { data: signatureData };
    const affirmedSig = {
      ...base,
      signerName: signerName?.trim() || base.signerName,
      timestamp: now,
      affirmed: true,
      affirmedAt: now,
      affirmedLang: activeLang,
    };
    setSignatureData(affirmedSig);
    setIsAffirmed(true);
    onSignatureCapture?.(affirmedSig);
  }, [signatureData, signerName, onSignatureCapture, activeLang]);

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
        <View style={styles.headerRight}>
          {isAffirmed && (signatureData?.affirmedAt || signatureData?.timestamp) && (
            <Text style={styles.timestamp}>
              {new Date(signatureData.affirmedAt || signatureData.timestamp).toLocaleTimeString()}
            </Text>
          )}
          {/* Language of the AFFIRMATION — the sentence being signed. Local to
              this pad, so nothing else in the app changes and there is no
              session state to lose. Hidden when the caller pinned `lang`: a
              caller that names a locale means it. */}
          {lang === undefined && (
            <Pressable
              onPress={() => setPadLang(activeLang === 'es' ? 'en' : 'es')}
              hitSlop={16}
              accessibilityRole="button"
              accessibilityLabel={activeLang === 'es'
                ? 'Ver esta declaración en inglés'
                : 'View this statement in Spanish'}
              style={styles.langToggle}
            >
              <Text style={styles.langToggleText}>
                {activeLang === 'es' ? 'EN' : 'ES'}
              </Text>
            </Pressable>
          )}
        </View>
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
            {isAffirmed ? (
              <View style={styles.signedBadge}>
                <Check size={12} strokeWidth={2} color={semantic.verified} />
                <Text style={styles.signedBadgeText}>{t('verified')}</Text>
              </View>
            ) : (
              <View style={styles.unaffirmedBadge}>
                <AlertTriangle size={12} strokeWidth={2} color={semantic.attention} />
                <Text style={styles.unaffirmedBadgeText}>{t('unaffirmed')}</Text>
              </View>
            )}
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
          {isSigned && isAffirmed ? (
            <Pressable onPress={handleClear} style={styles.clearBtn}>
              <Trash2 size={16} strokeWidth={1.5} color={semantic.neutral} />
              <Text style={styles.clearText}>{t('clearResign')}</Text>
            </Pressable>
          ) : isSigned && !isAffirmed ? (
            // Inherited credential — require ONE explicit affirmation for this
            // document, or clear it to draw a fresh one.
            <>
              <Pressable onPress={handleClear} style={styles.actionBtn}>
                <Trash2 size={16} strokeWidth={1.5} color={colors.text.muted} />
                <Text style={styles.actionText}>{t('clearResign')}</Text>
              </Pressable>
              <Pressable onPress={handleAffirm} style={[styles.actionBtn, styles.affirmBtn]}>
                <Check size={16} strokeWidth={1.5} color="#fff" />
                <Text style={styles.confirmText}>{t('affirm')}</Text>
              </Pressable>
            </>
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

      {/* Inherited-but-unaffirmed hint */}
      {isSigned && !isAffirmed && (
        <Text style={styles.unaffirmedHint}>{t('unaffirmedHint')}</Text>
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
    headerRight: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.sm,
    },
    langToggle: {
      minWidth: 44,
      minHeight: 44,
      alignItems: 'center',
      justifyContent: 'center',
      paddingHorizontal: spacing.sm,
      borderRadius: borderRadius.sm,
      borderWidth: 1,
      borderColor: withAlpha(colors.text.muted, 0.35),
    },
    langToggleText: {
      fontSize: 12,
      fontWeight: '700',
      color: colors.text.secondary,
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
      backgroundColor: isDark ? withAlpha('#ffffff', 0.05) : withAlpha('#000000', 0.04),
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
      backgroundColor: isDark ? withAlpha('#ffffff', 0.05) : withAlpha('#000000', 0.04),
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
      borderColor: withAlpha('#000000', 0.2),
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
      backgroundColor: semantic.verifiedBg,
      paddingHorizontal: spacing.sm,
      paddingVertical: 4,
      borderRadius: borderRadius.full,
    },
    signedBadgeText: {
      fontSize: 10,
      fontWeight: '600',
      color: semantic.verified,
      letterSpacing: 0.5,
    },
    unaffirmedBadge: {
      position: 'absolute',
      bottom: spacing.sm,
      right: spacing.sm,
      flexDirection: 'row',
      alignItems: 'center',
      gap: 4,
      backgroundColor: semantic.attentionBg,
      paddingHorizontal: spacing.sm,
      paddingVertical: 4,
      borderRadius: borderRadius.full,
    },
    unaffirmedBadgeText: {
      fontSize: 10,
      fontWeight: '600',
      color: semantic.attention,
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
      backgroundColor: isDark ? withAlpha('#ffffff', 0.05) : withAlpha('#000000', 0.04),
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
    affirmBtn: {
      flex: 2,
      backgroundColor: semantic.attention,
      borderColor: semantic.attention,
    },
    clearBtn: {
      flex: 1,
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'center',
      gap: spacing.xs,
      paddingVertical: spacing.md,
      backgroundColor: semantic.criticalBg,
      borderRadius: borderRadius.lg,
      borderWidth: 1,
      borderColor: semantic.criticalBorder,
    },
    clearText: {
      fontSize: 14,
      color: semantic.neutralStrong,
    },
    hintText: {
      fontSize: 12,
      color: semantic.attention,
      textAlign: 'center',
      marginTop: spacing.sm,
    },
    unaffirmedHint: {
      fontSize: 12,
      color: semantic.attention,
      textAlign: 'center',
      marginTop: spacing.sm,
    },
  });
}

export default SignaturePad;
