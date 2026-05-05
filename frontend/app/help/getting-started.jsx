/**
 * Phase B4 — /help/getting-started.
 *
 * Plain-English overview of what LeveLog monitors, refresh
 * cadence, first-15-minute expectations, and the manual filing
 * model.
 *
 * Source-of-truth references:
 *   • 8 family groups + 26 signal_kinds — pinned to
 *     frontend/src/utils/signalKindHelp.js (B3) which mirrors
 *     backend lib/notification_preferences.ALL_DEFAULT_SIGNAL_KINDS.
 *   • DOB poll cadence (15 min) — server.py scheduler.
 *   • 311 poll cadence (30 min) — server.py 311 watcher.
 */

import React from 'react';
import HelpPageShell, {
  HelpSection,
  HelpParagraph,
  HelpBullets,
  HelpKbd,
} from '../../src/components/HelpPageShell';

const FAMILY_OVERVIEW = [
  {
    label: 'Permits',
    body:
      "Work permits issued by DOB for your project. Sub-permits like plumbing, sprinkler, and general construction appear as separate rows.",
  },
  {
    label: 'Job Filings',
    body:
      "DOB applications for the work you plan to do. Each filing moves through review (pending → approved or disapproved); permits can only issue against an approved filing.",
  },
  {
    label: 'Violations',
    body:
      "DOB and ECB violations issued against your project. Each carries a fine and (usually) a required remedy by a deadline.",
  },
  {
    label: 'Stop Work Orders',
    body:
      "Orders that halt some or all work on your site until the underlying issue is resolved. FULL stops everything; PARTIAL stops only the cited scope.",
  },
  {
    label: 'Complaints',
    body:
      "DOB and 311 complaints about your project. DOB inspects most complaints and decides whether to issue a violation.",
  },
  {
    label: 'Inspections',
    body:
      "DOB inspection events — scheduled, passed, failed, and final signoff. Failed inspections must be remedied before re-inspection.",
  },
  {
    label: 'Compliance',
    body:
      "Periodic compliance filings: Facade (FISP / Local Law 11), boiler, elevator inspections, and Certificate of Occupancy applications.",
  },
  {
    label: 'License',
    body:
      "License renewal reminders — GC, plumbing, and other trade licenses tied to your filings.",
  },
];

export default function HelpGettingStarted() {
  return (
    <HelpPageShell title="Getting started">
      <HelpSection title="What does LeveLog monitor?">
        <HelpParagraph>
          LeveLog watches NYC DOB activity for every project you add, plus
          related city data sources (311, ECB, BIS). New events surface in
          your Activity feed, and critical items can trigger an email per
          your notification preferences.
        </HelpParagraph>
        <HelpParagraph>
          We track signals across 8 categories — 26 distinct event types
          in total:
        </HelpParagraph>
        {FAMILY_OVERVIEW.map((fam) => (
          <HelpSection key={fam.label} title={fam.label}>
            <HelpParagraph>{fam.body}</HelpParagraph>
          </HelpSection>
        ))}
      </HelpSection>

      <HelpSection title="How often is data refreshed?">
        <HelpParagraph>
          Different DOB datasets refresh on different cadences. We've
          tuned LeveLog to keep up without over-polling:
        </HelpParagraph>
        <HelpBullets
          items={[
            'NYC DOB datasets (permits, filings, violations, inspections, ECB violations, stop-work orders): every 15 minutes.',
            '311 service requests: every 30 minutes — 311 routes construction-related complaints to DOB or another agency for follow-up.',
            'BIS legacy permits: queried on demand during initial scans and renewal preparation; the daily DOB sync keeps them current too.',
            'GC license + insurance status (BIS): refreshed when you create / link a company, and re-checked daily.',
          ]}
        />
      </HelpSection>

      <HelpSection title="First steps">
        <HelpBullets
          items={[
            'Sign up at levelog.com and accept the email confirmation.',
            "On first login, you'll be guided through a 4-step onboarding flow: tell us about your company, add your first project, optionally add filing reps, and pick a notification preset.",
            'You can skip any step and revisit it later in Settings — no lock-in.',
            'Once your first project is added, our 15-minute DOB poller picks it up automatically. No manual sync needed.',
          ]}
        />
      </HelpSection>

      <HelpSection title="Expected timeline">
        <HelpParagraph>
          What to expect during your first day:
        </HelpParagraph>
        <HelpBullets
          items={[
            'Within 15 minutes of project add: initial scan completes. The dashboard shows a banner with a count of permits, violations, and inspections found.',
            'Within 24 hours: 311 complaints (if any) backfill via the 30-min watcher.',
            "Within 24 hours: BIS legacy permits surface if your project has filings older than the DOB NOW migration cutoff.",
            "Day 2 onward: only NEW events trigger notifications. The first scan's historical backlog is silent — you won't get a flood of emails about old filings.",
          ]}
        />
      </HelpSection>

      <HelpSection title="What about my filing reps?">
        <HelpParagraph>
          LeveLog does NOT file paperwork on your behalf. Filings happen
          manually on DOB NOW (a810-dobnow.nyc.gov) — you, or a licensed
          filing rep on your team, log in with your NYC.ID and complete
          the filing yourself.
        </HelpParagraph>
        <HelpParagraph>
          We collect filing rep contact info during onboarding (Step 3)
          so when a permit needs renewal, the Activity feed and renewal
          page can surface the right name + license number for the
          applicant. No credentials are stored — DOB NOW logins stay on
          your browser.
        </HelpParagraph>
        <HelpParagraph>
          See the <HelpKbd>Permit renewal</HelpKbd> guide for the manual
          renewal flow LeveLog assists.
        </HelpParagraph>
      </HelpSection>
    </HelpPageShell>
  );
}
