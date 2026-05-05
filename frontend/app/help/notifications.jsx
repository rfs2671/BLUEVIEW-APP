/**
 * Phase B4 — /help/notifications.
 *
 * Walkthrough of the notification preferences UI: presets,
 * per-project overrides, the preview tool, and the SMS roadmap
 * disclaimer.
 */

import React from 'react';
import HelpPageShell, {
  HelpSection,
  HelpParagraph,
  HelpBullets,
  HelpKbd,
} from '../../src/components/HelpPageShell';

export default function HelpNotifications() {
  return (
    <HelpPageShell title="Notification preferences">
      <HelpSection title="Choosing a preset">
        <HelpParagraph>
          We offer three preset shapes — each generates a complete
          configuration covering all 26 signal_kinds. Pick the one that
          matches your team's tolerance for email volume:
        </HelpParagraph>
        <HelpBullets
          items={[
            "Critical only (default for new users) — only urgent items email you immediately. The other 20 stay in the activity feed only. Six signal kinds trigger emails: violation_dob, violation_ecb, stop_work_full, stop_work_partial, inspection_failed, filing_disapproved.",
            "Standard — critical items immediately, plus a daily 7am ET digest covering 4 warning signal kinds (permit_expired, inspection_scheduled, license_renewal_due, complaint_dob). Info-only items stay in the feed.",
            "Everything — every DOB signal triggers an email immediately. Useful for very active sites where you need to react to every event. High volume.",
          ]}
        />
      </HelpSection>

      <HelpSection title="When to use each preset">
        <HelpBullets
          items={[
            "Critical only — best for office staff who want one-touch awareness without inbox noise. Recommended for most users.",
            "Standard — best for project managers who want a morning brief covering warnings + immediate alerts for emergencies.",
            "Everything — best for compliance teams or projects with tight deadlines where you cannot afford to miss any DOB activity.",
          ]}
        />
      </HelpSection>

      <HelpSection title="Per-project overrides">
        <HelpParagraph>
          Your preset applies globally by default. To silence one
          specific project (or amplify it), open Settings →
          Notifications → Per-project overrides:
        </HelpParagraph>
        <HelpBullets
          items={[
            "Pick a project from the dropdown.",
            "Apply a preset that's different from your global one — for example, \"Critical only\" globally but \"Everything\" on the one project that's about to fail an inspection.",
            "Or customize per-signal_kind delivery channels and severity thresholds for that project alone.",
            "The override only applies to that one project. Removing it falls back to your global preset.",
          ]}
        />
      </HelpSection>

      <HelpSection title="How preview works">
        <HelpParagraph>
          The Preview tool at the top of Settings → Notifications
          replays the last 7 days of signals through your current
          (unsaved) preferences and shows what would have been
          delivered:
        </HelpParagraph>
        <HelpBullets
          items={[
            "Immediate emails — count of signals that would have triggered an email right away.",
            "Digest — count of signals that would have rolled into a daily digest.",
            "Feed only — count of signals that would have stayed silent (still visible in the feed).",
          ]}
        />
        <HelpParagraph>
          Use this before saving a new preset to gauge volume. Preview
          runs against your real signal history, so the count is
          accurate to your projects.
        </HelpParagraph>
      </HelpSection>

      <HelpSection title="Advanced — per-signal_kind controls">
        <HelpParagraph>
          The Advanced section under each preset lets you fine-tune
          individual signal kinds:
        </HelpParagraph>
        <HelpBullets
          items={[
            "Channels — email, in-app, or both. (SMS is on the roadmap; see below.)",
            "Severity threshold — \"any\", \"warning or higher\", \"critical only\", or \"off\".",
            "Delivery — immediate, daily digest, weekly digest, or feed-only.",
          ]}
        />
        <HelpParagraph>
          Each row has a "What does this mean?" link that explains the
          signal type in plain English.
        </HelpParagraph>
      </HelpSection>

      <HelpSection title="SMS — coming soon">
        <HelpParagraph>
          SMS delivery for critical signals is on the v1.1 roadmap.
          Today, all alerts are email or in-app feed only. We're
          tracking interest — if SMS would meaningfully improve your
          workflow, let us know via the chat widget.
        </HelpParagraph>
      </HelpSection>
    </HelpPageShell>
  );
}
