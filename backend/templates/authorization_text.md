# Filing Authorization

**Version:** 1.0
**Effective:** 2026-04-30

By accepting this authorization, you (the licensed General Contractor or
their authorized agent) grant LeveLog, Inc. permission to:

1. **Submit permit renewal applications on your behalf** through the
   NYC Department of Buildings DOB NOW filing system, using the DOB
   NOW credentials you provide. Filings will be made in your name as
   the legal licensee — you remain responsible for the accuracy of
   the data submitted and for compliance with NYC Building Code and
   DOB rules.

2. **Use your DOB NOW credentials only for permit-renewal filings**
   you have specifically authorized through the LeveLog interface.
   We will not log into DOB NOW outside the context of a renewal
   you have explicitly initiated.

3. **Store your credentials in encrypted form**, using a hybrid
   encryption scheme (AES-256-GCM data key wrapped by RSA-OAEP-4096
   against an offline private key held only on the LeveLog operator's
   designated agent machine). Cloud servers never see your password
   in plaintext; only the agent machine, after pulling a job from the
   queue, can decrypt them at filing time.

4. **Pay the standard DOB renewal fee** ($130 for the 1-year ceiling
   renewal) directly to NYC DOB through the DOB NOW payment flow.
   LeveLog does not collect or process this fee — it is paid through
   your DOB NOW account using your saved payment method.

You may revoke this authorization at any time by:
- Removing your DOB NOW credentials from a Filing Representative's
  profile in the LeveLog Owner Portal (Settings → Filing Reps →
  Revoke Credentials), OR
- Contacting LeveLog support at hello@levelog.com.

Revocation takes effect immediately. Any in-flight filing jobs that
have already begun executing on the agent will complete their
current step before halting; subsequent filings cannot proceed
without re-entered credentials.

This authorization is between you (or your authorized representative
on behalf of the licensed individual) and LeveLog, Inc. It does NOT
modify your existing relationship with NYC DOB. You retain all rights
and responsibilities as the legal licensee under NYC DOB rules.

By typing the licensee name below and clicking "Accept", you
confirm that:
- You have read and understood the above terms.
- You are the licensed individual named, OR you are an authorized
  representative with explicit permission to grant this authorization
  on the licensee's behalf.
- You consent to LeveLog filing permit renewals on your behalf
  under the conditions above.
