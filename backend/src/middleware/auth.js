const { verifyAccessToken, verifyStepUpToken } = require('../utils/jwt');
const { query } = require('../config/db');
const logger = require('./logger');

/**
 * Authenticate user via Bearer token
 */
async function authenticate(req, res, next) {
  try {
    const authHeader = req.headers.authorization;
    if (!authHeader || !authHeader.startsWith('Bearer ')) {
      return res.status(401).json({ success: false, message: 'Authentication required' });
    }
    
    const token = authHeader.split(' ')[1];
    const decoded = verifyAccessToken(token);
    
    // Fetch user from DB
    const result = await query(
      `SELECT id, email, first_name, last_name, role, kyc_tier, mfa_enabled, 
              is_active, is_suspended, suspension_reason, email_verified, phone_verified,
              trust_score, risk_level
       FROM users WHERE id = $1`,
      [decoded.sub]
    );
    
    if (result.rows.length === 0) {
      return res.status(401).json({ success: false, message: 'User not found' });
    }
    
    const user = result.rows[0];
    
    if (!user.is_active) {
      return res.status(403).json({ success: false, message: 'Account deactivated' });
    }
    
    if (user.is_suspended) {
      return res.status(403).json({ 
        success: false, 
        message: 'Account suspended',
        reason: user.suspension_reason 
      });
    }
    
    req.user = user;
    next();
  } catch (err) {
    if (err.code === 'TOKEN_EXPIRED') {
      return res.status(401).json({ success: false, code: 'TOKEN_EXPIRED', message: 'Token expired' });
    }
    if (err.name === 'JsonWebTokenError' || err.code === 'INVALID_TOKEN') {
      return res.status(401).json({ success: false, message: 'Invalid token' });
    }
    next(err);
  }
}

/**
 * Authorize based on roles
 */
function authorize(...roles) {
  return (req, res, next) => {
    if (!req.user) {
      return res.status(401).json({ success: false, message: 'Authentication required' });
    }
    
    if (!roles.includes(req.user.role)) {
      return res.status(403).json({ 
        success: false, 
        message: 'Insufficient permissions',
        requiredRoles: roles 
      });
    }
    
    next();
  };
}

/**
 * Require step-up authentication for sensitive operations
 */
function requireStepUp(scope) {
  return (req, res, next) => {
    const stepUpToken = req.headers['x-stepup-token'];
    
    if (!stepUpToken) {
      return res.status(403).json({ 
        success: false, 
        code: 'STEPUP_REQUIRED',
        message: 'Step-up authentication required' 
      });
    }
    
    try {
      const decoded = verifyStepUpToken(stepUpToken, scope);
      req.stepUpVerified = true;
      req.stepUpScope = scope;
      next();
    } catch (err) {
      if (err.code === 'STEPUP_EXPIRED') {
        return res.status(403).json({ 
          success: false, 
          code: 'STEPUP_EXPIRED',
          message: 'Step-up token expired' 
        });
      }
      return res.status(403).json({ 
        success: false, 
        code: 'STEPUP_INVALID',
        message: 'Invalid step-up token' 
      });
    }
  };
}

/**
 * Optional authentication - sets req.user if valid, never blocks
 */
async function optionalAuth(req, res, next) {
  try {
    const authHeader = req.headers.authorization;
    if (!authHeader || !authHeader.startsWith('Bearer ')) {
      return next();
    }
    
    const token = authHeader.split(' ')[1];
    const decoded = verifyAccessToken(token);
    
    const result = await query(
      `SELECT id, email, first_name, last_name, role, kyc_tier, mfa_enabled,
              is_active, is_suspended, email_verified, phone_verified
       FROM users WHERE id = $1`,
      [decoded.sub]
    );
    
    if (result.rows.length > 0 && result.rows[0].is_active && !result.rows[0].is_suspended) {
      req.user = result.rows[0];
    }
  } catch (err) {
    // Silently ignore auth errors for optional auth
  }
  
  next();
}

module.exports = { authenticate, authorize, requireStepUp, optionalAuth };
