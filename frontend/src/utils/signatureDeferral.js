/**
 * THREE STATES, NOT TWO: what a filed record says about one man's mark.
 *
 * ── WHY THIS IS ITS OWN MODULE, AND IT IS NOT TIDINESS ─────────────────────
 *
 * NOTHING IS IMPORTED HERE. Not expo-file-system, not AsyncStorage, not the
 * API client — this file is pure, and that is what lets the two surfaces that
 * have to agree about a signature both load it FOR REAL rather than against a
 * stub:
 *
 *   siteLogbookHistory.js        the transport. Asks for `view=text`, fetches
 *                                the marks, splices them, keeps them on disk.
 *                                Re-exports everything here, so every existing
 *                                import of it is unchanged.
 *   app/site/logbooks.jsx        the screen a DOB inspector reads. Its
 *                                renderers are sliced out and executed by
 *                                logbookViewRenderers.test.cjs, which cannot
 *                                require a module that touches the filesystem
 *                                — so with the protocol living in the
 *                                transport module, the one test that RUNS
 *                                those renderers had to stub the function that
 *                                decides whether a man signed.
 *
 * A STUBBED `signatureMark` IS THE WHOLE DEFECT WEARING THE NAME OF THE FIX.
 * That test is the only thing that executes the pre-shift roster, and the
 * answer it checks is exactly the one that must not be guessed.
 *
 * ── THE DEFECT THIS PROTOCOL EXISTS FOR, MEASURED 2026-10-08 ───────────────
 *
 * On the one project with a filed history — the one the gate tablet is bolted
 * to, 339 submitted records over 43 dates — signature images are 11,233,990 of
 * 17,080,794 stored bytes, 65.8%. (The other four projects hold 53,100 between
 * them; the scope is named because the first version of this note said "every
 * project" and meant this one.)
 *
 * Measured THROUGH THE HANDLER, a day costs 336,385 bytes at the median and
 * 1,132,800 at the heaviest; served this way the same days are 73,733 and
 * 592,372.
 *
 * But the pre-shift renderer keyed TWO blocks off one field:
 *
 *     workers.some(w => w.worker_signature)    -> draw the signature images
 *     workers.some(w => !w.worker_signature)   -> list those names as UNSIGNED
 *
 * so a payload that merely OMITTED the mark would have told an inspector that
 * every one of the 505 men who signed at the kiosk had NOT signed. A false
 * statement on a legal record, and worse than a slow screen. Hence three
 * states, and hence a single function that answers which one.
 */

/**
 * THE ONE DEFINITION OF THE FLAG, AND WHY IT LIVES IN THIS MODULE.
 *
 * `server.py`'s `SIGNATURE_DEFERRED_SUFFIX` is the other half of this string,
 * and `test_images_load_when_the_sheet_is_opened.py` holds the two equal by
 * reading this declaration's own source.
 *
 * ONE DECLARATION, READ BY BOTH SURFACES. `siteLogbookHistory.js` asks for
 * `view=text` and splices what comes back; `app/site/logbooks.jsx` renders the
 * three states. A screen that spelled the suffix itself is how a renderer
 * comes to look for a key the transport stopped sending — which on this screen
 * means telling a DOB inspector that a man who signed did not.
 */
export const SIG_DEFERRED_SUFFIX = '_deferred';

/**
 * THE FIELDS A SIGNATURE CAN BE STORED UNDER, per site, in the renderer's own
 * precedence.
 *
 * `worker_signature` FIRST, because that is what the roster actually stores —
 * all 583 marks in production — and it is the order
 * `frontend/app/site/logbooks.jsx` and `backend/lib/legal_render/primitives.py`
 * already read them in. Two keys for an attendee because `renderToolboxTalk`
 * reads two.
 */
export const SIG_FIELDS = {
  worker: ['worker_signature'],
  attendee: ['worker_signature', 'signature'],
  acknowledgment: ['worker_signature'],
};

/**
 * WHAT THIS RECORD SAYS ABOUT ONE MAN'S MARK. Three answers, never two.
 *
 *   {value}            he signed, and these are the bytes. Draw them.
 *   {deferred: true}   he signed; the bytes are a second request. Say SO —
 *                      distinctly from both of the others.
 *   {}                 he did not sign.
 *
 * THE MIDDLE ONE IS WHY THIS FUNCTION EXISTS. Every reader on this screen used
 * to infer signed-ness from the PRESENCE of the image, so a payload without
 * the image told a DOB inspector that every worker who signed at the kiosk had
 * not signed. That is a false statement on a legal record. Readers call this
 * instead of testing the field, and `siteSignatureDeferral.test.cjs` derives
 * the reader census from logbooks.jsx's own source so a fourth site cannot be
 * added that tests the field directly.
 *
 * THE VALUE WINS OVER THE FLAG when both are somehow present. A record whose
 * images have been spliced back in is the state the renderer is best at, and
 * preferring the flag there would hide an image the device is holding.
 */
export function signatureMark(holder, fields) {
  const h = (holder && typeof holder === 'object') ? holder : {};
  const keys = Array.isArray(fields) ? fields : SIG_FIELDS.worker;
  for (const f of keys) {
    if (h[f]) return { value: h[f], deferred: false, field: f };
  }
  for (const f of keys) {
    if (h[`${f}${SIG_DEFERRED_SUFFIX}`] === true) {
      return { value: null, deferred: true, field: f };
    }
  }
  return { value: null, deferred: false, field: null };
}

/**
 * Every address this record is still owed an image for, as dotted paths.
 *
 * DERIVED FROM THE BODY, NOT FROM A COUNT THE SERVER PROMISED. A full-document
 * body — what a server that predates `view=text` serves — carries no flags, so
 * this is EMPTY and nothing is fetched, which is exactly right: the images are
 * already in hand. The deploy gap needs no branch of its own.
 *
 * The path spelling is the server's: `data.workers.3.worker_signature`,
 * `data.attendees.0.signature`, `data.worker_signature`. Sites and precedence
 * come from SIG_FIELDS, so this walk and the server's
 * `_signature_image_paths` describe the same four sites.
 */
export function deferredSignaturePaths(log) {
  const out = [];
  const data = (log && log.data && typeof log.data === 'object') ? log.data : null;
  if (!data) return out;
  const flagged = (holder, field) => (
    holder && typeof holder === 'object'
      && holder[`${field}${SIG_DEFERRED_SUFFIX}`] === true
  );
  for (const [listName, fields] of [['workers', SIG_FIELDS.worker],
                                    ['attendees', SIG_FIELDS.attendee]]) {
    const rows = data[listName];
    if (!Array.isArray(rows)) continue;
    rows.forEach((holder, i) => {
      for (const field of fields) {
        if (flagged(holder, field)) out.push(`data.${listName}.${i}.${field}`);
      }
    });
  }
  for (const field of SIG_FIELDS.acknowledgment) {
    if (flagged(data, field)) out.push(`data.${field}`);
  }
  return out;
}

/** Whether ANY record in this day is still owed an image. */
/**
 * Every photo thumbnail `photos=deferred` left out of one record.
 *
 * `data.activities[ai].photos[pi].thumb_base64_deferred === true` means the
 * ~400px inline copy exists on the stored record and was held back from the
 * day download; it is fetched with the record's signature marks
 * (`include=photos`) and stored on disk with them. NOT a claim about the photo:
 * until it arrives the reader falls through to the served URL, exactly as it
 * does for a photo that never had an inline copy.
 */
export function deferredPhotoPaths(log) {
  const out = [];
  const data = (log && log.data && typeof log.data === 'object') ? log.data : null;
  const acts = data && Array.isArray(data.activities) ? data.activities : null;
  if (!acts) return out;
  acts.forEach((act, ai) => {
    const photos = act && Array.isArray(act.photos) ? act.photos : null;
    if (!photos) return;
    photos.forEach((p, pi) => {
      if (p && typeof p === 'object'
          && p[`thumb_base64${SIG_DEFERRED_SUFFIX}`] === true) {
        out.push(`data.activities.${ai}.photos.${pi}.thumb_base64`);
      }
    });
  });
  return out;
}

/** Everything a record still owes this device: signature marks and photo thumbnails. */
export function deferredImagePaths(log) {
  return deferredSignaturePaths(log).concat(deferredPhotoPaths(log));
}

/** Does any record of the day owe an image of either kind? */
export function dayHasDeferredImages(logs) {
  return (Array.isArray(logs) ? logs : [])
    .some((l) => deferredImagePaths(l).length > 0);
}

export function dayHasDeferredSignatures(logs) {
  return (Array.isArray(logs) ? logs : [])
    .some((l) => deferredSignaturePaths(l).length > 0);
}

/**
 * The record with its images put back where the flags are, and the flags gone.
 *
 * SPLICED BACK RATHER THAN PASSED ALONGSIDE, AND THAT IS THE SAFETY ARGUMENT.
 * Once the bytes are in hand the record is byte-for-byte the shape this screen
 * has always rendered, so the drawing code for a loaded signature is the code
 * that was already there and was already right. Only the DEFERRED branch is
 * new. Handing the renderers a second map to consult would have made all three
 * states new code at once, on the one screen a DOB inspector reads.
 *
 * THE FLAG IS DELETED WITH THE SPLICE, so nothing can draw the image and the
 * "not yet loaded" notice about the same mark.
 *
 * COPY-ON-WRITE, like the server's half: a day holds 592 KB of photo
 * thumbnails this never touches, and a record with nothing to splice is
 * returned unchanged, identity included.
 */
export function applySignatureImages(log, images) {
  const map = (images && typeof images === 'object') ? images : null;
  if (!map) return log;
  const paths = Object.keys(map).filter((p) => map[p]);
  if (paths.length === 0) return log;
  const data = (log && log.data && typeof log.data === 'object') ? log.data : null;
  if (!data) return log;

  const out = { ...log, data: { ...data } };
  const copied = {};
  let touched = false;
  for (const path of paths) {
    const parts = String(path).split('.');
    if (parts.length === 2 && parts[0] === 'data') {
      const field = parts[1];
      if (!(`${field}${SIG_DEFERRED_SUFFIX}` in out.data)) continue;
      delete out.data[`${field}${SIG_DEFERRED_SUFFIX}`];
      out.data[field] = map[path];
      touched = true;
      continue;
    }
    // A PHOTO THUMBNAIL: data.activities.<ai>.photos.<pi>.thumb_base64.
    if (parts.length === 6 && parts[0] === 'data' && parts[1] === 'activities'
        && parts[3] === 'photos') {
      const ai = Number(parts[2]);
      const pi = Number(parts[4]);
      const field = parts[5];
      const acts = out.data.activities;
      if (!Array.isArray(acts) || !Number.isInteger(ai) || ai < 0 || ai >= acts.length) continue;
      if (!copied.activities) {
        copied.activities = acts.slice();
        out.data.activities = copied.activities;
      }
      const act = { ...(copied.activities[ai] || {}) };
      const photos = Array.isArray(act.photos) ? act.photos.slice() : null;
      if (!photos || !Number.isInteger(pi) || pi < 0 || pi >= photos.length) continue;
      const photo = { ...(photos[pi] || {}) };
      if (!(`${field}${SIG_DEFERRED_SUFFIX}` in photo)) continue;
      delete photo[`${field}${SIG_DEFERRED_SUFFIX}`];
      photo[field] = map[path];
      photos[pi] = photo;
      act.photos = photos;
      copied.activities[ai] = act;
      touched = true;
      continue;
    }
    if (parts.length !== 4 || parts[0] !== 'data') continue;
    const [, listName, index, field] = parts;
    const rows = out.data[listName];
    if (!Array.isArray(rows)) continue;
    const i = Number(index);
    if (!Number.isInteger(i) || i < 0 || i >= rows.length) continue;
    if (!copied[listName]) {
      copied[listName] = rows.slice();
      out.data[listName] = copied[listName];
    }
    const list = copied[listName];
    const holder = { ...(list[i] || {}) };
    // ONLY WHERE A FLAG SAID SO. A path that names a mark this body did not
    // defer is ignored rather than written: that is a server and a device
    // disagreeing about the record, and the stored document is the record.
    if (!(`${field}${SIG_DEFERRED_SUFFIX}` in holder)) continue;
    delete holder[`${field}${SIG_DEFERRED_SUFFIX}`];
    holder[field] = map[path];
    list[i] = holder;
    touched = true;
  }
  return touched ? out : log;
}
