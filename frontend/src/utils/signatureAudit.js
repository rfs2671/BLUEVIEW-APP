import * as Device from 'expo-device';
import { Platform } from 'react-native';
import apiClient from './api';
 
// Cache hardware fingerprint — it doesn't change during a session
let _cachedFingerprint = null;
 
/**
 * Get the hardware fingerprint for this device.
 * Combines multiple expo-device fields into a stable identifier.
 */
export async function getDeviceFingerprint() {
  if (_cachedFingerprint) return _cachedFingerprint;
 
  try {
    const fingerprint = {
      brand: Device.brand,
      modelName: Device.modelName,
      modelId: Device.modelId,
      osName: Device.osName,
      osVersion: Device.osVersion,
      deviceName: Device.deviceName,
      platform: Platform.OS,
      // Device.deviceId is not available on all platforms
      // so we build a composite fingerprint
      composite: [
        Device.brand,
        Device.modelName,
        Device.osName,
        Device.osVersion,
        Platform.OS,
      ].filter(Boolean).join('|'),
    };
 
    _cachedFingerprint = fingerprint;
    return fingerprint;
  } catch (e) {
    console.warn('Could not get device fingerprint:', e);
    return {
      platform: Platform.OS,
      composite: `${Platform.OS}|unknown`,
    };
  }
}
 
/**
 * Build the device_info payload for a signature event.
 * @param {object} user - The current user from AuthContext
 */
export async function buildDeviceInfo(user) {
  const fingerprint = await getDeviceFingerprint();
 
  return {
    site_device_id: user?.site_device_id || user?.id || null,
    hardware_fingerprint: fingerprint.composite,
    device_details: fingerprint,
    user_agent: Platform.OS === 'web' ? navigator?.userAgent : null,
  };
}
 
/**
 * Record a signature event in the audit ledger.
 *
 * @param {object} params
 * @param {string} params.documentType - "logbook" | "daily_log" | "worker_registration"
 * @param {string} params.documentId - MongoDB _id of the parent document
 * @param {string} params.eventType - "cp_sign" | "superintendent_sign" | "worker_sign"
 * @param {string} params.signerName - Name of the person signing
 * @param {string} params.signerRole - "cp" | "site_device" | "worker" | "admin"
 * @param {object} params.signatureData - The actual signature {paths, signerName, timestamp} or base64
 * @param {object} params.contentSnapshot - Full JSON state of the document at sign-time
 * @param {object} params.user - Current user from AuthContext
 *
 * @returns {string|null} The event_id if successful, null on failure
 */
// Tier 1 (4): the CAPACITY a person signs in, distinct from their login role.
// Derived from the sign context so §3301.13.13 "signed as Superintendent" is
// recorded on every event even without per-editor changes; an explicit
// actingCapacity (e.g. "Competent Person - Excavation") always wins.
function deriveActingCapacity(eventType, signerRole) {
  if (eventType === 'superintendent_sign') return 'Construction Superintendent';
  if (eventType === 'ssc_sign') return 'Site Safety Coordinator/Manager';
  if (eventType === 'cp_sign') return 'Competent Person';
  if (signerRole === 'superintendent') return 'Construction Superintendent';
  if (signerRole === 'ssc') return 'Site Safety Coordinator/Manager';
  if (signerRole === 'cp') return 'Competent Person';
  return signerRole || 'Signer';
}

export async function recordSignatureEvent({
  documentType,
  documentId,
  eventType,
  signerName,
  signerRole,
  signatureData,
  contentSnapshot,
  actingCapacity,
  user,
}) {
  // ── A WRITE THAT NEVER HAPPENS IS NOT SILENCE ─────────────────────────────
  //
  // EVERY CALLER GUARDS ON `if (docId)` AND SKIPS. That guard is right — a
  // POST with a null document_id would write a ledger row pointing at nothing —
  // but the skip itself was reported by absolutely nothing, and it is not a
  // rare branch. It is THE OFFLINE PATH: no server id means the push did not
  // land, the log is filed from the local draft later by draftSync, and
  // draftSync has never recorded a signature event. So the single most likely
  // way to produce a signed logbook with no ledger row left no trace at all,
  // on the device or on the server.
  //
  // The durable half of this is server-side (sweep_signature_ledger_gaps finds
  // exactly these the following night). This half is so that a device log,
  // when someone does have one, says which record it was about.
  if (!documentId) {
    console.error(
      '[signature-ledger] SKIPPED — no server id for the document, so no '
      + 'ledger event was attempted. This signature is filed with no audit '
      + 'row unless something records it later.',
      { documentType, eventType, signerName, signerRole },
    );
    return null;
  }

  try {
    const deviceInfo = await buildDeviceInfo(user);

    const payload = {
      document_type: documentType,
      document_id: documentId,
      event_type: eventType,
      signer_name: signerName,
      signer_role: signerRole,
      // Tier 1 (4): explicit capacity wins; otherwise derived from the context.
      acting_capacity: actingCapacity || deriveActingCapacity(eventType, signerRole),
      signature_data: signatureData,
      content_snapshot: contentSnapshot,
      device_info: deviceInfo,
    };
 
    const response = await apiClient.post('/api/signature-events', payload);
    return response.data?.event_id || null;
  } catch (error) {
    // ── THE FAILURE NOW SAYS WHAT IT WAS FOR ────────────────────────────────
    //
    // This was `console.error('Failed to record signature event:', error)`.
    // It named no document, no signer and no event type, so even on a device
    // whose console someone could read, the line could not be tied to a
    // record — which is the same problem the missing ledger row has, one layer
    // up. Tagged [signature-ledger] to match the server, so one grep spans
    // both sides.
    //
    // STILL NON-BLOCKING, AND STILL RESOLVING WITH null. The contract is
    // deliberate: the signature saves on the document either way and a CP must
    // never be refused his filed log over an audit write. But `null` IS the
    // failure report, and a caller that discards it discards the only thing
    // this function can tell it — see the note at the awaited call site in
    // site_superintendent_log.jsx.
    console.error(
      '[signature-ledger] WRITE FAILED — this signature has no audit row.',
      {
        documentType,
        documentId,
        eventType,
        signerName,
        signerRole,
        status: error?.response?.status ?? null,
        message: error?.message,
      },
    );
    return null;
  }
}
 
/**
 * Verify the integrity of all signatures on a document.
 *
 * @param {string} documentType
 * @param {string} documentId
 * @returns {object} Verification result from the backend
 */
export async function verifySignatureIntegrity(documentType, documentId) {
  try {
    const response = await apiClient.get(
      `/api/signature-events/verify/${documentType}/${documentId}`
    );
    return response.data;
  } catch (error) {
    console.error('Failed to verify signature integrity:', error);
    return null;
  }
}
 
/**
 * Get the audit trail for a document.
 *
 * @param {string} documentType
 * @param {string} documentId
 * @returns {object} Audit events from the backend
 */
export async function getAuditTrail(documentType, documentId) {
  try {
    const response = await apiClient.get(
      `/api/signature-events/document/${documentType}/${documentId}`
    );
    return response.data;
  } catch (error) {
    console.error('Failed to get audit trail:', error);
    return null;
  }
}
