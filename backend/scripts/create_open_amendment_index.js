/**
 * ONE OPEN AMENDMENT PER PARENT, ENFORCED BY THE DATABASE.
 *
 *   mongosh "$MONGO_URL" backend/scripts/create_open_amendment_index.js
 *
 * Add DROP=1 to remove the index instead of creating it:
 *
 *   DROP=1 mongosh "$MONGO_URL" backend/scripts/create_open_amendment_index.js
 *
 * A FILE, NOT A --eval ONE-LINER, for the reason audit_r2_photo_exposure.js
 * already gives: one-liners handed over in a session arrive mangled -- the
 * shell eats the `$` operators and the quotes collapse. This one is worse than
 * most to retype, because a partialFilterExpression that loses a clause builds
 * a DIFFERENT and WRONGER index that looks like a success.
 *
 * ── WHAT THE DEFECT IS ──────────────────────────────────────────────────────
 *
 * amend_logbook (server.py) READS the parent's children, asks
 * open_amendment_head whether one is already open, and then INSERTS. There is
 * nothing between the read and the insert. Two genuinely simultaneous requests
 * both read "no open child" and both insert, and the application layer cannot
 * close that -- only a unique index can.
 *
 * Production carries the result twice over. Two open children on ONE parent on
 * 2026-08-10 (sixty seconds apart) and two more on 2026-08-14 (twenty-six
 * seconds apart): a superintendent tapped Amend, the screen did not visibly
 * change, and he tapped again.
 *
 * ── WHY THE BUILD CAN FAIL, AND WHY THIS SCRIPT REFUSES RATHER THAN TRIES ───
 *
 * THOSE DUPLICATES ARE STILL THERE. A unique index cannot be built over a
 * collection that already violates it -- the build is rejected. Worse, the
 * application's own bootstrap calls this index through
 * _ensure_index_resilient, which LOGS AND RETURNS on failure by design (an
 * index must never block app startup). So on deploy the rejection is silent:
 * the race stays open and every test still passes.
 *
 * This script therefore does the opposite. It looks for the violating parents
 * FIRST, prints them, and refuses to attempt the build if any exist. Clearing
 * them is a product action, not a database one: withdraw the extra drafts
 * (POST /api/logbooks/{id}/withdraw, or the "Withdraw this correction" button
 * on the log), which leaves both documents intact and releases the slot. Then
 * run this again.
 *
 * ── THE FILTER, CLAUSE BY CLAUSE ────────────────────────────────────────────
 *
 * It MIRRORS server.py's OPEN_AMENDMENT_PARTIAL_FILTER exactly, and a test
 * (test_amendment_withdraw.py) asserts the two agree -- an index the operator
 * builds that the application does not believe in is worse than none.
 *
 *   parent_logbook_id: {$type: "string"}   the key. Only children have one.
 *   is_amendment: true                     never governs an ORIGINAL. A unique
 *                                          index reaching originals would
 *                                          allow one logbook in the collection.
 *   is_deleted: false                      a soft-deleted child releases the
 *                                          slot.
 *   status: "draft"                        excludes "submitted" AND
 *                                          "withdrawn". A withdrawn child that
 *                                          still held the slot would keep the
 *                                          parent's Amend button shut forever,
 *                                          which is the dead end withdrawal
 *                                          exists to open.
 *   is_locked: false                       a filed child releases it.
 *   cp_signature: null                     unsigned. In Mongo an equality to
 *                                          null matches null OR MISSING, which
 *                                          is exactly the question meant.
 *
 * EVERY CLAUSE IS ONE A partialFilterExpression MAY CONTAIN. Mongo permits
 * equality, $exists:true, the range operators and $type -- and rejects $ne,
 * $or, $not and $nin. That constraint is why the filter reads as it does.
 *
 * NO SENTINEL FIELD, AND THAT IS THE POINT. Every clause reads a field the
 * document already carries, so a child leaves the index the moment it is
 * withdrawn, filed, signed or deleted. Nothing has to remember to unset
 * anything, and no closing path can forget and wedge a parent shut.
 *
 * ── WHAT IT IS NOT ──────────────────────────────────────────────────────────
 *
 * READ-ONLY EXCEPT FOR THE INDEX ITSELF. It never writes, updates or deletes a
 * document. The only mutation it can make is createIndex (or dropIndex under
 * DROP=1).
 */

const INDEX_NAME = "logbooks_one_open_amendment_per_parent";
const KEYS = { parent_logbook_id: 1 };
const PARTIAL_FILTER = {
  parent_logbook_id: { $type: "string" },
  is_amendment: true,
  is_deleted: false,
  status: "draft",
  is_locked: false,
  cp_signature: null,
};

const coll = db.getCollection("logbooks");
const DROP = (process.env.DROP || "") !== "";

print("");
print("=== " + INDEX_NAME + " ===");
print("db: " + db.getName());
print("");

if (DROP) {
  const before = coll.getIndexes().filter((i) => i.name === INDEX_NAME);
  if (before.length === 0) {
    print("Index is not present. Nothing to drop.");
  } else {
    coll.dropIndex(INDEX_NAME);
    print("DROPPED " + INDEX_NAME);
  }
  const after = coll.getIndexes().filter((i) => i.name === INDEX_NAME);
  print("Verified present after drop: " + after.length + " (expected 0)");
  quit(after.length === 0 ? 0 : 1);
}

// ── ALREADY THERE? ──────────────────────────────────────────────────────────
const existing = coll.getIndexes().filter((i) => i.name === INDEX_NAME);
if (existing.length > 0) {
  print("Index ALREADY EXISTS. Nothing to do.");
  printjson(existing[0]);
  quit(0);
}

// ── THE VIOLATIONS THAT WOULD REJECT THE BUILD ──────────────────────────────
//
// Counted through the SAME predicate the index uses, so this cannot report
// clean while the build fails on something it did not look at.
const openCount = coll.countDocuments(PARTIAL_FILTER);
print("Open amendment drafts the index would govern: " + openCount);

// THE POSITIVE CONTROL. An empty result is either a finding or a broken check,
// and nothing distinguishes them without one. If the filter selected NOTHING
// at all, a clean duplicate report below would be meaningless -- the index
// would build instantly and enforce nothing.
if (openCount === 0) {
  print("");
  print("NOTE: the filter matches ZERO documents right now.");
  print("That is either genuinely no open corrections, or a filter that has");
  print("drifted from what amend_logbook writes. Check one before trusting a");
  print("clean duplicate report:");
  const anyChild = coll.countDocuments({
    parent_logbook_id: { $type: "string" },
    is_amendment: true,
  });
  print("  amendment children in the collection at all: " + anyChild);
  if (anyChild > 0) {
    print("  a sample child, so its field shapes can be compared by eye:");
    printjson(
      coll.findOne(
        { parent_logbook_id: { $type: "string" }, is_amendment: true },
        {
          _id: 1, parent_logbook_id: 1, is_amendment: 1, is_deleted: 1,
          status: 1, is_locked: 1, cp_signature: 1, date: 1,
        }
      )
    );
  }
}

const dupes = coll
  .aggregate([
    { $match: PARTIAL_FILTER },
    {
      $group: {
        _id: "$parent_logbook_id",
        n: { $sum: 1 },
        children: { $push: { id: "$_id", at: "$created_at", date: "$date" } },
      },
    },
    { $match: { n: { $gt: 1 } } },
    { $sort: { n: -1 } },
  ])
  .toArray();

if (dupes.length > 0) {
  print("");
  print("REFUSING TO BUILD. " + dupes.length + " parent(s) already hold more");
  print("than one open amendment. A unique index over them is rejected, and");
  print("the application's own bootstrap would swallow that rejection.");
  print("");
  dupes.forEach((d) => {
    print("  parent " + d._id + "  ->  " + d.n + " open children");
    d.children.forEach((c) => {
      print("      " + c.id + "   date=" + c.date + "   created=" + c.at);
    });
  });
  print("");
  print("FIX THEM THROUGH THE PRODUCT, NOT THE DATABASE: withdraw the extra");
  print("drafts. That is a state, not a delete -- both documents survive");
  print("intact, and a withdrawn child no longer matches the filter.");
  print("");
  print("  POST /api/logbooks/{logbook_id}/withdraw   (a signature is");
  print("  required; the 'Withdraw this correction' button on the log sends");
  print("  one). Keep the child you meant; withdraw the rest.");
  print("");
  print("Then run this script again.");
  quit(1);
}

print("No parent holds more than one open amendment. Building.");

// THE ONE FAILURE MODE THAT CANNOT BE CHECKED ANYWHERE ELSE.
//
// A partialFilterExpression may contain ONLY equality, $exists:true, the range
// operators and $type. Every clause above is one of those, but the server that
// decides is Atlas and nothing in the test suite can ask it -- the backend
// tests run against mocks, and the application's own bootstrap calls this
// index through _ensure_index_resilient, which LOGS AND RETURNS on failure.
//
// So this script is the only place a rejection is ever seen by a person, and
// it must say WHICH kind of rejection it was rather than printing a stack.
try {
  coll.createIndex(KEYS, {
    name: INDEX_NAME,
    unique: true,
    partialFilterExpression: PARTIAL_FILTER,
  });
} catch (e) {
  const msg = String((e && e.message) || e);
  print("");
  print("createIndex FAILED: " + msg);
  print("");
  if (/partialFilterExpression|partial|filter/i.test(msg)) {
    print("THE FILTER WAS REJECTED, not the data. A partialFilterExpression");
    print("accepts only equality, $exists:true, $gt/$gte/$lt/$lte and $type.");
    print("Report this with the message above — server.py's");
    print("OPEN_AMENDMENT_PARTIAL_FILTER has to change with it, or the two");
    print("definitions drift and the app believes in an index that is not");
    print("there. Do NOT hand-edit one of them to get past this.");
  } else if (/E11000|duplicate/i.test(msg)) {
    print("DUPLICATES EXIST that the check above did not find. That means the");
    print("filter here and the data disagree — report it rather than");
    print("deleting rows to make the build pass.");
  } else {
    print("Neither a filter rejection nor a duplicate. Report the message.");
  }
  quit(1);
}

// ── VERIFY IT ACTUALLY EXISTS, AND THAT IT IS THE RIGHT ONE ─────────────────
//
// createIndex returning without throwing is not the same as the index being
// there with the shape asked for. Read it back.
const built = coll.getIndexes().filter((i) => i.name === INDEX_NAME);
print("");
if (built.length === 0) {
  print("FAILED: createIndex reported no error but the index is NOT present.");
  quit(1);
}
printjson(built[0]);
const ok =
  built[0].unique === true &&
  built[0].partialFilterExpression !== undefined &&
  JSON.stringify(built[0].key) === JSON.stringify(KEYS);
print("");
print(ok ? "BUILT AND VERIFIED." : "PRESENT BUT THE SHAPE IS WRONG -- see above.");
quit(ok ? 0 : 1);
