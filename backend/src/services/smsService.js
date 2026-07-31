const crypto = require('crypto');
const bcrypt = require('bcryptjs');
const { query } = require('../config/db');
const logger = require('./logger');

const SMS_PROVIDER = process.env.SMS_PROVIDER;
const TERMII_API_KEY = process.env.TERMII_API_KEY;
const TERMII_SENDER_ID = process.env.TERMII_SENDER_ID || 'Compbuy';

/**
 * Issue an OTP to a user's phone
 */
async function issueOtp(userId, phone, purpose) {
  // Generate 6-digit OTP
  const otp = crypto.randomInt(100000, 999999).toString();
  
  // Hash the OTP
  const saltRounds = parseInt(process.env.BCRYPT_SALT_ROUNDS, 10) || 13;
  const otpHash = await bcrypt.hash(otp, saltRounds);
  
  // Store hash with 10min expiry
  const expiry = new Date(Date.now() + 10 * 60 * 1000);
  
  try {
    await query(
      `UPDATE users 
       SET phone_otp_hash = $2, 
           phone_otp_expiry = $3,
           updated_at = NOW()
       WHERE id = $1`,
      [userId, otpHash, expiry]
    );
    
    // Send via Termii if configured
    if (TERMII_API_KEY && SMS_PROVIDER === 'termii') {
      try {
        const message = `Your Compbuy verification code is: ${otp}. Valid for 10 minutes. Do not share this code.`;
        
        const response = await fetch('https://api.termii.com/api/sms/send', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'api_key': TERMII_API_KEY
          },
          body: JSON.stringify({
            to: phone,
            from: TERMII_SENDER_ID,
            sms: message,
            type: 'plain'
          })
        });
        
        const result = await response.json();
        logger.info('OTP sent via Termii', { userId, phone, success: result.response_code === 'SUCCESS' });
      } catch (err) {
        logger.error('Termii send failed', { error: err.message });
      }
    } else {
      // Log for development
      if (process.env.NODE_ENV !== 'production') {
        logger.warn(`[DEV OTP] User ${userId}: ${otp}`);
      } else {
        logger.warn('SMS provider not configured', { userId, phone });
      }
    }
    
    return true;
  } catch (err) {
    logger.error('Failed to issue OTP', { error: err.message, stack: err.stack });
    throw err;
  }
}

/**
 * Verify an OTP
 */
async function verifyOtp(userId, otpInput) {
  try {
    const result = await query(
      `SELECT phone_otp_hash, phone_otp_expiry FROM users WHERE id = $1`,
      [userId]
    );
    
    if (result.rows.length === 0) {
      return { valid: false, reason: 'User not found' };
    }
    
    const { phone_otp_hash: otpHash, phone_otp_expiry: expiry } = result.rows[0];
    
    if (!otpHash) {
      return { valid: false, reason: 'No OTP issued' };
    }
    
    if (expiry && new Date(expiry) < new Date()) {
      return { valid: false, reason: 'OTP expired' };
    }
    
    const isValid = await bcrypt.compare(otpInput, otpHash);
    
    if (!isValid) {
      return { valid: false, reason: 'Invalid OTP' };
    }
    
    // Clear OTP fields and mark phone as verified
    await query(
      `UPDATE users 
       SET phone_otp_hash = NULL,
           phone_otp_expiry = NULL,
           phone_verified = true,
           updated_at = NOW()
       WHERE id = $1`,
      [userId]
    );
    
    logger.info('OTP verified', { userId });
    return { valid: true };
  } catch (err) {
    logger.error('OTP verification failed', { error: err.message });
    return { valid: false, reason: 'Verification error' };
  }
}

module.exports = { issueOtp, verifyOtp };
