/**
 * INJECTS THE BUILD'S COMMIT INTO THE APP.
 *
 * app.json carries a `extra.jsCommit` slot and app/settings.jsx reads it, but
 * nothing ever filled it, so every bundle ever published reported "Bundle
 * commit not injected at build time". The card exists to make a device test
 * unambiguous — which JS is on this phone, and does it match the server — and
 * it could not answer the only question it was built to answer. Device round 4
 * spent a finding on that.
 *
 * WHY A CONFIG FILE RATHER THAN A COMMITTED VALUE. A commit written into
 * app.json would be the commit of whenever someone last remembered to update
 * it, which is worse than blank: a stale hash reads as a confident answer. This
 * resolves at publish time from the environment doing the publishing.
 *
 * THE SOURCES, in order:
 *   EAS_BUILD_GIT_COMMIT_HASH  set by EAS Build (native binaries)
 *   JS_COMMIT                  set by .github/workflows/ota-update.yml from
 *                              github.sha (OTA bundles — the usual path)
 *   EXPO_PUBLIC_JS_COMMIT      manual override for a local export
 *
 * NEVER A FALLBACK TO `git rev-parse`. A local working tree is not the thing
 * being published, and reading one would let a dirty checkout claim a clean
 * commit. With no environment value it stays '' and the card says it does not
 * know — the behaviour that is already there and already honest.
 *
 * MUST STAY A STRING. `null` came back from the Expo config pipeline as `{}`,
 * which is truthy, got rendered as a React child and crashed /settings with
 * React error #31. See src/utils/buildIdentity.test.cjs.
 */
module.exports = ({ config }) => ({
  ...config,
  extra: {
    ...config.extra,
    jsCommit: String(
      process.env.EAS_BUILD_GIT_COMMIT_HASH
      || process.env.JS_COMMIT
      || process.env.EXPO_PUBLIC_JS_COMMIT
      || '',
    ).trim(),
  },
});
