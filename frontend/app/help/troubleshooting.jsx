/**
 * Phase B4 — /help/troubleshooting.
 *
 * The 6 most common "something looks wrong" scenarios with
 * step-by-step recovery instructions.
 */

import React from 'react';
import HelpPageShell, {
  HelpSection,
  HelpParagraph,
  HelpBullets,
  HelpKbd,
} from '../../src/components/HelpPageShell';

export default function HelpTroubleshooting() {
  return (
    <HelpPageShell title="Troubleshooting">
      <HelpSection title="I'm not seeing signals">
        <HelpParagraph>
          A few things to check, in order:
        </HelpParagraph>
        <HelpBullets
          items={[
            "Is the project less than 15 minutes old? The first poll runs every 15 minutes; if you just added the project, wait one cycle.",
            "Open the project's DOB Compliance page (gear icon). Confirm \"Enable DOB Tracking\" is on. If it's off, no DOB data will pull for the project.",
            "Check the BIN. If the BIN field shows blank or a placeholder (e.g. 1000000, 2000000), GeoSearch couldn't auto-resolve from the address. Open the gear icon and enter the correct BIN manually — find it at a810-bisweb.nyc.gov.",
            "Confirm the address is well-formed. \"123 Main St, Brooklyn, NY 11201\" works; \"123 Main\" alone may not.",
            "If the project is in another borough or city, no DOB data will surface — LeveLog only monitors NYC.",
          ]}
        />
      </HelpSection>

      <HelpSection title="I'm getting too many emails">
        <HelpParagraph>See the FAQ entry on reducing email volume:</HelpParagraph>
        <HelpBullets
          items={[
            "Settings → Notifications → switch to \"Critical only\" preset.",
            "Or use Per-project overrides to silence noisy projects.",
            "Or use Advanced to disable specific signal_kind emails.",
            "Daily-digest deliveries arrive at 7am ET — that’s normal, not a flood.",
          ]}
        />
      </HelpSection>

      <HelpSection title="I'm not getting emails (and I expect to)">
        <HelpParagraph>
          Run through this checklist:
        </HelpParagraph>
        <HelpBullets
          items={[
            "Check your spam / junk folder. Add the LeveLog sender to your address book.",
            "Confirm your preset isn't accidentally on \"Critical only\" — many warnings stay in the feed under that preset.",
            "Check Settings → Notifications. If the page shows you're on \"Critical only\" but you expected \"Standard\", switch and save.",
            "If LeveLog has a kill-switch active (an internal incident response toggle), no emails go out for any user. Reach out via the chat widget — we'll let you know if a kill-switch is currently on.",
            "Email-throttling: the same record won't email you twice in 24 hours. If DOB re-pulled an existing violation, you won't get a duplicate notification.",
          ]}
        />
      </HelpSection>

      <HelpSection title="Activity feed is empty">
        <HelpParagraph>
          The feed shows "We're monitoring DOB. Your first signals will
          appear within 15 minutes." in two situations:
        </HelpParagraph>
        <HelpBullets
          items={[
            "Brand-new project that hasn't completed its first 15-minute poll. Wait a cycle.",
            "Project where DOB has zero historical records — usually because the address is wrong or the project is outside NYC. Re-check the address; manually enter the BIN if you have it.",
          ]}
        />
        <HelpParagraph>
          If the feed has been empty for over an hour and you've
          confirmed the BIN + address, reach out via the chat widget —
          we may need to manually trigger a sync.
        </HelpParagraph>
      </HelpSection>

      <HelpSection title="Wrong project address">
        <HelpParagraph>
          Open the project detail page → tap the project name to edit
          → fix the address → save. The next 15-minute DOB poll
          re-resolves the BIN and pulls the correct record set.
        </HelpParagraph>
        <HelpParagraph>
          If the BIN was already auto-resolved to the wrong building,
          open the DOB Compliance page (gear icon) and edit the BIN
          field directly.
        </HelpParagraph>
      </HelpSection>

      <HelpSection title='Why does the activity feed show "(none)" signal_kind for some items?'>
        <HelpParagraph>
          Some legacy DOB records — especially BIS-era permits filed
          before the DOB NOW migration — don't map cleanly to one of
          our 26 signal_kinds. Rather than drop them, we surface them
          with a <HelpKbd>(none)</HelpKbd> kind label so you can still
          see the underlying record. They appear in the feed but won't
          trigger preset-based notifications.
        </HelpParagraph>
        <HelpParagraph>
          This is rare; usually it indicates a record type we haven't
          seen yet. Reach out and we'll add proper signal_kind support
          in a future release.
        </HelpParagraph>
      </HelpSection>
    </HelpPageShell>
  );
}
