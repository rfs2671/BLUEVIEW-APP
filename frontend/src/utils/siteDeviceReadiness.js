import { manifestScopes, readManifestList, readSpaceShortfall } from './siteManifestStore';
import { listCachedDocs, cachedDocName, canCacheDocs } from './docCache';

/**
 * IS THIS TABLET READY TO BE TAKEN AT ITS WORD?
 *
 * THE MACHINE. A fixed Android tablet is bolted to a construction gate. It is
 * mains-powered, permanently foregrounded, and nobody prepares it: it fills
 * itself from GET /api/projects/{id}/manifest and is then read — offline, in a
 * cellar, on a scaffold — by a superintendent, and handed to a DOB inspector.
 *
 * THE RULING. An incomplete set is UNUSABLE, not partially usable. "A device
 * that silently holds nine of fifteen plans is worse than one that says it
 * holds none, because the second is a device somebody fixes and the first is a
 * device somebody trusts." Never a short list presented as the list.
 *
 * THE DATA LAYER ALREADY OBEYS IT. siteManifestStore's reader answers
 * complete / partial / absent, and PARTIAL hands back ZERO ROWS on purpose: a
 * fragment returned to a caller reads as a complete short list, and that is the
 * cache shredder the whole store was built to prevent. What did not exist was
 * any screen surfacing it. This module is that surface's model.
 *
 * ── THE AXIS THIS IS NOT ───────────────────────────────────────────────────
 *
 * app/site/logbooks.jsx and app/site/documents.jsx already keep a two-state
 * honesty discipline on `fetchState`: "No Submitted Logs" is a claim about the
 * RECORD, so it may only be made when the SERVER answered; otherwise an
 * <OfflineNotice> says which way the read failed. That discipline is right and
 * nothing here weakens it — but it is a different question. It asks whether
 * the network answered JUST NOW. It says nothing about whether this DEVICE
 * holds the complete approved set. A tablet that fetched perfectly and wrote
 * its own store partway through reports fetchState 'ok' and renders a short
 * list with nothing on screen saying it is short.
 *
 * The two are orthogonal and both can be true at once. The screens carry both.
 *
 * ── THE THREE STATES ───────────────────────────────────────────────────────
 *
 *   SITE_READY_NEVER    No generation this device can still READ committed in
 *                       full. Either half unusable makes the whole device
 *                       unusable — a tablet with every plan and no logbook is
 *                       not a tablet an inspector can be handed. Hard warning,
 *                       and the screens stop making claims about the record.
 *
 *   SITE_READY_CURRENT  A complete set, recent. No chrome at all.
 *
 *   SITE_READY_STALE    A complete set that has not been refreshed. THE OLD
 *                       COMPLETE SET STAYS AUTHORITATIVE AND USABLE; the screen
 *                       shows its AGE.
 *
 * ── WHY STALE KEEPS THE OLD SET, AND WHY THAT IS NOT A LOOPHOLE ────────────
 *
 * The ruling forbids presenting a short list as the list. It does not require
 * throwing away a complete older one — and doing so would make the tablet
 * strictly worse: a superintendent who had fifteen plans this morning would
 * have none this afternoon because a later update dropped a page.
 *
 * THE STORE ACTUALLY RETAINS IT, verified rather than assumed:
 * writeManifestList purges superseded generations ONLY after its own commit
 * lands, and a failed write rolls back only the generation that run wrote. So
 * the previous complete generation survives a later failure and the reader
 * still assembles it whole. siteDeviceReadiness.test.cjs proves that against
 * the real store; if generation cleanup ever changes, that test fails and this
 * decision has to be revisited.
 *
 * ── AN AGE THAT IS NOT RECORDED IS NOT AN AGE OF ZERO ─────────────────────
 *
 * A list committed by a build older than the stamp reads as complete — the
 * store says so deliberately — but nothing on the device says WHEN. A tablet
 * that has been off the network since that build could be months out of date.
 * Reporting it CURRENT would be a claim made out of an absence, which is the
 * exact move this feature exists to refuse, so an unrecorded age is STALE and
 * the copy says the age is not recorded rather than printing a fabricated one.
 * It self-clears on the first complete refresh.
 *
 * ── NO FRACTION THIS DEVICE CANNOT STAND BEHIND ───────────────────────────
 *
 * A count of files on disk is real — one readDirectoryAsync, and the filename
 * already encodes {id}.{version}. A DENOMINATOR is only real when a COMPLETE
 * generation supplies it, so "N of M" is never shown in the NEVER state: there
 * is no M there, only a numerator that would read as reassurance. And the
 * NUMERATOR is only real where the platform can hold files at all, which is
 * why canCacheDocs() gates it rather than trusting an empty set.
 */

/** Nothing has been read yet. NOT a verdict — a fresh mount must not accuse a
 *  healthy tablet on first paint. */
export const SITE_READY_UNKNOWN = 'unknown';
/** No complete set this device can read. It is not ready to leave signal. */
export const SITE_READY_NEVER = 'never';
/** A complete set, refreshed recently. Normal operation. */
export const SITE_READY_CURRENT = 'current';
/** A complete set that has not been refreshed. Still authoritative, ageing. */
export const SITE_READY_STALE = 'stale';
/**
 * A complete LIST, and the device has stopped filling it because there is no
 * room. Terminal until somebody frees space.
 *
 * ITS WHOLE REASON FOR EXISTING IS TO NOT BE `filling`. Before it, a tablet
 * that had refused the fill reported "83 of 87 … Still saving this project to
 * the tablet" for ever, because `filling` is computed from a directory read
 * and a missing file looks identical whether it is on its way or will never
 * come. That told a superintendent to wait for something that was not coming.
 * NOT YET and NEVER are different facts and this is the second one.
 */
export const SITE_READY_NO_SPACE = 'no-space';

/**
 * How old a complete set may be before the screens say so.
 *
 * The store polls every five minutes on a mains-powered, permanently
 * foregrounded tablet and rewrites its commit on every complete walk, so a
 * healthy device is minutes old, never hours. A day is therefore not a tight
 * threshold — it is a generous one, chosen so the banner means "something has
 * been wrong since yesterday" and not "the wifi blinked", because a warning
 * that cries wolf at a gate is a warning people learn to walk past.
 */
export const STALE_AFTER_MS = 24 * 60 * 60 * 1000;

// The tablet renders PDFs and nothing else, so only PDFs can be part of a
// promise about what it holds. Matches the store's own DOWNLOADABLE set.
const HOLDABLE = new Set(['pdf']);

const isComplete = (r) => !!r && r.state === 'complete';

/**
 * How long ago, in words a superintendent standing at a gate can act on.
 * Deliberately coarse: nobody decides anything differently at 51 hours than at
 * 49, and three significant figures would read as machine output.
 */
/**
 * A size in words somebody can act on, at the same coarseness as agePhrase.
 *
 * "1.2 GB" and "340 MB" are decisions a person can make about a device;
 * "1,283,457,024 bytes" is machine output on an inspector's screen. Rounds UP,
 * because this number tells someone how much to free and rounding down would
 * send them back for a second go.
 */
export function bytesPhrase(n) {
  const b = Number(n);
  if (!Number.isFinite(b) || b <= 0) return null;
  const MB = 1024 * 1024;
  const GB = 1024 * MB;
  if (b >= GB) {
    const gb = Math.ceil((b / GB) * 10) / 10;
    return `${gb} GB`;
  }
  return `${Math.max(1, Math.ceil(b / MB))} MB`;
}

export function agePhrase(ms) {
  const n = Number(ms);
  if (!Number.isFinite(n) || n < 0) return null;
  const hours = Math.floor(n / 3600000);
  if (hours < 1) return 'less than an hour ago';
  if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`;
  const days = Math.floor(hours / 24);
  return `${days} day${days === 1 ? '' : 's'} ago`;
}

/**
 * The readiness of one device, from what the store holds and what is on disk.
 *
 * Pure, and injected with both — no filesystem and no storage — so every state
 * below is reachable in a test without a device.
 *
 *   files / logbooks   readManifestList() results, or null when not read yet.
 *   cachedNames        the Set from listCachedDocs(), or NULL where this
 *                      platform cannot hold files at all. Null withholds the
 *                      fraction; an empty Set is a measured zero.
 *   shortfall          readSpaceShortfall() — {needed, free, at} when the last
 *                      fill was REFUSED for room, else null. Injected for the
 *                      same reason as the other two: it is the one fact a
 *                      directory read cannot produce, because a missing file
 *                      looks the same whether it is coming or never will.
 */
export function readinessFrom({
  files, logbooks, cachedNames, shortfall, now, staleAfterMs,
} = {}) {
  const at = Number.isFinite(now) ? now : Date.now();
  const limit = Number.isFinite(staleAfterMs) ? staleAfterMs : STALE_AFTER_MS;

  const base = {
    state: SITE_READY_UNKNOWN,
    at: null,
    ageMs: null,
    ageKnown: false,
    rowsUsable: false,
    saved: null,
    expected: null,
    countsKnown: false,
    filling: false,
    reason: null,
  };

  // Nothing read yet. Say nothing.
  if (!files || !logbooks) return base;

  // EITHER HALF UNUSABLE MAKES THE DEVICE UNUSABLE. The plans and the logbooks
  // are two scopes but one promise: an inspector handed a tablet with every
  // drawing and no submitted logs has been handed a tablet that cannot answer
  // him. And no fraction — an absent list supplies no denominator.
  if (!isComplete(files) || !isComplete(logbooks)) {
    return {
      ...base,
      state: SITE_READY_NEVER,
      reason: (isComplete(files) ? logbooks.reason : files.reason) || 'incomplete',
    };
  }

  // The device is only as current as its STALEST half.
  const stamps = [files.at, logbooks.at];
  const ageKnown = stamps.every((v) => Number.isFinite(v));
  const oldest = ageKnown ? Math.min(...stamps) : null;
  // A clock that moved backwards must not produce a negative age.
  const ageMs = ageKnown ? Math.max(0, at - oldest) : null;

  // What this device is supposed to hold, and what it actually has. The
  // denominator comes from a complete generation, so it is one we can stand
  // behind; the numerator is a directory read, or withheld entirely.
  const wanted = [
    ...files.rows.filter((r) => HOLDABLE.has(String((r && r.e) || '').toLowerCase())),
    ...logbooks.rows,          // a logbook is rendered to PDF on request
  ];
  const countsKnown = cachedNames instanceof Set;
  const expected = wanted.length;
  const saved = countsKnown
    ? wanted.filter((r) => cachedNames.has(cachedDocName(r.id, r.cache_version))).length
    : null;

  const out = {
    ...base,
    state: (!ageKnown || ageMs > limit) ? SITE_READY_STALE : SITE_READY_CURRENT,
    at: oldest,
    ageMs,
    ageKnown,
    // THE OLD COMPLETE SET REMAINS AUTHORITATIVE. Stale is an age, not a fault.
    rowsUsable: true,
    saved,
    expected: countsKnown ? expected : null,
    countsKnown,
    filling: countsKnown && expected > 0 && saved < expected,
    reason: ageKnown ? null : 'age-not-recorded',
  };

  // ── NOT YET, OR NEVER ────────────────────────────────────────────────────
  //
  // Applied LAST, over a state that is otherwise complete, because that is
  // exactly the situation it describes: the list is whole and trustworthy, and
  // the FILES behind it have stopped arriving. It converts the advisory into a
  // verdict rather than adding a fourth thing to read.
  //
  // ONLY WHEN THE DEVICE IS ACTUALLY SHORT. A recorded refusal with everything
  // on disk is a stale note — the fill was refused, then space was freed and
  // the files landed some other way, or the manifest shrank. Reporting no-space
  // there would accuse a tablet that is complete, which is the failure this
  // whole module refuses in the other direction. The next successful run clears
  // the record; this makes sure a lingering one cannot lie in the meantime.
  //
  // IT OUTRANKS STALE, DELIBERATELY. A stale set self-clears the moment the
  // tablet sees Wi-Fi; this one does not clear until a person does something.
  // When both are true the actionable one is the one to print.
  if (shortfall && out.filling) {
    return {
      ...out,
      state: SITE_READY_NO_SPACE,
      // NOT `filling`. A device that has stopped is not filling, and every
      // reader that asks this question is asking whether to wait.
      filling: false,
      shortBytes: Math.max(0, Number(shortfall.needed) - Number(shortfall.free)) || null,
      neededBytes: Number(shortfall.needed) || null,
      freeBytes: Number(shortfall.free) || null,
      reason: 'no-space',
    };
  }

  return out;
}

/** Read the device's readiness for one project. */
export async function readSiteReadiness(projectId, opts = {}) {
  if (!projectId) return readinessFrom({});
  const scopes = manifestScopes(projectId);
  const [files, logbooks, shortfall] = await Promise.all([
    readManifestList(scopes.files),
    readManifestList(scopes.logbooks),
    readSpaceShortfall(projectId),
  ]);
  const cachedNames = canCacheDocs() ? await listCachedDocs() : null;
  return readinessFrom({ files, logbooks, cachedNames, shortfall, now: opts.now });
}

/* ══════════════════════════════════════════════════════════════════════════
 * THE WORDING — the deliverable, not decoration.
 *
 * READ BY: a superintendent at a gate, wearing gloves, deciding whether to
 * walk into a cellar with this tablet. And possibly by a DOB inspector who has
 * just been handed it.
 *
 * SO IT MAY NOT: say "sync failed", or name any part of the machine — no
 * manifest, no cache, no generation, no server, no endpoint. Those words tell
 * the reader that something in a program went wrong, which is neither the fact
 * he needs nor a fact he can act on, and on the inspector's screen it reads as
 * a system that is not in control of its own records.
 *
 * IT MUST: say the device cannot be relied on away from signal; say that
 * records may be missing WITHOUT SHOWING AS MISSING, which is the one thing
 * about this failure a person cannot work out by looking; and say what to do.
 *
 * Returns null when there is nothing to say — which is most of the time, and
 * is the point: a banner that is always there is furniture.
 * ═════════════════════════════════════════════════════════════════════════ */
export function describeReadiness(readiness) {
  const r = readiness || {};

  if (r.state === SITE_READY_NEVER) {
    return {
      tone: 'critical',
      heading: 'This tablet is not ready to use offline',
      body: 'It has not finished downloading this project’s plans, documents and '
        + 'logbooks. Records may be missing without showing as missing. Keep it on '
        + 'Wi-Fi until this message clears.',
      detail: 'If this message is still here tomorrow, tell the office before anyone '
        + 'relies on this tablet.',
    };
  }

  // ── THE TABLET HAS STOPPED, AND ONLY A PERSON CAN RESTART IT ────────────
  //
  // CRITICAL, not attention, and above STALE. Every other state on this screen
  // either fixes itself or is about age; this one waits for a human, and until
  // that human acts the tablet is missing drawings it will never fetch.
  //
  // IT SAYS THE NUMBER TO FREE. "Not enough space" sends someone to a settings
  // screen to guess; "needs about 340 MB more" is a decision. Rounded up,
  // because rounding down sends them back for a second go.
  //
  // NO PART OF THE MACHINE IS NAMED, per this module's rule — no manifest, no
  // cache, no sync. "It has stopped saving" is the fact; "the manifest run was
  // refused" is machine output on an inspector's screen.
  if (r.state === SITE_READY_NO_SPACE) {
    const short = bytesPhrase(r.shortBytes);
    const held = r.countsKnown && r.expected > 0
      ? ` ${r.saved} of ${r.expected} records are on it.`
      : '';
    return {
      tone: 'critical',
      heading: 'This tablet is full and has stopped saving records',
      body: 'Some of this project’s plans, documents and logbooks are not on it '
        + 'and will not download until space is freed. They will not open once '
        + 'the signal drops, and they will not show as missing.'
        + held,
      detail: short
        ? `Free about ${short} on this tablet, then keep it on Wi-Fi. Tell the office if you cannot.`
        : 'Free space on this tablet, then keep it on Wi-Fi. Tell the office if you cannot.',
    };
  }

  if (r.state === SITE_READY_STALE) {
    const age = r.ageKnown ? agePhrase(r.ageMs) : null;
    // The denominator here comes from a COMPLETE generation, so it is one this
    // device can stand behind. Only said when it is short of it — "15 of 15"
    // on a warning banner is noise.
    const held = r.countsKnown && r.expected > 0 && r.saved < r.expected
      ? ` ${r.saved} of ${r.expected} records are on this tablet.`
      : '';
    return {
      tone: 'attention',
      heading: 'These records may be out of date',
      body: 'This tablet holds a complete set of this project’s plans, documents and '
        + 'logbooks, but it has not been able to pick up newer ones. Anything added or '
        + 'withdrawn since then is not on it. Put it back on Wi-Fi to bring it up to date.',
      detail: age
        ? `Last complete update: ${age}.${held}`
        : `Last complete update: not recorded on this tablet.${held}`,
    };
  }

  // A COMPLETE AND CURRENT LIST OF FILES THAT ARE NOT ALL HERE YET.
  //
  // The list is whole, so the denominator is one we can stand behind — and a
  // tablet whose list is whole and whose FILES are not is still a tablet that
  // will not open a drawing in a cellar. That is worth a line, and only a line:
  // it is the ordinary state of a device that is filling itself correctly, so
  // it is an advisory, not an alarm.
  if (r.state === SITE_READY_CURRENT && r.filling) {
    return {
      tone: 'attention',
      heading: 'Still saving this project to the tablet',
      body: `${r.saved} of ${r.expected} plans, documents and logbooks are on this `
        + 'tablet so far. The rest need Wi-Fi. Anything not yet saved will not open '
        + 'once the signal drops.',
      detail: null,
    };
  }

  // CURRENT and full, or nothing read yet. Say nothing.
  return null;
}

export default {
  SITE_READY_UNKNOWN,
  SITE_READY_NEVER,
  SITE_READY_CURRENT,
  SITE_READY_STALE,
  SITE_READY_NO_SPACE,
  STALE_AFTER_MS,
  agePhrase,
  bytesPhrase,
  readinessFrom,
  readSiteReadiness,
  describeReadiness,
};
