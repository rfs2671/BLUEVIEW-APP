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
export async function recordSignatureEvent({
  documentType,
  documentId,
  eventType,
  signerName,
  signerRole,
  signatureData,
  contentSnapshot,
  user,
}) {
  try {
    const deviceInfo = await buildDeviceInfo(user);
 
    const payload = {
      document_type: documentType,
      document_id: documentId,
      event_type: eventType,
      signer_name: signerName,
      signer_role: signerRole,
      signature_data: signatureData,
      content_snapshot: contentSnapshot,
      device_info: deviceInfo,
    };
 
    const response = await apiClient.post('/api/signature-events', payload);
    return response.data?.event_id || null;
  } catch (error) {
    console.error('Failed to record signature event:', error);
    // Non-blocking — the signature still saves on the document.
    // The audit trail entry will be missing, but the app doesn't break.
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
