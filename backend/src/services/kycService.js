const { query } = require('../config/db');
const { recordAuditEvent } = require('./auditChain');
const logger = require('./logger');

// KYC tier hierarchy
const TIER_ORDER = [
  'tier0_unverified',
  'tier1_email_phone',
  'tier2_id_verified',
  'tier3_financial_verified',
  'tier4_enhanced_dd'
];

/**
 * Check if user meets required tier
 */
function meetsTier(userTier, requiredTier) {
  const userIndex = TIER_ORDER.indexOf(userTier);
  const requiredIndex = TIER_ORDER.indexOf(requiredTier);
  return userIndex >= requiredIndex;
}

/**
 * Submit national identifiers (BVN/NIN)
 */
async function submitNationalIdentifiers(userId, { bvn, nin }) {
  const { encryptField } = require('../utils/encryption');
  
  try {
    const updates = [];
    const params = [];
    let paramIdx = 1;
    
    if (bvn) {
      updates.push(`bvn_encrypted = $${paramIdx}`);
      params.push(encryptField(bvn));
      paramIdx++;
      updates.push(`bvn_verified = false`);
    }
    
    if (nin) {
      updates.push(`nin_encrypted = $${paramIdx}`);
      params.push(encryptField(nin));
      paramIdx++;
      updates.push(`nin_verified = false`);
    }
    
    updates.push(`updated_at = NOW()`);
    params.push(userId);
    
    await query(
      `UPDATE users SET ${updates.join(', ')} WHERE id = $${paramIdx}`,
      params
    );
    
    await recordAuditEvent({
      actorId: userId,
      action: 'KYC_NATIONAL_ID_SUBMITTED',
      entityType: 'user',
      entityId: userId,
      metadata: { bvnSubmitted: !!bvn, ninSubmitted: !!nin },
      ip: ''
    });
    
    return true;
  } catch (err) {
    logger.error('Failed to submit national identifiers', { error: err.message, stack: err.stack });
    throw err;
  }
}

/**
 * Approve a KYC document
 */
async function approveDocument(documentId, reviewerId) {
  const client = await require('../config/db').getClient();
  
  try {
    await client.query('BEGIN');
    
    // Update document status
    await client.query(
      `UPDATE kyc_documents 
       SET status = 'approved', reviewed_by = $2, reviewed_at = NOW()
       WHERE id = $1`,
      [documentId, reviewerId]
    );
    
    // Get document info
    const docResult = await client.query(
      `SELECT user_id, doc_type FROM kyc_documents WHERE id = $1`,
      [documentId]
    );
    
    if (docResult.rows.length > 0) {
      const { user_id: userId, doc_type } = docResult.rows[0];
      
      // Update user flags based on doc type
      if (doc_type === 'govt_id' || doc_type === 'international_passport' || doc_type === 'drivers_license') {
        await client.query(
          `UPDATE users SET govt_id_verified = true, updated_at = NOW() WHERE id = $1`,
          [userId]
        );
      } else if (doc_type === 'selfie_liveness') {
        await client.query(
          `UPDATE users SET liveness_check_passed = true, liveness_checked_at = NOW(), updated_at = NOW() WHERE id = $1`,
          [userId]
        );
      } else if (doc_type === 'cac_certificate') {
        // CAC verified at listing level typically
      } else if (doc_type === 'bank_statement' || doc_type === 'audited_accounts') {
        // Financial verification
      }
      
      // Recalculate tier
      await recalculateUserTierInternal(client, userId);
      
      await recordAuditEvent({
        actorId: reviewerId,
        action: 'KYC_DOCUMENT_APPROVED',
        entityType: 'kyc_document',
        entityId: documentId,
        metadata: { userId, docType: doc_type },
        ip: ''
      });
    }
    
    await client.query('COMMIT');
    
    return true;
  } catch (err) {
    await client.query('ROLLBACK');
    logger.error('Failed to approve document', { error: err.message, stack: err.stack });
    throw err;
  } finally {
    client.release();
  }
}

/**
 * Reject a KYC document
 */
async function rejectDocument(documentId, reviewerId, reason) {
  try {
    await query(
      `UPDATE kyc_documents 
       SET status = 'rejected', reviewed_by = $2, reviewed_at = NOW(), rejection_reason = $3
       WHERE id = $1`,
      [documentId, reviewerId, reason]
    );
    
    const docResult = await query(
      `SELECT user_id, doc_type FROM kyc_documents WHERE id = $1`,
      [documentId]
    );
    
    if (docResult.rows.length > 0) {
      await recordAuditEvent({
        actorId: reviewerId,
        action: 'KYC_DOCUMENT_REJECTED',
        entityType: 'kyc_document',
        entityId: documentId,
        metadata: { userId: docResult.rows[0].user_id, docType: docResult.rows[0].doc_type, reason },
        ip: ''
      });
    }
    
    return true;
  } catch (err) {
    logger.error('Failed to reject document', { error: err.message, stack: err.stack });
    throw err;
  }
}

/**
 * Internal tier recalculation (within transaction)
 */
async function recalculateUserTierInternal(client, userId) {
  const result = await client.query(
    `SELECT email_verified, phone_verified, govt_id_verified, liveness_check_passed, bvn_verified, nin_verified
     FROM users WHERE id = $1`,
    [userId]
  );
  
  if (result.rows.length === 0) return 'tier0_unverified';
  
  const user = result.rows[0];
  let newTier = 'tier0_unverified';
  
  // Tier 1: email and phone verified
  if (user.email_verified && user.phone_verified) {
    newTier = 'tier1_email_phone';
  }
  
  // Tier 2: + govt_id AND liveness AND (bvn OR nin)
  if (newTier === 'tier1_email_phone' && 
      user.govt_id_verified && 
      user.liveness_check_passed && 
      (user.bvn_verified || user.nin_verified)) {
    newTier = 'tier2_id_verified';
  }
  
  // Tier 3: + CAC certificate approved AND (audited_accounts OR bank_statement approved)
  // This requires checking kyc_documents table
  if (newTier === 'tier2_id_verified') {
    const docsResult = await client.query(
      `SELECT ARRAY_AGG(doc_type) FILTER (WHERE status = 'approved') as approved_docs
       FROM kyc_documents WHERE user_id = $1`,
      [userId]
    );
    
    const approvedDocs = docsResult.rows[0].approved_docs || [];
    const hasCAC = approvedDocs.some(d => d === 'cac_certificate');
    const hasFinancials = approvedDocs.some(d => d === 'audited_accounts' || d === 'bank_statement');
    
    if (hasCAC && hasFinancials) {
      newTier = 'tier3_financial_verified';
    }
  }
  
  // Tier 4: + enhanced DD attestation
  if (newTier === 'tier3_financial_verified') {
    const ddResult = await client.query(
      `SELECT COUNT(*) FROM kyc_documents 
       WHERE user_id = $1 AND doc_type = 'enhanced_dd_attestation' AND status = 'approved'`,
      [userId]
    );
    
    if (parseInt(ddResult.rows[0].count, 10) > 0) {
      newTier = 'tier4_enhanced_dd';
    }
  }
  
  await client.query(
    `UPDATE users SET kyc_tier = $2, updated_at = NOW() WHERE id = $1`,
    [userId, newTier]
  );
  
  return newTier;
}

/**
 * Recalculate user tier (public method)
 */
async function recalculateUserTier(userId) {
  const client = await require('../config/db').getClient();
  try {
    await client.query('BEGIN');
    const newTier = await recalculateUserTierInternal(client, userId);
    await client.query('COMMIT');
    return newTier;
  } catch (err) {
    await client.query('ROLLBACK');
    throw err;
  } finally {
    client.release();
  }
}

/**
 * Express middleware to require minimum KYC tier
 */
function requireTier(requiredTier) {
  return (req, res, next) => {
    if (!req.user) {
      return res.status(401).json({ success: false, message: 'Authentication required' });
    }
    
    if (!meetsTier(req.user.kyc_tier, requiredTier)) {
      return res.status(403).json({
        success: false,
        code: 'KYC_TIER_INSUFFICIENT',
        currentTier: req.user.kyc_tier,
        requiredTier
      });
    }
    
    next();
  };
}

module.exports = {
  meetsTier,
  submitNationalIdentifiers,
  approveDocument,
  rejectDocument,
  recalculateUserTier,
  requireTier
};
