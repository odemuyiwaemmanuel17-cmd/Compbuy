const { asyncHandler } = require('../middleware/errorHandler');
const { query } = require('../config/db');
const { recordAuditEvent } = require('../services/auditChain');
const { hashFile } = require('../middleware/security');
const { sendKycStatusEmail } = require('../services/emailService');
const { approveDocument, rejectDocument, submitNationalIdentifiers } = require('../services/kycService');
const logger = require('../utils/logger');

/**
 * Submit national ID (BVN/NIN)
 */
const submitNationalId = asyncHandler(async (req, res) => {
  await submitNationalIdentifiers(req.user.id, req.body);
  res.status(202).json({ success: true, message: 'National identifiers submitted for verification' });
});

/**
 * Upload KYC document
 */
const uploadDocument = asyncHandler(async (req, res) => {
  if (!req.file) {
    return res.status(400).json({ success: false, message: 'No file uploaded' });
  }
  
  const filePath = req.file.path;
  const fileHash = hashFile(filePath);
  
  // Check for cross-user hash collision (potential fraud)
  const existing = await query(
    `SELECT user_id FROM kyc_documents WHERE file_hash_sha256 = $1 AND user_id != $2`,
    [fileHash, req.user.id]
  );
  
  if (existing.rows.length > 0) {
    logger.warn('Potential document fraud detected', { userId: req.user.id, duplicateUserId: existing.rows[0].user_id, fileHash });
  }
  
  const result = await query(
    `INSERT INTO kyc_documents (user_id, doc_type, file_path, file_hash_sha256, mime_type, file_size, status)
     VALUES ($1, $2, $3, $4, $5, $6, 'pending')
     RETURNING id`,
    [req.user.id, req.body.doc_type || 'general', filePath, fileHash, req.file.mimetype, req.file.size]
  );
  
  recordAuditEvent({ actorId: req.user.id, action: 'KYC_DOCUMENT_UPLOADED', entityType: 'kyc_document', entityId: result.rows[0].id, metadata: { docType: req.body.doc_type }, ip: req.ip });
  
  res.status(201).json({ success: true, document_id: result.rows[0].id });
});

/**
 * Get KYC status
 */
const getStatus = asyncHandler(async (req, res) => {
  const userResult = await query(
    `SELECT kyc_tier, email_verified, phone_verified, govt_id_verified, liveness_check_passed, bvn_verified, nin_verified
     FROM users WHERE id = $1`,
    [req.user.id]
  );
  
  const docsResult = await query(
    `SELECT id, doc_type, status, rejection_reason, created_at FROM kyc_documents WHERE user_id = $1 ORDER BY created_at DESC`,
    [req.user.id]
  );
  
  res.json({ 
    success: true, 
    tier: userResult.rows[0]?.kyc_tier || 'tier0_unverified',
    flags: userResult.rows[0] || {},
    documents: docsResult.rows 
  });
});

/**
 * Get review queue (admin only)
 */
const getReviewQueue = asyncHandler(async (req, res) => {
  const result = await query(
    `SELECT d.id, d.doc_type, d.file_path, d.file_hash_sha256, d.mime_type, d.file_size, d.status, d.created_at,
            u.id as user_id, u.email, u.first_name, u.last_name
     FROM kyc_documents d
     JOIN users u ON d.user_id = u.id
     WHERE d.status = 'pending'
     ORDER BY d.created_at ASC`,
    []
  );
  
  res.json({ success: true, documents: result.rows });
});

/**
 * Approve document (admin only)
 */
const approveDocumentHandler = asyncHandler(async (req, res) => {
  await approveDocument(req.params.id, req.user.id);
  
  // Get document info for email
  const docResult = await query(
    `SELECT user_id FROM kyc_documents WHERE id = $1`,
    [req.params.id]
  );
  
  if (docResult.rows.length > 0) {
    const userResult = await query(`SELECT email, first_name FROM users WHERE id = $1`, [docResult.rows[0].user_id]);
    if (userResult.rows.length > 0) {
      sendKycStatusEmail(userResult.rows[0], 'approved', null).catch(err => logger.error('Failed to send approval email', { error: err.message }));
    }
  }
  
  res.json({ success: true });
});

/**
 * Reject document (admin only)
 */
const rejectDocumentHandler = asyncHandler(async (req, res) => {
  const { reason } = req.body;
  
  if (!reason) {
    return res.status(400).json({ success: false, message: 'Rejection reason required' });
  }
  
  await rejectDocument(req.params.id, req.user.id, reason);
  
  // Get document info for email
  const docResult = await query(
    `SELECT user_id FROM kyc_documents WHERE id = $1`,
    [req.params.id]
  );
  
  if (docResult.rows.length > 0) {
    const userResult = await query(`SELECT email, first_name FROM users WHERE id = $1`, [docResult.rows[0].user_id]);
    if (userResult.rows.length > 0) {
      sendKycStatusEmail(userResult.rows[0], 'rejected', reason).catch(err => logger.error('Failed to send rejection email', { error: err.message }));
    }
  }
  
  res.json({ success: true });
});

module.exports = {
  submitNationalId,
  uploadDocument,
  getStatus,
  getReviewQueue,
  approveDocumentHandler,
  rejectDocumentHandler
};
