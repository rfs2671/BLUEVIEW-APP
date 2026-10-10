/**
 * YOUR CALENDAR FEED (Integrations → WhatsApp → Personal assistant): the
 * person's private, revocable ICS link with everything coming up on their
 * jobs -- city hearings and permit expirations, dated events said in the
 * job's WhatsApp groups, and their own "remind me"s. Subscribe once in
 * Google Calendar or Outlook. The link is shown once, when it is made.
 * (GET / POST / DELETE /api/me/calendar-feed)
 */
import React, { useCallback, useEffect, useState } from 'react';
import { View, Text, StyleSheet } from 'react-native';
import * as Clipboard from 'expo-clipboard';
import { Link2 } from 'lucide-react-native';
import { GlassCard } from '../GlassCard';
import GlassButton from '../GlassButton';
import { useToast } from '../Toast';
import { upcomingAPI } from '../../utils/api';
import { spacing, borderRadius } from '../../styles/theme';
import { useTheme } from '../../context/ThemeContext';

export default function CalendarFeedCard() {
  const { colors } = useTheme();
  const toast = useToast();
  const [feed, setFeed] = useState(null);         // { active, url? }
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setFeed(await upcomingAPI.feedStatus());
    } catch (e) {
      setFeed(null);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const makeFeed = async () => {
    setBusy(true);
    try {
      const made = await upcomingAPI.makeFeed();
      setFeed({ active: true, url: made.url });
    } catch (err) {
      toast?.error?.('Calendar link', 'Could not make one. Try again.');
    } finally {
      setBusy(false);
    }
  };

  const revokeFeed = async () => {
    setBusy(true);
    try {
      await upcomingAPI.revokeFeed();
      setFeed({ active: false });
    } catch (err) {
      toast?.error?.('Calendar link', 'Could not turn it off. Try again.');
    } finally {
      setBusy(false);
    }
  };

  const copy = async (url) => {
    await Clipboard.setStringAsync(url);
    toast?.success?.('Copied', 'Paste it into Google or Outlook: “Subscribe from URL”.');
  };

  const text = { color: colors.text.primary };
  const muted = { color: colors.text.muted };

  return (
    <GlassCard style={styles.card}>
      <View style={styles.head}>
        <Link2 size={16} color={text.color} />
        <Text style={[styles.section, text]}>Your calendar feed</Text>
      </View>
      <Text style={[styles.line, muted]}>
        A private link with everything coming up on your jobs. Subscribe to it once in Google
        Calendar or Outlook; it stays up to date. Anyone with the link can see it, so keep it
        to yourself. Turning it off stops it at once.
      </Text>
      {feed && feed.url ? (
        <>
          <Text selectable style={[styles.url, text]}>{feed.url}</Text>
          <Text style={[styles.chip, muted]}>Shown once. Copy it now.</Text>
          <View style={styles.buttons}>
            <GlassButton title="Copy link" onPress={() => copy(feed.url)} />
            <GlassButton title="Turn off" onPress={revokeFeed} disabled={busy} />
          </View>
        </>
      ) : feed && feed.active ? (
        <View style={styles.buttons}>
          <GlassButton title="New link" onPress={makeFeed} disabled={busy} />
          <GlassButton title="Turn off" onPress={revokeFeed} disabled={busy} />
        </View>
      ) : (
        <View style={styles.buttons}>
          <GlassButton title="Get my calendar link" onPress={makeFeed} disabled={busy} />
        </View>
      )}
    </GlassCard>
  );
}

const styles = StyleSheet.create({
  card: { padding: spacing.md, marginTop: spacing.md, borderRadius: borderRadius.lg },
  head: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  section: { fontWeight: '700', marginBottom: spacing.sm, flex: 1 },
  line: { fontSize: 15, lineHeight: 21 },
  chip: { fontSize: 12, marginTop: 2 },
  url: { fontSize: 13, marginVertical: spacing.sm },
  buttons: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, marginTop: spacing.sm },
});
