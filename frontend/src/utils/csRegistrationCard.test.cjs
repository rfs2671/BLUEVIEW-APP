/**
 * The CS card, as the card itself is printed.
 *
 * WHAT THE PHYSICAL CARD SAYS. A NYC construction superintendent carries a
 * DOB-issued card printed with a REGISTRATION NUMBER, an ISSUE date and an
 * EXPIRATION date. Three screens showed the first of the three and labelled it
 * a LICENSE: the admin register (`admin/superintendent.jsx`) and the two log
 * editors that print a badge under the superintendent's signature
 * (`daily-log.jsx`, `site/daily-logs.jsx`).
 *
 * THE LABEL IS PART OF THE RECORD. "CS LICENSE: 12345" sits directly beneath a
 * signature on a compliance log. It states that the man holds a licence, which
 * is not what his card says he holds.
 *
 * THE FALLBACK IS THE WHOLE TRICK. Nothing migrates. Every registration
 * written before today carries `license_number` and no `registration_number`,
 * so every read here has to take EITHER — and the edit form especially, since
 * a form that loads a blank and saves it wipes the number off a live record.
 *
 * NO EXPIRY ENFORCEMENT ANYWHERE IN THE UI. The dates are captured and shown;
 * nothing greys out, warns, or blocks on them. That is a product ruling the
 * operator has not made, and section 4 pins its absence.
 *
 * Run:  node src/utils/csRegistrationCard.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
const read = (...p) =>
  fs.readFileSync(path.join(FRONTEND, ...p), 'utf8').split('\r\n').join('\n');

const ADMIN = read('app', 'admin', 'superintendent.jsx');
const CP_LOG = read('app', 'daily-log.jsx');
const SITE_LOG = read('app', 'site', 'daily-logs.jsx');

let failures = 0;
const ok = (c, m) => {
  if (c) { console.log(`  ok  ${m}`); } else { failures += 1; console.log(`FAIL  ${m}`); }
};

console.log('\n1. THE ADMIN REGISTER CAPTURES ALL THREE PRINTED FIELDS');
{
  ok(/registration_number: ''/.test(ADMIN),
    'the form carries a registration_number, not a license_number');
  ok(/issue_date: ''/.test(ADMIN) && /expiration_date: ''/.test(ADMIN),
    'and the two dates the card is printed with');
  ok(/registration_number: form\.registration_number/.test(ADMIN),
    'create posts the registration number');
  ok(/issue_date: form\.issue_date/.test(ADMIN)
     && /expiration_date: form\.expiration_date/.test(ADMIN),
  'create posts both dates');
  ok(/changed\.registration_number = /.test(ADMIN),
    'and edit diffs the number so a correction reaches the server');
  ok(/changed\.issue_date = /.test(ADMIN)
     && /changed\.expiration_date = /.test(ADMIN),
  'and diffs both dates');
}

console.log('\n2. EVERY READ TAKES EITHER NAME — NOTHING MIGRATES');
{
  ok(/reg\.registration_number \|\| reg\.license_number/.test(ADMIN),
    'the edit form loads the number under EITHER name — a form that loaded a '
    + 'blank here would save the number off a live registration');
  const cardReads = ADMIN.match(
    /registration_number \|\| [a-z]+\.license_number/g) || [];
  ok(cardReads.length >= 2,
    'and so does the list card, so historical rows still show their number');
  ok(/registration_number \|\| .*license_number/.test(CP_LOG),
    'the CP log badge takes either name');
  ok(/registration_number \|\| .*license_number/.test(SITE_LOG),
    'and so does the site log badge');
}

console.log('\n3. IT IS CALLED A REGISTRATION, ON THE SCREEN AND ON THE BADGE');
{
  ok(/REGISTRATION NUMBER/.test(ADMIN),
    'the admin field is labelled REGISTRATION NUMBER');
  ok(!/license number/i.test(ADMIN),
    'and nothing on that screen — label, placeholder or toast — still calls '
    + 'it a license number');
  ok(!/License will be marked inactive/.test(ADMIN)
     && !/CS license per active job/.test(ADMIN),
  'nor does the delete prompt or the one-job banner call the registration a '
  + 'license');
  ok(/CS REGISTRATION:/.test(CP_LOG),
    'the CP log badge under the signature says CS REGISTRATION');
  ok(/CS REGISTRATION:/.test(SITE_LOG),
    'and so does the site log badge');
  ok(!/CS LICENSE:/.test(CP_LOG) && !/CS LICENSE:/.test(SITE_LOG),
    'neither log still prints CS LICENSE beneath a signature');
  ok(/ISSUE DATE/.test(ADMIN) && /EXPIRATION DATE/.test(ADMIN),
    'and the two dates are labelled as the card labels them');
}

console.log('\n4. NOTHING IN THE UI ENFORCES AN EXPIRY');
{
  // The operator has not ruled on what an expired registration should do. The
  // dates are captured and displayed; that is the whole feature. If this ever
  // changes it should change deliberately, by deleting these three lines.
  ok(!/registrationExpired|isExpired|expiredWarning/.test(ADMIN),
    'no expiry verdict is computed on the admin screen');
  ok(!/disabled=\{[^}]*expiration_date/.test(ADMIN),
    'nothing is disabled because of an expiry date');
  ok(!/expir/i.test(CP_LOG.slice(CP_LOG.indexOf('CS REGISTRATION:') - 400,
    CP_LOG.indexOf('CS REGISTRATION:') + 400)),
  'and the log badge states the number without judging it');
}

console.log(`\n${failures === 0 ? 'ALL PASS' : `${failures} FAILURE(S)`}\n`);
process.exit(failures === 0 ? 0 : 1);
