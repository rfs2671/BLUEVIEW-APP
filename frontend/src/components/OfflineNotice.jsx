import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { CloudOff, AlertTriangle } from 'lucide-react-native';
import { semantic, withAlpha } from '../styles/semanticColors';
import { spacing, borderRadius } from '../styles/theme';

/**
 * The honest replacement for a false empty state.
 *
 * Screens used to render "No Documents" / "No Submitted Logs" when the fetch
 * FAILED, which reads as "none exist" — actively misleading, and on the
 * Inspector Mode screen it misrepresents compliance to a DOB inspector.
 *
 * Use with settleFetch()/isOfflineError() (src/utils/offlineState.js):
 *   fetchState === 'offline' -> <OfflineNotice mode="offline" />
 *   fetchState === 'error'   -> <OfflineNotice mode="error" />
 *   otherwise                -> the screen's REAL empty state
 *
 * `cachedCount` is for the cache-first screens: when we CAN show cached data
 * offline, say that instead of blocking.
 */
export default function OfflineNotice({ mode = 'offline', detail, cachedCount, style }) {
  const offline = mode === 'offline';
  const Icon = offline ? CloudOff : AlertTriangle;
  const tint = offline ? semantic.attention : semantic.critical;

  const title = offline
    ? (cachedCount > 0 ? 'Offline — showing saved copy' : 'Unavailable offline')
    : 'Could not load';

  const body = detail || (offline
    ? (cachedCount > 0
        ? `Reconnect to refresh. ${cachedCount} saved item${cachedCount === 1 ? '' : 's'} shown.`
        : 'Reconnect to load this. Nothing is saved on this device yet.')
    : 'Something went wrong reading this. Pull to refresh or try again.');

  return (
    <View style={[s.wrap, { borderColor: withAlpha(tint, 0.4), backgroundColor: withAlpha(tint, 0.1) }, style]}>
      <Icon size={22} strokeWidth={1.8} color={tint} />
      <View style={s.textWrap}>
        <Text style={[s.title, { color: tint }]}>{title}</Text>
        <Text style={s.body}>{body}</Text>
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  wrap: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: spacing.md,
    borderWidth: 1,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    marginVertical: spacing.sm,
  },
  textWrap: { flex: 1, minWidth: 0 },
  title: { fontSize: 14, fontWeight: '700', marginBottom: 2 },
  body: { fontSize: 13, lineHeight: 18, color: '#94a3b8' },
});
