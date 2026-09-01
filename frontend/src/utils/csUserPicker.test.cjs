/**
 * Linking a CS registration to the account that signs.
 *
 * WHY IT MATTERS. `cs_registrations.user_id` has existed since #311 and
 * `attribute_signer` reads it — but nothing ever WROTE it, so every
 * registration created through the UI carried `user_id: null` and
 * MATCHED_ACCOUNT was unreachable. The best available answer was
 * MATCHED_LICENCE, which that module itself calls "corroboration, not
 * binding: two humans typed the same string".
 *
 * EVERY APPROVED USER IN THE COMPANY, NO ROLE FILTER. A CS licence is a DOB
 * credential, not an app role. Michael is role "cp" and IS the construction
 * superintendent, so filtering by role would hide the one person this control
 * exists to link — the same mistake as gating the log on
 * role == "superintendent".
 *
 * THREE STATES ON THE CARD, and the middle one is the point: an admin who
 * cannot SEE that a registration is unlinked will not know to fix it. The
 * third — linked to a user who no longer exists — looks linked until somebody
 * tries to use it.
 *
 * Run:  node src/utils/csUserPicker.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
const SRC = fs.readFileSync(
  path.join(FRONTEND, 'app', 'admin', 'superintendent.jsx'), 'utf8',
).split('\r\n').join('\n');

let failures = 0;
const ok = (c, m) => {
  if (c) { console.log(`  ok  ${m}`); } else { failures += 1; console.log(`FAIL  ${m}`); }
};

console.log('\n1. THE LINK IS WRITTEN, ON CREATE AND ON EDIT');
{
  ok(/user_id: form\.user_id \|\| null/.test(SRC),
    'create sends the link');
  ok(/const userNew = form\.user_id \|\| null;/.test(SRC)
     && /changed\.user_id = userNew/.test(SRC),
  'and edit diffs it, so linking AND unlinking both reach the server');
  ok(/user_id: reg\.user_id \|\| ''/.test(SRC),
    'the edit form loads the EXISTING link — an unlinked registration must be '
    + 'fixable, not silently unlinkable');
  ok(!/user_id: form\.user_id,\s*$/m.test(SRC),
    "'' is never sent as a user id — absent must read as absent, and an empty "
    + 'string is an id that matches nobody');
}

console.log('\n2. NO ROLE FILTER');
{
  // `setProjectsState` is DECLARED above fetchData, so it is not a valid end
  // anchor — slicing to it yields an empty string and the assertion passes or
  // fails on nothing. Anchor on the Promise.all itself.
  const start = SRC.indexOf('const [regsRes, usersRes, projsRes]');
  const end = SRC.indexOf('setFetchState(regsRes.status)');
  ok(start > 0 && end > start, 'the fetch block was located at all');
  const fetchBlock = SRC.slice(start, end);
  ok(/adminUsersAPI\.getAll\(\)/.test(fetchBlock),
    'it asks for the company user list');
  ok(!/role\s*===\s*'superintendent'/.test(SRC)
     && !/filter\(\s*\(?u\)?\s*=>\s*u\.role/.test(SRC),
  'and does NOT filter by role — Michael is cp and IS the CS');
}

console.log('\n3. THREE STATES ON THE CARD');
{
  ok(/Not linked to a user account/.test(SRC), 'unlinked is stated, not blank');
  ok(/Linked to a user who no longer exists/.test(SRC),
    'a dangling link is called out rather than reading as linked');
  ok(/Linked to \$\{linked\.full_name/.test(SRC),
    'and a good link names the person');
  ok(/linkOk:.*verified/.test(SRC) && /linkMissing:.*attention/.test(SRC)
     && /linkBroken:.*critical/.test(SRC),
  'the three states differ by COLOUR too, so a list can be scanned');
  ok(!/semantic\.danger/.test(SRC),
    'using a token that exists — the module exports attention/critical/verified');
}

console.log('\n4. THE PICKER CANNOT MISLEAD');
{
  ok(/No DEFAULT SELECTION|NO DEFAULT SELECTION/.test(SRC),
    'nothing is pre-picked — linking the wrong user asserts an identity on a '
    + 'statutory record');
  ok(/u\.email/.test(SRC),
    'each row shows the email as well as the name, because two people can '
    + 'share a name');
  ok(/usersState !== 'ok'/.test(SRC),
    'a FAILED user load says so rather than rendering an empty list, which '
    + 'would read as "there is nobody to link"');
  ok(/still files/.test(SRC),
    'and says the registration still works without a link, so a load failure '
    + 'does not block the admin');
}

console.log('\n5. THE THIRD FETCH IS DESTRUCTURED');
{
  ok(/const \[regsRes, usersRes, projsRes\] = await Promise\.all\(/.test(SRC),
    'adding a promise without widening the destructure would have handed the '
    + 'USERS result to projsRes');
}

console.log(`\n${failures === 0 ? 'ALL PASS' : `${failures} FAILURE(S)`}\n`);
process.exit(failures === 0 ? 0 : 1);
