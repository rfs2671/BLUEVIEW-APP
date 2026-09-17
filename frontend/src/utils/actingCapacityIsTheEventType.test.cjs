/**
 * `acting_capacity` COMES FROM THE SIGNATURE EVENT TYPE, NEVER FROM THE ROLE.
 *
 * ── THE ONE ACCOUNT THIS IS ABOUT ───────────────────────────────────────────
 *
 * Michael Cespedes is the registered construction superintendent on 588 Thomas
 * — the only `cs_registrations` row on the platform — and he holds `role: cp`.
 * He signs BC 3301.13.13, the superintendent's own statutory record, from that
 * account. If the capacity were read off his role, the ledger would record the
 * superintendent's log as signed by a COMPETENT PERSON: the precise opposite of
 * what `acting_capacity` exists to prove, on the one document where the
 * capacity IS the point.
 *
 * ── IT IS ALREADY CORRECT, AND THAT IS WHY THIS EXISTS ──────────────────────
 *
 * `deriveActingCapacity` keys on the event type first and falls back to the
 * role only when the event type says nothing. Nothing tested it. The role-split
 * work adds a real `superintendent` role and promotes Michael onto it, and the
 * change that looks like tidying up afterwards — "now that the role exists, read
 * the capacity from it" — is exactly the change that breaks this, silently. No
 * error, the hash computes, the document renders; only the capacity is wrong,
 * in a field nobody reads until somebody needs it.
 *
 * ── THE ASSERTION IS THE CONFLICT, NOT THE AGREEMENT ────────────────────────
 *
 * Asking `deriveActingCapacity('superintendent_sign', 'superintendent')` proves
 * nothing: both inputs point the same way and a role-driven implementation
 * passes it. Every case below sets the event type and the role AGAINST each
 * other and asserts the EVENT TYPE won.
 *
 * Run:  node src/utils/actingCapacityIsTheEventType.test.cjs
 */
const fs = require('fs');
const path = require('path');
const { loadEsm } = require('./esmHarness.cjs');

const FRONTEND = path.join(__dirname, '..', '..');

const { deriveActingCapacity } = loadEsm('src/utils/signatureAudit.js', {
  stubs: {
    'expo-device': {
      brand: null, modelName: null, modelId: null, osName: null,
      osVersion: null, deviceName: null,
    },
    'react-native': { Platform: { OS: 'test' } },
    './api': { default: { post: async () => ({ data: {} }) } },
  },
});

let failures = 0;
const check = (name, fn) => {
  try {
    fn();
    console.log(`  ok  ${name}`);
  } catch (e) {
    failures += 1;
    console.error(`FAIL  ${name}\n      ${e.message}`);
  }
};
const eq = (actual, expected, what) => {
  if (actual !== expected) {
    throw new Error(`${what}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
  }
};

console.log('\nacting_capacity is the event type\n');

// ── 1. THE EVENT TYPE BEATS A CONFLICTING ROLE, IN BOTH DIRECTIONS ──────────

check("a cp signing the superintendent's log signs as a Superintendent", () => {
  eq(deriveActingCapacity('superintendent_sign', 'cp'),
    'Construction Superintendent', 'Michael, today');
});

check('a superintendent signing the daily jobsite log signs as a Competent Person', () => {
  eq(deriveActingCapacity('cp_sign', 'superintendent'),
    'Competent Person', 'Michael, after the migration');
});

check('an admin signing the superintendent log still signs as a Superintendent', () => {
  eq(deriveActingCapacity('superintendent_sign', 'admin'),
    'Construction Superintendent', 'admin');
});

check('the ssc event type beats a cp role', () => {
  eq(deriveActingCapacity('ssc_sign', 'cp'),
    'Site Safety Coordinator/Manager', 'ssc_sign');
});

check('the answer does not move when only the role moves', () => {
  // THE INVARIANT, stated as one sentence rather than as N cases: hold the
  // event type and vary the role across every role this product has, including
  // the two the role split adds. One answer, or the role is deciding.
  const roles = ['cp', 'superintendent', 'admin', 'owner', 'pm', 'site_device',
    'worker', '', null, undefined];
  for (const eventType of ['superintendent_sign', 'cp_sign', 'ssc_sign']) {
    const answers = new Set(roles.map((r) => deriveActingCapacity(eventType, r)));
    if (answers.size !== 1) {
      throw new Error(
        `${eventType} produced ${answers.size} different capacities across roles: `
        + `${JSON.stringify([...answers])}`,
      );
    }
  }
});

// ── 2. THE ROLE IS A FALLBACK AND IT IS STILL REACHABLE ─────────────────────
//
// If it were not, section 1 would pass on a function that ignored `signerRole`
// entirely — which is a different implementation from the one being pinned, and
// would drop the capacity for any event type not on the list.

check('an unknown event type falls back to the role', () => {
  eq(deriveActingCapacity('worker_sign', 'superintendent'),
    'Construction Superintendent', 'fallback');
  eq(deriveActingCapacity('worker_sign', 'cp'), 'Competent Person', 'fallback');
});

check('an unknown event type and an unknown role still name something', () => {
  // Never empty: a blank capacity on a ledger row is indistinguishable from an
  // event written before the field existed.
  eq(deriveActingCapacity('worker_sign', 'pm'), 'pm', 'unknown role');
  eq(deriveActingCapacity('', ''), 'Signer', 'nothing known');
});

// ── 3. THE CALLER STILL USES IT, AND AN EXPLICIT CAPACITY STILL WINS ────────

check('recordSignatureEvent derives the capacity when none is passed', () => {
  const src = fs.readFileSync(
    path.join(FRONTEND, 'src', 'utils', 'signatureAudit.js'), 'utf8',
  );
  const code = src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(?<!:)\/\/.*$/gm, '');
  if (!code.includes('actingCapacity || deriveActingCapacity(eventType, signerRole)')) {
    throw new Error(
      'the payload no longer derives the capacity from the event type — '
      + 'section 1 would keep passing while nothing shipped used the function',
    );
  }
});

check('the server is not asked to trust the role either', () => {
  // The server records `authenticated_role` SEPARATELY from `acting_capacity`
  // — the verified login role beside the claimed capacity. They must not be
  // the same value, or the capacity stops being independent evidence.
  const src = fs.readFileSync(
    path.join(__dirname, '..', '..', '..', 'backend', 'server.py'), 'utf8',
  );
  if (!src.includes('acting_capacity=data.acting_capacity')) {
    throw new Error('record_signature_event no longer takes the capacity from the body');
  }
  if (src.includes('acting_capacity=current_user.get("role")')) {
    throw new Error('the server is deriving the capacity from the login role');
  }
});

console.log(`\n${failures === 0 ? 'all passed' : `${failures} FAILED`}\n`);
process.exit(failures === 0 ? 0 : 1);
