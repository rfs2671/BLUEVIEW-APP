#!/usr/bin/env bash
# SECRET SCAN — the lines a change ADDS, checked for credentials before merge.
#
#   scripts/secret-scan.sh <base-ref>        scan what HEAD adds over <base-ref>
#   scripts/secret-scan.sh --self-test       prove the scanner can find something
#
# ── WHY THE ADDED LINES, AND NOT THE WHOLE HISTORY ─────────────────────────
#
# History already holds one JWT signed with the production secret
# (test_reports/iteration_4.json, January 2026). The operator ruled NO history
# rewrite -- rotating the secret is what closes it. A scanner pointed at full
# history would therefore fail every pull request forever over a finding that
# is already known and already being handled, and a gate that is always red is
# switched off by the first person who needs to merge. This asks the question
# a PR can actually answer: does THIS change add a secret?
#
# ── WHY THERE IS A SELF-TEST, AND WHY IT RUNS FIRST ────────────────────────
#
# The scan that found that JWT first reported ZERO hits over 1.4 million lines
# of history that provably contained matches. `git log -p` emits NUL bytes; GNU
# grep then switches to binary mode and prints "Binary file matches" in place
# of the lines, and the next grep in the pipe discards that silently. `-c`
# still counts in binary mode, which is why a count looked healthy while the
# listing was empty. Every grep below carries `-a`, and the self-test feeds the
# scanner lines it MUST catch -- through the same pipeline, with a NUL byte in
# the stream -- before it is allowed to report a clean scan. A scanner that
# cannot fail is not a scanner.
#
# ── WHAT IT LOOKS FOR ──────────────────────────────────────────────────────
#
# Mongo URIs carrying a password, AWS/R2-style access keys, private-key blocks,
# OpenAI-style `sk-`, Resend `re_`, GitHub and Slack tokens, signed JWTs, and a
# named-variable rule for the credentials this app actually holds -- JWT, R2,
# DeepInfra (QWEN), WaAPI, Resend, Mongo -- because those have no distinctive
# prefix and a pattern alone would never see them.
#
# A line that must legitimately contain such a string says so inline:
#     ...   # secret-scan: allow
set -euo pipefail

PATTERN='mongodb(\+srv)?://[^/[:space:]:@]+:[^@[:space:]]+@'
PATTERN+='|AKIA[0-9A-Z]{16}'
PATTERN+='|-----BEGIN [A-Z ]*PRIVATE KEY-----'
PATTERN+='|(^|[^A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}'
PATTERN+='|(^|[^A-Za-z0-9])re_[A-Za-z0-9_]{20,}'
PATTERN+='|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}'
PATTERN+='|xox[baprs]-[A-Za-z0-9-]{10,}'
PATTERN+='|eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{20,}'
PATTERN+='|(JWT_SECRET|R2_SECRET_ACCESS_KEY|R2_ACCESS_KEY_ID|QWEN_API_KEY|DEEPINFRA_API_KEY|WAAPI_TOKEN|RESEND_API_KEY|MONGO_URL)[[:space:]]*[:=][[:space:]]*["'"'"'][^"'"'"'$<{]{16,}'

# Values that LOOK like credentials and are documentation. Kept short and
# literal on purpose: an allowlist that grows a wildcard stops being one.
PLACEHOLDERS='localhost|127\.0\.0\.1|user:pass@|:PASSWORD@|:password@|<[^>]+>|\.\.\.@|…|example\.(com|org)|dev-only|not-for-production|smoke_test|changeme|your[-_]'

scan() {
  # stdin: unified-diff text. stdout: offending added lines. Never exits
  # non-zero itself -- the caller decides, so the self-test can inspect.
  grep -a -E '^\+' \
    | grep -a -v -E '^\+\+\+ ' \
    | grep -a -E "$PATTERN" \
    | grep -a -v -E "$PLACEHOLDERS" \
    | grep -a -v -F 'secret-scan: allow' \
    || true
}

self_test() {
  local fake_jwt fake_uri found
  # Assembled at runtime so this file never contains a literal that the scan
  # would itself report on the PR that edits it.
  fake_jwt="eyJ""hbGciOiJIUzI1NiJ9.eyJ""zdWIiOiJzZWxmLXRlc3QifQ.c2lnbmF0dXJlc2lnbmF0dXJlc2ln"
  # The '@' is supplied by a variable, so this LINE never carries the
  # user:secret@host shape. Splitting with "" would not do: quotes are inside
  # the pattern's [^@] class and the match would run straight through them.
  local at='@'
  fake_uri="mongodb+srv://svc:Zq8vK2mN4pR7tX1w${at}cluster0.abcde.mongodb.net"
  found=$(printf '+++ b/x\n+token = "%s"\n+\0binary\n+MONGO_URL = "%s"\n+MONGO_URL = "mongodb://localhost:27017"\n+ok = "%s"  # secret-scan: allow\n' \
            "$fake_jwt" "$fake_uri" "$fake_jwt" | scan | wc -l)
  # Exactly two: the JWT and the real-shaped URI. The localhost URI is a
  # placeholder and the third line opts out; the NUL byte must not blind it.
  if [ "$found" != "2" ]; then
    echo "::error::secret-scan SELF-TEST FAILED: expected 2 findings, got $found."
    echo "The scanner cannot be trusted to report a clean result."
    exit 2
  fi
  echo "secret-scan self-test: 2 of 2 planted secrets caught, placeholder and opt-out ignored"
}

if [ "${1:-}" = "--self-test" ]; then
  self_test
  exit 0
fi

BASE="${1:?usage: secret-scan.sh <base-ref> | --self-test}"
self_test

# FILE BY FILE, and only the file name and a count are printed. The value
# must never reach a public CI log -- that would be a second leak of the thing
# being reported -- and neither may a prefix of it: the first characters of a
# key are the ones that identify it.
bad=0
while IFS= read -r f; do
  [ -n "$f" ] || continue
  n=$(git diff --no-color --unified=0 "$BASE"...HEAD -- "$f" | scan | wc -l)
  if [ "$n" -gt 0 ]; then
    echo "::error file=$f::secret-scan: $n added line(s) look like a credential (value withheld)"
    bad=$((bad + n))
  fi
done < <(git diff --name-only --diff-filter=AM "$BASE"...HEAD)

if [ "$bad" -gt 0 ]; then
  echo
  echo "Remove the value and ROTATE it -- a secret that reached a pushed branch"
  echo "is exposed whether or not this PR merges. If a line is genuinely safe,"
  echo "end it with:   # secret-scan: allow"
  exit 1
fi
echo "secret-scan: no credentials added over $BASE"
