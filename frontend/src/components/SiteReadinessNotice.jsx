import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { AlertTriangle, CloudDownload } from 'lucide-react-native';
import { semantic, withAlpha } from '../styles/semanticColors';
import { spacing, borderRadius } from '../styles/theme';
import {
  SITE_READY_UNKNOWN,
  SITE_READY_NEVER,
  readSiteReadiness,
  describeReadiness,
} from '../utils/siteDeviceReadiness';

/**
 * WHETHER THIS TABLET CAN BE TAKEN AT ITS WORD, SAID ON THE SCREEN.
 *
 * The model — and the argument behind all three states, and the exact wording
 * and why each clause is in it — is src/utils/siteDeviceReadiness.js. This file
 * is only the paint.
 *
 * A SEPARATE NOTICE FROM <OfflineNotice>, DELIBERATELY. That one answers "did
 * the network answer just now"; this one answers "does this device hold the
 * complete approved set". They are orthogonal, both can be true at once, and
 * the /site screens carry both — but a single component saying both would blur
 * the one distinction that matters, which is that a failed read is temporary
 * and an unfinished device is not.
 */
export default function SiteReadinessNotice({ readiness, style }) {
  const copy = describeReadiness(readiness);
  if (!copy) return null;

  const critical = copy.tone === 'critical';
  const Icon = critical ? AlertTriangle : CloudDownload;
  const tint = critical ? semantic.critical : semantic.attention;

  return (
    <View
      style={[
        s.wrap,
        { borderColor: withAlpha(tint, critical ? 0.7 : 0.4), backgroundColor: withAlpha(tint, 0.12) },
        critical && s.wrapCritical,
        style,
      ]}
      accessibilityRole="alert"
    >
      <Icon size={critical ? 28 : 22} strokeWidth={1.8} color={tint} />
      <View style={s.textWrap}>
        <Text style={[s.heading, critical && s.headingCritical, { color: tint }]}>
          {copy.heading}
        </Text>
        <Text style={s.body}>{copy.body}</Text>
        {!!copy.detail && <Text style={s.detail}>{copy.detail}</Text>}
      </View>
    </View>
  );
}

/**
 * The device's readiness, re-read on a timer.
 *
 * ON A TIMER BECAUSE NOBODY TOUCHES THIS DEVICE. The tablet is bolted to a
 * gate and left on one screen for days; a state read once at mount would show
 * yesterday's verdict for ever — it would APPEAR only if somebody navigated,
 * and, worse, a freshly provisioned tablet would keep accusing itself long
 * after it had finished filling. Thirty seconds is short enough that the
 * warning tracks the device rather than the navigation, and long enough that
 * the directory listing is not a load.
 *
 * It reads AsyncStorage and one directory listing. No network, so it costs
 * nothing in a dead zone and reports the same answer there as anywhere.
 */
export function useSiteReadiness(projectId, opts = {}) {
  const intervalMs = opts.intervalMs === undefined ? 30000 : opts.intervalMs;
  const [readiness, setReadiness] = useState({ state: SITE_READY_UNKNOWN });

  useEffect(() => {
    if (!projectId) { setReadiness({ state: SITE_READY_UNKNOWN }); return undefined; }
    let alive = true;
    const tick = async () => {
      try {
        const r = await readSiteReadiness(projectId);
        if (alive) setReadiness(r);
      } catch (_e) {
        // A READ THAT THREW IS NOT AN ACCUSATION. Falling back to UNKNOWN
        // shows nothing, which is right: this component must never be the
        // reason a healthy tablet is reported broken.
        if (alive) setReadiness({ state: SITE_READY_UNKNOWN });
      }
    };
    tick();
    const timer = intervalMs > 0 ? setInterval(tick, intervalMs) : null;
    return () => { alive = false; if (timer) clearInterval(timer); };
  }, [projectId, intervalMs]);

  return readiness;
}

/**
 * May this screen still make a claim about the RECORD?
 *
 * The honest-empty discipline on the /site screens ("No Submitted Logs" is a
 * claim about the record, so it may only be made when the SERVER answered) is
 * unchanged and stays exactly where it is. This adds the second condition it
 * never had: on a device that holds no complete set, an empty screen is not a
 * fact about the project at all — it is a fact about the tablet, and the
 * notice above is already stating it. Two contradictory explanations of the
 * same blank screen is worse than one.
 */
export const canClaimEmpty = (readiness) => (readiness || {}).state !== SITE_READY_NEVER;

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
  // The not-ready case is read across a gate by someone holding something in
  // the other hand, so it gets a heavier edge and more room than an advisory.
  wrapCritical: { borderWidth: 2, padding: spacing.lg },
  textWrap: { flex: 1, minWidth: 0 },
  heading: { fontSize: 15, fontWeight: '700', marginBottom: 4 },
  headingCritical: { fontSize: 19 },
  body: { fontSize: 14, lineHeight: 20, color: '#94a3b8' },
  detail: { fontSize: 13, lineHeight: 18, color: '#94a3b8', marginTop: 6, fontWeight: '600' },
});
