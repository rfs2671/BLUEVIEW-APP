/**
 * MR.10 — Client-side hybrid encryption for DOB NOW credentials.
 *
 * Uses SubtleCrypto (Web Crypto API) — no third-party crypto libs.
 *
 * The byte format MUST match dob_worker/lib/crypto.py:decrypt_credentials:
 *
 *   [4-byte big-endian RSA-wrapped-key length]
 *   [RSA-OAEP-SHA256 wrapped 32-byte AES key]   (typically 512 bytes for RSA-4096)
 *   [12-byte AES-GCM nonce]
 *   [AES-GCM ciphertext + 16-byte tag concatenated]
 *
 * Final blob is base64-encoded for JSON transport. The agent's decrypt
 * path strips the prefix, splits into pieces, RSA-unwraps the AES key,
 * and AES-GCM-decrypts the ciphertext. We mirror that scheme here.
 *
 * Notes on SubtleCrypto vs cryptography.hazmat compatibility:
 *
 *   - AES-GCM: SubtleCrypto's `crypto.subtle.encrypt` with
 *     {name:'AES-GCM', iv, tagLength:128} returns ciphertext+tag
 *     concatenated (16-byte tag appended). cryptography.hazmat's
 *     AESGCM.encrypt returns the same layout. ✓
 *
 *   - RSA-OAEP: SubtleCrypto with {name:'RSA-OAEP', hash:'SHA-256'}
 *     uses MGF1 + SHA-256 + label=null. cryptography.hazmat's
 *     OAEP(MGF=MGF1(SHA-256), algorithm=SHA-256, label=None) is
 *     identical. ✓
 *
 *   - Public key import: We accept SubjectPublicKeyInfo PEM (the
 *     format `cryptography.serialization.PublicFormat.SubjectPublicKeyInfo`
 *     produces, which is what generate_keypair.py emits). PEM →
 *     base64 strip headers → DER bytes → SubtleCrypto's `importKey`
 *     with format='spki'. ✓
 *
 *   - Length prefix: 4-byte big-endian uint32. Encoded via DataView's
 *     setUint32(0, len, false) where false = big-endian. Matches
 *     Python's struct.pack(">I", len). ✓
 */

// ── Helpers ─────────────────────────────────────────────────────────

/**
 * Strip PEM markers + whitespace, base64-decode → DER bytes.
 * Throws if the PEM doesn't have the expected SubjectPublicKeyInfo
 * markers — better to fail loud than silently encrypt with garbage.
 */
function pemToDer(pem) {
  if (typeof pem !== 'string') {
    throw new Error('pemToDer: input must be a string');
  }
  const begin = '-----BEGIN PUBLIC KEY-----';
  const end = '-----END PUBLIC KEY-----';
  if (!pem.includes(begin) || !pem.includes(end)) {
    throw new Error('pemToDer: input is not a SubjectPublicKeyInfo PEM');
  }
  const b64 = pem
    .replace(begin, '')
    .replace(end, '')
    .replace(/\s+/g, '');
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) {
    out[i] = bin.charCodeAt(i);
  }
  return out;
}

/**
 * Base64-encode a Uint8Array. Implemented in chunks to avoid the
 * argument-count limit of String.fromCharCode(...big_array).
 *
 * For RSA-4096 ciphertext (~600 bytes total) the spread-operator
 * approach works, but using chunks keeps this safe even when a
 * future commit moves to a larger modulus or longer plaintext.
 */
function bytesToBase64(bytes) {
  const CHUNK = 0x8000; // 32KB — well below any browser's call-stack limit
  let binary = '';
  for (let i = 0; i < bytes.length; i += CHUNK) {
    const slice = bytes.subarray(i, i + CHUNK);
    binary += String.fromCharCode.apply(null, slice);
  }
  return btoa(binary);
}

/**
 * Import a SubjectPublicKeyInfo PEM as an RSA-OAEP-SHA256 public
 * key suitable for `crypto.subtle.encrypt`. extractable=false
 * because we never need to re-export the imported key.
 */
async function importRsaOaepPublicKey(pem) {
  const der = pemToDer(pem);
  return crypto.subtle.importKey(
    'spki',
    der,
    { name: 'RSA-OAEP', hash: 'SHA-256' },
    false,
    ['encrypt']
  );
}

// ── Main entry point ────────────────────────────────────────────────

/**
 * Encrypt a credentials object for delivery to the agent.
 *
 * @param {object} credentials — typically { username, password } but
 *   any JSON-serializable shape works; the agent decrypts and parses
 *   as JSON.
 * @param {string} publicKeyPem — SubjectPublicKeyInfo PEM, fetched
 *   from GET /api/agent-public-key.
 * @returns {Promise<string>} base64 ciphertext blob ready to POST
 *   to /api/owner/companies/{id}/filing-reps/{rep_id}/credentials
 *   as `encrypted_ciphertext`.
 */
export async function encryptCredentials(credentials, publicKeyPem) {
  // 1. Plaintext: JSON-encode the credentials dict.
  const plaintextStr = JSON.stringify(credentials);
  const plaintextBytes = new TextEncoder().encode(plaintextStr);

  // 2. Generate a fresh AES-256-GCM key + 12-byte nonce.
  //    extractable=true so we can export the raw key bytes for
  //    RSA wrapping.
  const aesKey = await crypto.subtle.generateKey(
    { name: 'AES-GCM', length: 256 },
    /* extractable */ true,
    ['encrypt']
  );
  const nonce = crypto.getRandomValues(new Uint8Array(12));

  // 3. Encrypt plaintext with AES-GCM. The tagLength:128 produces a
  //    16-byte auth tag appended to the ciphertext, matching
  //    cryptography.hazmat's AESGCM default.
  const aesCiphertextAB = await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv: nonce, tagLength: 128 },
    aesKey,
    plaintextBytes
  );
  const aesCiphertextAndTag = new Uint8Array(aesCiphertextAB);

  // 4. Export the raw 32-byte AES key and wrap it with RSA-OAEP.
  const aesKeyRaw = new Uint8Array(await crypto.subtle.exportKey('raw', aesKey));
  const publicKey = await importRsaOaepPublicKey(publicKeyPem);
  const wrappedKeyAB = await crypto.subtle.encrypt(
    { name: 'RSA-OAEP' },
    publicKey,
    aesKeyRaw
  );
  const wrappedKey = new Uint8Array(wrappedKeyAB);

  // 5. Build the blob: [4-byte BE wrapped-key length][wrapped_key]
  //    [12-byte nonce][aes_ct_and_tag]. Matches the layout in
  //    dob_worker/lib/crypto.py exactly.
  const blob = new Uint8Array(
    4 + wrappedKey.length + nonce.length + aesCiphertextAndTag.length
  );
  // Big-endian uint32. The `false` arg to setUint32 means BE.
  new DataView(blob.buffer).setUint32(0, wrappedKey.length, false);
  blob.set(wrappedKey, 4);
  blob.set(nonce, 4 + wrappedKey.length);
  blob.set(aesCiphertextAndTag, 4 + wrappedKey.length + nonce.length);

  return bytesToBase64(blob);
}

/**
 * SHA-256 fingerprint of a SubjectPublicKeyInfo PEM, hex-encoded.
 * Matches the backend's _compute_public_key_fingerprint output —
 * both hash the same DER bytes. The frontend rarely needs this
 * directly (the backend returns the fingerprint alongside the PEM
 * in /agent-public-key) but exposing it lets the operator UI show
 * a verification fingerprint or check for tampering.
 */
export async function publicKeyFingerprint(pem) {
  const der = pemToDer(pem);
  const hashAB = await crypto.subtle.digest('SHA-256', der);
  const bytes = new Uint8Array(hashAB);
  let hex = '';
  for (let i = 0; i < bytes.length; i++) {
    hex += bytes[i].toString(16).padStart(2, '0');
  }
  return hex;
}

// Default export for ergonomic single-import sites.
export default {
  encryptCredentials,
  publicKeyFingerprint,
};
