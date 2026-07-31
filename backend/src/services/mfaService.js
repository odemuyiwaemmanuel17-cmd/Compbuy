const { authenticator } = require('otplib');
const crypto = require('crypto');
const bcrypt = require('bcryptjs');
const QRCode = require('qrcode');
const { query } = require('../config/db');
const { encryptField, decryptField } = require('../utils/encryption');
const logger = require('./logger');

authenticator.options = { window: 1 };

const TOTP_ISSUER = process.env.TOTP_ISSUER || 'Compbuy';

/**
 * Generate MFA setup payload with QR code and backup codes
 */
async function generateSetupPayload(user) {
  const secret = authenticator.generateSecret();
  const email = user.email || user.data?.email;
  
  // Generate QR URI
  const uri = authenticator.keyuri(email, TOTP_ISSUER, secret);
  const qrDataUrl = await QRCode.toDataURL(uri);
  
  // Generate 10 backup codes (10 chars each)
  const backupCodes = [];
  const hashedCodes = [];
  
  for (let i = 0; i < 10; i++) {
    const code = crypto.randomBytes(5).toString('hex');
    backupCodes.push(code);
    const hashed = await bcrypt.hash(code, 10);
    hashedCodes.push(hashed);
  }
  
  return {
    secret,
    qrDataUrl,
    backupCodes,
    hashedCodes
  };
}

/**
 * Activate MFA for a user
 */
async function activateMfa(userId, secret, hashedBackupCodes, reason) {
  try {
    const encryptedSecret = encryptField(secret);
    
    await query(
      `UPDATE users 
       SET mfa_secret_encrypted = $2, 
           mfa_backup_codes_hash = $3,
           mfa_enabled = true,
           mfa_enforced_reason = $4,
           updated_at = NOW()
       WHERE id = $1`,
      [userId, encryptedSecret, hashedBackupCodes, reason || null]
    );
    
    logger.info('MFA activated', { userId, reason });
  } catch (err) {
    logger.error('Failed to activate MFA', { error: err.message, stack: err.stack });
    throw err;
  }
}

/**
 * Verify TOTP code
 */
async function verifyTotpCode(userId, code) {
  try {
    const result = await query(
      `SELECT mfa_secret_encrypted FROM users WHERE id = $1 AND mfa_enabled = true`,
      [userId]
    );
    
    if (result.rows.length === 0) {
      return false;
    }
    
    const encryptedSecret = result.rows[0].mfa_secret_encrypted;
    const secret = decryptField(encryptedSecret);
    
    if (!secret) {
      logger.error('Could not decrypt MFA secret', { userId });
      return false;
    }
    
    const isValid = authenticator.verify({ token: code, secret });
    return isValid;
  } catch (err) {
    logger.error('TOTP verification failed', { error: err.message });
    return false;
  }
}

/**
 * Verify and consume a backup code
 */
async function verifyBackupCode(userId, code) {
  try {
    const result = await query(
      `SELECT mfa_backup_codes_hash FROM users WHERE id = $1 AND mfa_enabled = true`,
      [userId]
    );
    
    if (result.rows.length === 0) {
      return false;
    }
    
    const hashedCodes = result.rows[0].mfa_backup_codes_hash;
    if (!hashedCodes || !Array.isArray(hashedCodes)) {
      return false;
    }
    
    // Find matching code
    let matchingIndex = -1;
    for (let i = 0; i < hashedCodes.length; i++) {
      const matches = await bcrypt.compare(code, hashedCodes[i]);
      if (matches) {
        matchingIndex = i;
        break;
      }
    }
    
    if (matchingIndex === -1) {
      return false;
    }
    
    // Remove used code (single-use)
    const newHashedCodes = hashedCodes.filter((_, idx) => idx !== matchingIndex);
    
    await query(
      `UPDATE users 
       SET mfa_backup_codes_hash = $2, updated_at = NOW()
       WHERE id = $1`,
      [userId, newHashedCodes]
    );
    
    logger.info('Backup code used', { userId, remainingCodes: newHashedCodes.length });
    return true;
  } catch (err) {
    logger.error('Backup code verification failed', { error: err.message });
    return false;
  }
}

/**
 * Disable MFA for a user
 */
async function disableMfa(userId) {
  try {
    await query(
      `UPDATE users 
       SET mfa_secret_encrypted = NULL,
           mfa_backup_codes_hash = NULL,
           mfa_enabled = false,
           mfa_enforced_reason = NULL,
           updated_at = NOW()
       WHERE id = $1`,
      [userId]
    );
    
    logger.info('MFA disabled', { userId });
  } catch (err) {
    logger.error('Failed to disable MFA', { error: err.message, stack: err.stack });
    throw err;
  }
}

/**
 * Check if MFA is required for this user/context
 */
function mfaRequiredFor(user, context) {
  const HIGH_VALUE_THRESHOLD = parseInt(process.env.HIGH_VALUE_THRESHOLD_NGN, 10) || 100000000;
  
  // Sellers always require MFA if enabled
  if (process.env.MFA_REQUIRED_FOR_SELLERS === 'true' && 
      (user.role === 'seller' || user.role === 'broker')) {
    return 'seller_role';
  }
  
  // High value transactions
  if (process.env.MFA_REQUIRED_FOR_HIGH_VALUE === 'true' && 
      context?.amount >= HIGH_VALUE_THRESHOLD) {
    return 'high_value_threshold';
  }
  
  return null;
}

module.exports = {
  generateSetupPayload,
  activateMfa,
  verifyTotpCode,
  verifyBackupCode,
  disableMfa,
  mfaRequiredFor
};
