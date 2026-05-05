/**
 * Phase B4 — /help/faq.
 *
 * The 8 most-asked questions, plain-English answers.
 */

import React from 'react';
import HelpPageShell, {
  HelpSection,
  HelpParagraph,
  HelpBullets,
  HelpKbd,
} from '../../src/components/HelpPageShell';

export default function HelpFAQ() {
  return (
    <HelpPageShell title="FAQ">
      <HelpSection title="What's the difference between a 311 complaint and a DOB violation?">
        <HelpParagraph>
          A <HelpKbd>311 complaint</HelpKbd> is a report from a member of
          the public — a neighbor, passer-by, or sub on site — about
          something they noticed. It hasn't been verified by DOB yet;
          it's just a tip. 311 routes construction-related complaints to
          DOB (or another agency) for follow-up.
        </HelpParagraph>
        <HelpParagraph>
          A <HelpKbd>DOB violation</HelpKbd> is a formal finding by DOB
          (or ECB) that something on your project breaks the building
          code. Violations carry fines and (usually) a required remedy
          by a deadline. They typically come AFTER an inspection
          triggered by a 311 complaint, an audit, or a periodic
          inspection.
        </HelpParagraph>
        <HelpParagraph>
          A 311 complaint about your project may or may not turn into a
          violation — it depends on what the inspector finds.
        </HelpParagraph>
      </HelpSection>

      <HelpSection title="What does each severity level mean?">
        <HelpParagraph>
          Every signal is tagged with a severity that drives default
          notification behavior:
        </HelpParagraph>
        <HelpBullets
          items={[
            'Critical — immediate action needed: violations, ECB violations, stop-work orders (full or partial), failed inspections, disapproved filings. By default these email you immediately under every preset.',
            'Warning — soon-but-not-now: permit expirations, scheduled inspections, license renewal reminders, DOB complaints. Under "Critical only" these stay in the feed; under "Standard" they batch into a daily digest at 7am ET; under "Everything" they email immediately.',
            'Info — informational: permit issued, filing approved, inspection passed, CofO issued, etc. Under "Critical only" and "Standard" these stay in the feed; under "Everything" they email immediately.',
          ]}
        />
      </HelpSection>

      <HelpSection title="How do I reduce email volume?">
        <HelpBullets
          items={[
            'Open Settings → Notifications and switch to the "Critical only" preset (the default for new users). This drops you to ~6 email-triggering signal types.',
            'Or stay on your current preset and use Per-project overrides to silence one noisy project — for example, a project where you have someone else handling DOB matters.',
            'Or use the Advanced section to silence specific signal types globally (e.g. turn off complaint_311 emails if you find them noisy).',
            'The Activity feed always shows everything regardless of email settings — so you don\'t miss anything by quieting your inbox.',
          ]}
        />
      </HelpSection>

      <HelpSection title="Why didn't I get notified about X?">
        <HelpParagraph>
          A few common reasons:
        </HelpParagraph>
        <HelpBullets
          items={[
            "Your preset suppressed it. Critical only and Standard only email a subset of signal kinds. Open Settings → Notifications → Advanced to see what's on / off.",
            "It was the project's first poll. The initial scan pulls the entire historical backlog and is intentionally silent — you'd otherwise get hundreds of emails on day one. Day 2 onward, only NEW events email you.",
            "The signal landed in a daily digest. Standard preset batches warnings into a 7am ET digest — check your morning email.",
            "Email-throttling kicked in. The same record (e.g. one violation re-pulled by DOB) won't email you twice within 24 hours.",
            "Your spam folder caught it. Add LeveLog's sender to your contacts.",
          ]}
        />
      </HelpSection>

      <HelpSection title="What if my permit expires?">
        <HelpParagraph>
          You'll see a <HelpKbd>permit_expired</HelpKbd> signal in the
          Activity feed, and the Permit Renewals page surfaces every
          expiring permit with a status badge. Work covered by the
          expired permit must stop until it's renewed.
        </HelpParagraph>
        <HelpParagraph>
          For most permits, renewal is a manual filing on DOB NOW —
          LeveLog doesn't file for you, but we surface every PW2 value
          you need to copy into the form. See the{' '}
          <HelpKbd>Permit renewal</HelpKbd> guide for the full flow.
        </HelpParagraph>
      </HelpSection>

      <HelpSection title="Does LeveLog file my renewals?">
        <HelpParagraph>
          No. Renewals are filed manually on DOB NOW by you (or a
          licensed filing rep on your team). LeveLog provides:
        </HelpParagraph>
        <HelpBullets
          items={[
            "An automatic eligibility check (insurance current? license current? PAA needed?) so you know whether the renewal can proceed.",
            "Pre-filled PW2 values you can copy into the DOB NOW form (job number, fee, applicant name + license number).",
            "A direct deep-link to DOB NOW.",
            "A status indicator that tracks the filing through DOB review afterward.",
          ]}
        />
        <HelpParagraph>
          We made this design choice deliberately for v1 — handing your
          DOB NOW credentials to a third party is a security and
          reliability risk we're not comfortable accepting yet. RPA-based
          auto-filing is on our roadmap.
        </HelpParagraph>
      </HelpSection>

      <HelpSection title="Who's the licensed individual on my filings?">
        <HelpParagraph>
          For most NYC DOB filings, the applicant of record is a
          licensed individual — either you (if you hold a GC, plumbing,
          or other applicable license) or a designated filing rep (a
          licensed individual you've authorized to file on your behalf).
        </HelpParagraph>
        <HelpParagraph>
          During onboarding Step 3, you can add filing reps to your
          company. We use those names + license numbers to surface the
          right applicant on each permit's renewal page. You can manage
          filing reps in Settings → Company → Filing reps anytime.
        </HelpParagraph>
        <HelpParagraph>
          Filing rep <HelpKbd>credentials</HelpKbd> (DOB NOW passwords)
          are NEVER stored in LeveLog — that's a hard rule. We only
          surface contact info.
        </HelpParagraph>
      </HelpSection>

      <HelpSection title="Can I add multiple users to my company?">
        <HelpParagraph>
          Multi-user invites are coming in v1.1. For v1, each company
          has a single admin user. If you need a second person at your
          GC to see the LeveLog dashboard today, reach out via the chat
          widget on levelog.com and we'll provision a second login
          manually.
        </HelpParagraph>
      </HelpSection>
    </HelpPageShell>
  );
}
