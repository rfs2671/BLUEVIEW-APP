/**
 * PR C — daily-log photo lightbox. Photos were 80x80 thumbnails with only a
 * remove badge; now tap-to-enlarge (mirrors the worker-detail OSHA-card modal),
 * showing the ENHANCED derivative and falling back gracefully when
 * enhance_status != done. Static guard over the shipped source.
 *
 * Run:  node src/utils/photoLightbox.test.cjs
 */
const fs = require('fs');
const path = require('path');

const dailyJobsite = fs.readFileSync(
  path.join(__dirname, '..', '..', 'app', 'logbooks', 'daily_jobsite.jsx'), 'utf8');
const api = fs.readFileSync(path.join(__dirname, 'api.js'), 'utf8');

let passed = 0, failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

ok(/openPhotoLightbox/.test(dailyJobsite) && /photoLightbox/.test(dailyJobsite),
  'daily_jobsite: lightbox handler + state present');
ok(/onPress=\{\(\) => openPhotoLightbox/.test(dailyJobsite),
  'daily_jobsite: thumbnail is tappable (was no onPress)');
ok(/enhance_status === 'done'/.test(dailyJobsite),
  'daily_jobsite: shows enhanced when done, original otherwise (no broken image)');
ok(/<Modal/.test(dailyJobsite) && /resizeMode="contain"/.test(dailyJobsite),
  'daily_jobsite: lightbox Modal (mirrors the OSHA-card modal)');
ok(/lightboxLabel/.test(dailyJobsite),
  'daily_jobsite: labels which version is shown (Enhanced / Original)');
ok(/getLogbookPhotoUrl:/.test(api) && /\/reports\/logbook-photo\//.test(api),
  'api.js: getLogbookPhotoUrl builds the ?v= serving URL');
ok(/getLogbookPhotoUrl\(/.test(dailyJobsite),
  'daily_jobsite: consumes getLogbookPhotoUrl (not dead)');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
