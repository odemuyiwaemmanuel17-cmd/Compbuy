const { asyncHandler } = require('../middleware/errorHandler');
const bcrypt = require('bcryptjs');
const crypto = require('crypto');
const { query } = require('../config/db');
const { signAccessToken, signRefreshToken, verifyRefreshToken, revokeRefreshToken, revokeAllUserSessions, signStepUpToken } = require('../utils/jwt');
const { encryptField, decryptField, hashForLookup } = require('../utils/encryption');
const { recordAuditEvent } = require('../services/auditChain');
const { buildFingerprint, registerOrUpdateDevice } = require('../services/deviceService');
const { computeLoginRisk } = require('../services/riskEngine');
const { issueOtp, verifyOtp } = require('../services/smsService');
const { generateSetupPayload, activateMfa, verifyTotpCode, verifyBackupCode } = require('../services/mfaService');
const { recalculateUserTier } = require('../services/kycService');
const { sendVerificationEmail, sendPasswordResetEmail, sendNewDeviceAlert } = require('../services/emailService');
const logger = require('../utils/logger');

const BCRYPT_SALT_ROUNDS = parseInt(process.env.BCRYPT_SALT_ROUNDS, 10) || 13;
const MAX_LOGIN_ATTEMPTS = parseInt(process.env.MAX_LOGIN_ATTEMPTS, 10) || 5;
const LOCKOUT_DURATION_MINUTES = parseInt(process.env.LOCKOUT_DURATION_MINUTES, 10) || 30;
const PASSWORD_HISTORY_COUNT = parseInt(process.env.PASSWORD_HISTORY_COUNT, 10) || 5;

/**
 * Normalize email (strip Gmail dots, lowercase)
 */
function normalizeEmail(email) {
  const [local, domain] = email.toLowerCase().split('@');
  if (domain === 'gmail.com' || domain === 'googlemail.com') {
    const normalizedLocal = local.replace(/\./g, '').split('+')[0];
    return `${normalizedLocal}@${domain}`;
  }
  return email.toLowerCase();
}

/**
 * Record login event (never throws)
 */
async function recordLoginEvent({ userId, email, success, failureReason, ip, deviceFingerprint, riskScore, mfaUsed }) {
  try {
    await query(
      `INSERT INTO login_events (user_id, email_attempted, success, failure_reason, ip_address, device_fingerprint, risk_score, mfa_used)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8)`,
      [userId || null, email, success, failureReason || null, ip, deviceFingerprint, riskScore || 0, mfaUsed || false]
    );
  } catch (err) {
    logger.error('Failed to record login event', { error: err.message });
  }
}

/**
 * Complete login flow
 */
async function completeLogin(req, res, user, deviceFingerprint, riskScore) {
  // Reset login attempts and lockout
  await query(
    `UPDATE users SET login_attempts = 0, locked_until = NULL, last_login_at = NOW(), last_login_ip = $2 WHERE id = $1`,
    [user.id, req.ip]
  );
  
  // Register device
  const deviceResult = await registerOrUpdateDevice(user.id, req);
  
  // Send alert for new device
  if (deviceResult.isNew && user.email_verified) {
    sendNewDeviceAlert(user, deviceResult.deviceName, req.ip).catch(err => {
      logger.error('Failed to send new device alert', { error: err.message });
    });
  }
  
  // Sign tokens
  const accessToken = signAccessToken({ sub: user.id, email: user.email, role: user.role });
  const refreshToken = await signRefreshToken(user.id, deviceResult.deviceId, req.ip, riskScore);
  
  // Set refresh token cookie
  const cookieOpts = {
    httpOnly: true,
    secure: process.env.COOKIE_SECURE === 'true',
    sameSite: process.env.COOKIE_SAME_SITE || 'strict',
    maxAge: 30 * 24 * 60 * 60 * 1000,
    path: '/api/auth',
    domain: process.env.COOKIE_DOMAIN || undefined
  };
  
  res.cookie('refreshToken', refreshToken, cookieOpts);
  
  // Record audit and login event
  recordAuditEvent({ actorId: user.id, action: 'USER_LOGIN', entityType: 'user', entityId: user.id, metadata: { ip: req.ip, deviceId: deviceResult.deviceId }, ip: req.ip });
  recordLoginEvent({ userId: user.id, email: user.email, success: true, ip: req.ip, deviceFingerprint, riskScore });
  
  // Return safe user fields
  const safeUser = {
    id: user.id,
    email: user.email,
    first_name: user.first_name,
    last_name: user.last_name,
    role: user.role,
    kyc_tier: user.kyc_tier,
    mfa_enabled: user.mfa_enabled,
    email_verified: user.email_verified,
    phone_verified: user.phone_verified
  };
  
  res.json({ success: true, access_token: accessToken, user: safeUser });
}

/**
 * Register new user
 */
const register = asyncHandler(async (req, res) => {
  const { first_name, last_name, email, phone, password, role } = req.body;
  
  const normalizedEmail = normalizeEmail(email);
  
  // Check for duplicates
  const existing = await query(
    `SELECT id FROM users WHERE email_normalized = $1 OR phone = $2`,
    [hashForLookup(normalizedEmail), phone]
  );
  
  if (existing.rows.length > 0) {
    return res.status(409).json({ success: false, message: 'Email or phone already registered' });
  }
  
  // Hash password
  const passwordHash = await bcrypt.hash(password, BCRYPT_SALT_ROUNDS);
  
  // Generate email verification token
  const emailVerifyToken = crypto.randomBytes(32).toString('hex');
  const emailVerifyExpiry = new Date(Date.now() + 24 * 60 * 60 * 1000);
  
  // Insert user
  const result = await query(
    `INSERT INTO users (email, email_normalized, password_hash, first_name, last_name, phone, role, email_verify_token, email_verify_expiry, kyc_tier)
     VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'tier0_unverified')
     RETURNING id, email, first_name, last_name, role, kyc_tier`,
    [email, hashForLookup(normalizedEmail), passwordHash, first_name, last_name, phone, role, emailVerifyToken, emailVerifyExpiry]
  );
  
  const user = result.rows[0];
  
  // Fire-and-forget: send verification email and SMS OTP
  sendVerificationEmail(user, emailVerifyToken).catch(err => logger.error('Failed to send verification email', { error: err.message }));
  issueOtp(user.id, phone, 'registration').catch(err => logger.error('Failed to send OTP', { error: err.message }));
  
  recordAuditEvent({ actorId: user.id, action: 'USER_REGISTERED', entityType: 'user', entityId: user.id, metadata: { role }, ip: req.ip });
  
  const safeUser = {
    id: user.id,
    email: user.email,
    first_name: user.first_name,
    last_name: user.last_name,
    role: user.role,
    kyc_tier: user.kyc_tier
  };
  
  res.status(201).json({ success: true, user: safeUser });
});

/**
 * Verify OTP
 */
const verifyOtpHandler = asyncHandler(async (req, res) => {
  const { otp } = req.body;
  const userId = req.user?.id;
  
  if (!userId) {
    return res.status(401).json({ success: false, message: 'Authentication required' });
  }
  
  const result = await verifyOtp(userId, otp);
  
  if (!result.valid) {
    return res.status(400).json({ success: false, message: result.reason || 'Invalid OTP' });
  }
  
  // Recalculate tier
  await recalculateUserTier(userId);
  
  recordAuditEvent({ actorId: userId, action: 'PHONE_VERIFIED', entityType: 'user', entityId: userId, metadata: {}, ip: req.ip });
  
  res.json({ success: true, message: 'Phone verified successfully' });
});

/**
 * Login
 */
const login = asyncHandler(async (req, res) => {
  const { email, password } = req.body;
  
  const deviceFingerprint = buildFingerprint(req);
  const normalizedEmail = normalizeEmail(email);
  
  // Fetch user by normalized email hash
  const result = await query(
    `SELECT * FROM users WHERE email_normalized = $1`,
    [hashForLookup(normalizedEmail)]
  );
  
  // Anti-enumeration: same error for no-user/wrong-pw
  if (result.rows.length === 0) {
    await recordLoginEvent({ email, success: false, failureReason: 'user_not_found', ip: req.ip, deviceFingerprint });
    return res.status(401).json({ success: false, message: 'Invalid credentials' });
  }
  
  const user = result.rows[0];
  
  // Check account status
  if (!user.is_active) {
    return res.status(403).json({ success: false, message: 'Account deactivated' });
  }
  
  if (user.is_suspended) {
    return res.status(403).json({ success: false, message: 'Account suspended' });
  }
  
  // Check lockout
  if (user.locked_until && new Date(user.locked_until) > new Date()) {
    return res.status(403).json({ success: false, message: 'Account temporarily locked' });
  }
  
  // Verify password
  const validPassword = await bcrypt.compare(password, user.password_hash);
  
  if (!validPassword) {
    // Increment attempts
    const newAttempts = (user.login_attempts || 0) + 1;
    const lockedUntil = newAttempts >= MAX_LOGIN_ATTEMPTS 
      ? new Date(Date.now() + LOCKOUT_DURATION_MINUTES * 60 * 1000)
      : null;
    
    await query(
      `UPDATE users SET login_attempts = $2, locked_until = $3 WHERE id = $1`,
      [user.id, newAttempts, lockedUntil]
    );
    
    await recordLoginEvent({ userId: user.id, email, success: false, failureReason: 'wrong_password', ip: req.ip, deviceFingerprint });
    return res.status(401).json({ success: false, message: 'Invalid credentials' });
  }
  
  // Compute risk score
  const riskResult = await computeLoginRisk({ userId: user.id, ip: req.ip, deviceFingerprint, email });
  
  // Check if MFA is enabled
  if (user.mfa_enabled) {
    // Require MFA step-up
    return res.json({ 
      success: true, 
      code: 'STEPUP_REQUIRED', 
      user_id: user.id,
      requires_mfa: true
    });
  }
  
  // Check if risk-triggered step-up needed
  if (riskResult.requiresStepUp) {
    return res.json({ 
      success: true, 
      code: 'STEPUP_REQUIRED', 
      user_id: user.id,
      risk_score: riskResult.score
    });
  }
  
  // Complete login
  await completeLogin(req, res, user, deviceFingerprint, riskResult.score);
});

/**
 * Verify MFA step-up
 */
const verifyMfaStepUp = asyncHandler(async (req, res) => {
  const { user_id: userId, code } = req.body;
  
  const result = await query(`SELECT * FROM users WHERE id = $1`, [userId]);
  if (result.rows.length === 0) {
    return res.status(400).json({ success: false, message: 'Invalid user' });
  }
  
  const user = result.rows[0];
  let verified = false;
  
  if (user.mfa_enabled) {
    // Try TOTP
    verified = await verifyTotpCode(userId, code);
    // Try backup code if TOTP failed
    if (!verified) {
      verified = await verifyBackupCode(userId, code);
    }
  } else {
    // Risk-triggered: verify SMS OTP
    const otpResult = await verifyOtp(userId, code);
    verified = otpResult.valid;
  }
  
  if (!verified) {
    return res.status(400).json({ success: false, message: 'Invalid code' });
  }
  
  const deviceFingerprint = buildFingerprint(req);
  const riskResult = await computeLoginRisk({ userId, ip: req.ip, deviceFingerprint, email: user.email });
  
  await completeLogin(req, res, user, deviceFingerprint, riskResult.score);
});

/**
 * MFA Setup
 */
const mfaSetup = asyncHandler(async (req, res) => {
  const payload = await generateSetupPayload(req.user);
  res.json({ success: true, ...payload });
});

/**
 * MFA Activate
 */
const mfaActivate = asyncHandler(async (req, res) => {
  const { secret, hashedCodes, code } = req.body;
  
  // Verify the code works
  const { authenticator } = require('otplib');
  const isValid = authenticator.verify({ token: code, secret });
  
  if (!isValid) {
    return res.status(400).json({ success: false, message: 'Invalid verification code' });
  }
  
  await activateMfa(req.user.id, secret, hashedCodes, 'user_enabled');
  recordAuditEvent({ actorId: req.user.id, action: 'MFA_ENABLED', entityType: 'user', entityId: req.user.id, metadata: {}, ip: req.ip });
  
  res.json({ success: true, message: 'MFA activated' });
});

/**
 * Refresh token
 */
const refresh = asyncHandler(async (req, res) => {
  const token = req.cookies.refreshToken;
  
  if (!token) {
    return res.status(401).json({ success: false, message: 'Refresh token required' });
  }
  
  const { userId } = await verifyRefreshToken(token);
  
  const result = await query(
    `SELECT id, email, role FROM users WHERE id = $1 AND is_active = true`,
    [userId]
  );
  
  if (result.rows.length === 0) {
    return res.status(401).json({ success: false, message: 'User not found' });
  }
  
  const accessToken = signAccessToken({ sub: userId, email: result.rows[0].email, role: result.rows[0].role });
  res.json({ success: true, access_token: accessToken });
});

/**
 * Logout
 */
const logout = asyncHandler(async (req, res) => {
  const token = req.cookies.refreshToken;
  
  if (token) {
    await revokeRefreshToken(token, 'user_logout');
  }
  
  res.clearCookie('refreshToken', { path: '/api/auth' });
  res.json({ success: true, message: 'Logged out' });
});

/**
 * Get current user
 */
const getMe = asyncHandler(async (req, res) => {
  const safeUser = {
    id: req.user.id,
    email: req.user.email,
    first_name: req.user.first_name,
    last_name: req.user.last_name,
    role: req.user.role,
    kyc_tier: req.user.kyc_tier,
    mfa_enabled: req.user.mfa_enabled,
    email_verified: req.user.email_verified,
    phone_verified: req.user.phone_verified,
    trust_score: req.user.trust_score
  };
  res.json({ success: true, user: safeUser });
});

/**
 * List devices
 */
const listDevices = asyncHandler(async (req, res) => {
  const devices = await require('../services/deviceService').listUserDevices(req.user.id);
  res.json({ success: true, devices });
});

/**
 * Revoke device
 */
const revokeDevice = asyncHandler(async (req, res) => {
  await require('../services/deviceService').revokeDevice(req.user.id, req.params.id);
  recordAuditEvent({ actorId: req.user.id, action: 'DEVICE_REVOKED', entityType: 'user_device', entityId: req.params.id, metadata: {}, ip: req.ip });
  res.json({ success: true });
});

/**
 * Forgot password
 */
const forgotPassword = asyncHandler(async (req, res) => {
  const { email } = req.body;
  const normalizedEmail = normalizeEmail(email);
  
  // Always return 200 for anti-enumeration
  const result = await query(
    `SELECT id, first_name FROM users WHERE email_normalized = $1 AND is_active = true`,
    [hashForLookup(normalizedEmail)]
  );
  
  if (result.rows.length > 0) {
    const user = result.rows[0];
    const resetToken = crypto.randomBytes(32).toString('hex');
    const resetExpiry = new Date(Date.now() + 60 * 60 * 1000);
    
    await query(
      `UPDATE users SET password_reset_token = $2, password_reset_expiry = $3 WHERE id = $1`,
      [user.id, resetToken, resetExpiry]
    );
    
    sendPasswordResetEmail({ ...user, email }, resetToken).catch(err => logger.error('Failed to send reset email', { error: err.message }));
  }
  
  res.json({ success: true, message: 'If an account exists, a reset link has been sent' });
});

/**
 * Reset password
 */
const resetPassword = asyncHandler(async (req, res) => {
  const { token, password } = req.body;
  
  const result = await query(
    `SELECT id, password_hash FROM users WHERE password_reset_token = $1 AND password_reset_expiry > NOW()`,
    [token]
  );
  
  if (result.rows.length === 0) {
    return res.status(400).json({ success: false, message: 'Invalid or expired token' });
  }
  
  const userId = result.rows[0].id;
  
  // Check password history
  const userResult = await query(`SELECT password_history FROM users WHERE id = $1`, [userId]);
  const history = userResult.rows[0].password_history || [];
  
  for (const oldHash of history) {
    const matches = await bcrypt.compare(password, oldHash);
    if (matches) {
      return res.status(400).json({ success: false, message: 'Cannot reuse recent passwords' });
    }
  }
  
  const newPasswordHash = await bcrypt.hash(password, BCRYPT_SALT_ROUNDS);
  
  // Update password and history
  const newHistory = [...history.slice(-(PASSWORD_HISTORY_COUNT - 1)), newPasswordHash];
  
  await query(
    `UPDATE users SET password_hash = $2, password_history = $3, password_changed_at = NOW(), password_reset_token = NULL, password_reset_expiry = NULL WHERE id = $1`,
    [userId, newPasswordHash, newHistory]
  );
  
  // Revoke all sessions
  await revokeAllUserSessions(userId, 'password_reset');
  
  recordAuditEvent({ actorId: userId, action: 'PASSWORD_RESET', entityType: 'user', entityId: userId, metadata: {}, ip: req.ip });
  
  res.json({ success: true, message: 'Password reset successfully' });
});

module.exports = {
  register,
  verifyOtpHandler,
  login,
  verifyMfaStepUp,
  mfaSetup,
  mfaActivate,
  refresh,
  logout,
  getMe,
  listDevices,
  revokeDevice,
  forgotPassword,
  resetPassword
};
