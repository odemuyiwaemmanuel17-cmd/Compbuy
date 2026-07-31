const crypto = require('crypto');
const logger = require('./logger');

const FIELD_ENCRYPTION_KEY = process.env.FIELD_ENCRYPTION_KEY;

if (!FIELD_ENCRYPTION_KEY) {
  logger.warn('FIELD_ENCRYPTION_KEY not set - encryption will fail');
} else if (Buffer.from(FIELD_ENCRYPTION_KEY, 'hex').length !== 32 && process.env.NODE_ENV !== 'test') {
  logger.warn('FIELD_ENCRYPTION_KEY should be 32 bytes (64 hex chars)');
}

const KEY = FIELD_ENCRYPTION_KEY ? Buffer.from(FIELD_ENCRYPTION_KEY, 'hex') : Buffer.alloc(32);

/**
 * Encrypt a field value using AES-256-GCM
 * Output format: [iv(12)][authTag(16)][ciphertext]
 */
function encryptField(plaintext) {
  if (!plaintext || plaintext === '') return null;
  
  const iv = crypto.randomBytes(12);
  const cipher = crypto.createCipheriv('aes-256-gcm', KEY, iv);
  
  let ciphertext = cipher.update(String(plaintext), 'utf8', 'binary');
  ciphertext += cipher.final('binary');
  
  const authTag = cipher.getAuthTag();
  
  // Combine: iv + authTag + ciphertext
  const result = Buffer.concat([iv, authTag, Buffer.from(ciphertext, 'binary')]);
  return result;
}

/**
 * Decrypt a field value
 */
function decryptField(buffer) {
  if (!buffer) return null;
  
  if (typeof buffer === 'string') {
    buffer = Buffer.from(buffer, 'hex');
  }
  
  if (buffer.length < 28) {
    logger.error('Invalid encrypted buffer length', { length: buffer.length });
    return null;
  }
  
  const iv = buffer.slice(0, 12);
  const authTag = buffer.slice(12, 28);
  const ciphertext = buffer.slice(28);
  
  try {
    const decipher = crypto.createDecipheriv('aes-256-gcm', KEY, iv);
    decipher.setAuthTag(authTag);
    
    let plaintext = decipher.update(ciphertext, 'binary', 'utf8');
    plaintext += decipher.final('utf8');
    
    return plaintext;
  } catch (err) {
    logger.error('Decryption failed', { error: err.message });
    return null;
  }
}

/**
 * Create a hash for lookup purposes (e.g., email normalization)
 */
function hashForLookup(plaintext) {
  const combined = String(plaintext) + (process.env.JWT_SECRET || '');
  return crypto.createHash('sha256').update(combined).digest('hex');
}

/**
 * Mask a value showing only last N characters
 */
function maskValue(plaintext, visibleDigits = 4) {
  if (!plaintext) return '';
  const str = String(plaintext);
  if (str.length <= visibleDigits) return str;
  const masked = '•'.repeat(str.length - visibleDigits) + str.slice(-visibleDigits);
  return masked;
}

module.exports = { encryptField, decryptField, hashForLookup, maskValue };
