/**
 * Phase B4 — /help/permit-renewal.
 *
 * The manual-filing renewal flow LeveLog assists with: status
 * indicators, PW2 copy values, eligibility checks.
 */

import React from 'react';
import HelpPageShell, {
  HelpSection,
  HelpParagraph,
  HelpBullets,
  HelpKbd,
} from '../../src/components/HelpPageShell';

export default function HelpPermitRenewal() {
  return (
    <HelpPageShell title="Permit renewal">
      <HelpSection title="What renewal looks like in LeveLog">
        <HelpParagraph>
          When a permit on your project approaches expiration, it
          surfaces in two places:
        </HelpParagraph>
        <HelpBullets
          items={[
            "The Activity feed shows a permit_expired (or permit_renewed) signal.",
            "The Permit Renewals page (Quick Actions tile on the project hub) lists every expiring permit with a status badge and a tap-to-expand action panel.",
          ]}
        />
        <HelpParagraph>
          Renewal happens manually on DOB NOW. LeveLog assists by
          surfacing eligibility, the right values to copy into the
          form, and a deep-link straight to the DOB NOW filing.
        </HelpParagraph>
      </HelpSection>

      <HelpSection title="Manual filing on DOB NOW">
        <HelpParagraph>
          The renewal flow is:
        </HelpParagraph>
        <HelpBullets
          items={[
            "Open the Permit Renewals page for your project.",
            "Tap the expiring permit. The action panel expands to show eligibility and copy-able PW2 values.",
            "If eligible: tap the deep-link to open DOB NOW. Log in with your NYC.ID, paste the PW2 values into the renewal form, sign, and pay the DOB fee.",
            "Return to LeveLog. The next 15-minute DOB poll picks up the new filing and the permit's status updates automatically.",
          ]}
        />
      </HelpSection>

      <HelpSection title="LeveLog provides PW2 values to copy">
        <HelpParagraph>
          The renewal action panel surfaces every value DOB NOW asks
          for, formatted to copy directly:
        </HelpParagraph>
        <HelpBullets
          items={[
            "Job number — the BIS or DOB NOW job that the permit attached to.",
            "Work type — general construction, plumbing, sprinkler, etc.",
            "Applicant name + license number — pulled from your filing reps roster (Settings → Company).",
            "Effective expiration date — the renewed permit's new expiration after applying §1.1 ceilings.",
            "Renewal fee — the DOB-determined fee for this permit type.",
            "Any blocking reasons — surfaced if eligibility fails.",
          ]}
        />
        <HelpParagraph>
          Tap any field to copy it to your clipboard. We'll show a
          toast confirming the copy.
        </HelpParagraph>
      </HelpSection>

      <HelpSection title="Renewal status indicators">
        <HelpParagraph>
          Each permit on the renewals page carries a status badge:
        </HelpParagraph>
        <HelpBullets
          items={[
            "Renewal Ready — eligible for renewal. Tap to open DOB NOW with the values pre-displayed.",
            "Insurance Required — your General Liability or Workers' Comp expiration isn't entered yet. Open Settings → Insurance to enter your COI dates, then re-check.",
            "Insurance Update Required — your insurance is on file but expired or expiring. Update it on file before renewal can proceed.",
            "License Issue — the linked GC license has a status problem (suspended, expired, lapsed). Resolve at the licensing authority before renewal.",
            "Manual Renewal — a renewal that hits DOB's 1-year ceiling or another rule that prevents auto-extend. Manual filing required; the panel shows what to do.",
            "Permit Lapsed — the permit expired more than 60 days ago. Renewal isn't available; you may need to re-file via Post Approval Amendment.",
            "Awaiting GC — LeveLog prepared a renewal draft on DOB NOW; you need to log in, sign, and pay.",
            "Completed — the permit was successfully renewed. New expiration shown.",
          ]}
        />
      </HelpSection>

      <HelpSection title="Eligibility checks">
        <HelpParagraph>
          Before opening DOB NOW, LeveLog confirms the renewal can
          actually proceed. We check:
        </HelpParagraph>
        <HelpBullets
          items={[
            "GC license is current and not suspended.",
            "General Liability insurance is current.",
            "Workers' Comp insurance is current.",
            "Disability insurance is current.",
            "The permit hasn't hit DOB's 1-year ceiling.",
            "The permit isn't BIS-legacy (those require a Post Approval Amendment instead).",
            "No outstanding violations block the renewal.",
          ]}
        />
        <HelpParagraph>
          If any check fails, the action panel surfaces the blocking
          reason instead of the DOB NOW deep-link — so you know what
          to fix before clicking through.
        </HelpParagraph>
      </HelpSection>
    </HelpPageShell>
  );
}
