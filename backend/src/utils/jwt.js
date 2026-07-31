const jwt = require('jsonwebtoken');
const crypto = require('crypto');
const { query } = require('../config/db');
const logger = require('./logger');

const ACCESS_SECRET = process.env.JWT_SECRET;
const REFRESH_SECRET = process.env.JWT_REFRESH_SECRET;
const STEPUP_SECRET = process.env.JWT_STEPUP_SECRET;
const ISSUER = process.env.JWT_ISSUER || 'compbuy.ng';
const AUDIENCE = process.env.JWT_AUDIENCE || 'compbuy-app';

if (!ACCESS_SECRET || !REFRESH_SECRET || !STEPUP_SECRET) {
  logger.warn('JWT secrets not fully configured');
}

function signAccessToken(payload) {
  return jwt.sign(payload, ACCESS_SECRET, {
    expiresIn: process.env.JWT_EXPIRES_IN || '15m',
    issuer: ISSUER,
    audience: AUDIENCE
  });
}

async function signRefreshToken(userId, deviceId, ip, riskScore) {
  const payload = { sub: userId, deviceId };
  const token = jwt.sign(payload, REFRESH_SECRET, {
    expiresIn: process.env.JWT_REFRESH_EXPIRES_IN || '30d',
    issuer: ISSUER,
    audience: AUDIENCE
  });
  
  // Hash the token for storage
  const tokenHash = crypto.createHash('sha256').update(token).digest('hex');
  const expiresAt = new Date(Date.now() + 30 * 24 * 60 * 60 * 1000);
  
  await query(
    `INSERT INTO sessions (user_id, device_id, refresh_token_hash, ip_address, risk_score_at_login, expires_at)
     VALUES ($1, $2, $3, $4, $5, $6)`,
    [userId, deviceId, tokenHash, ip, riskScore || 0, expiresAt]
  );
  
  return token;
}

function signStepUpToken(userId, scope) {
  return jwt.sign({ sub: userId, scope, stepup: true }, STEPUP_SECRET, {
    expiresIn: process.env.JWT_STEPUP_EXPIRES_IN || '5m',
    issuer: ISSUER,
    audience: AUDIENCE
  });
}

function verifyAccessToken(token) {
  try {
    return jwt.verify(token, ACCESS_SECRET, {
      issuer: ISSUER,
      audience: AUDIENCE
    });
  } catch (err) {
    if (err.name === 'TokenExpiredError') {
      err.code = 'TOKEN_EXPIRED';
    }
    throw err;
  }
}

async function verifyRefreshToken(token) {
  let decoded;
  try {
    decoded = jwt.verify(token, REFRESH_SECRET, {
      issuer: ISSUER,
      audience: AUDIENCE
    });
  } catch (err) {
    if (err.name === 'TokenExpiredError') {
      err.code = 'TOKEN_EXPIRED';
    }
    throw err;
  }
  
  const tokenHash = crypto.createHash('sha256').update(token).digest('hex');
  
  const result = await query(
    `SELECT s.id as session_id, s.user_id, s.device_id 
     FROM sessions s
     WHERE s.refresh_token_hash = $1 
       AND s.status = 'active'
       AND s.expires_at > NOW()`,
    [tokenHash]
  );
  
  if (result.rows.length === 0) {
    const err = new Error('Invalid or revoked refresh token');
    err.code = 'INVALID_TOKEN';
    throw err;
  }
  
  return {
    userId: decoded.sub,
    deviceId: decoded.deviceId,
    sessionId: result.rows[0].session_id
  };
}

function verifyStepUpToken(token, requiredScope) {
  try {
    const decoded = jwt.verify(token, STEPUP_SECRET, {
      issuer: ISSUER,
      audience: AUDIENCE
    });
    
    if (!decoded.stepup) {
      const err = new Error('Not a step-up token');
      err.code = 'INVALID_STEPUP';
      throw err;
    }
    
    if (requiredScope && decoded.scope !== requiredScope) {
      const err = new Error('Step-up token scope mismatch');
      err.code = 'STEPUP_SCOPE_MISMATCH';
      throw err;
    }
    
    return decoded;
  } catch (err) {
    if (err.name === 'TokenExpiredError') {
      err.code = 'STEPUP_EXPIRED';
    }
    throw err;
  }
}

async function revokeRefreshToken(token, reason) {
  try {
    const tokenHash = crypto.createHash('sha256').update(token).digest('hex');
    await query(
      `UPDATE sessions 
       SET status = 'revoked', revoked_at = NOW(), revoked_reason = $2 
       WHERE refresh_token_hash = $1 AND status = 'active'`,
      [tokenHash, reason || 'user_logout']
    );
  } catch (err) {
    logger.error('Failed to revoke refresh token', { error: err.message });
  }
}

async function revokeAllUserSessions(userId, reason) {
  try {
    await query(
      `UPDATE sessions 
       SET status = 'revoked', revoked_at = NOW(), revoked_reason = $2 
       WHERE user_id = $1 AND status = 'active'`,
      [userId, reason || 'security_revocation']
    );
  } catch (err) {
    logger.error('Failed to revoke all user sessions', { error: err.message });
  }
}

module.exports = {
  signAccessToken,
  signRefreshToken,
  signStepUpToken,
  verifyAccessToken,
  verifyRefreshToken,
  verifyStepUpToken,
  revokeRefreshToken,
  revokeAllUserSessions
};
