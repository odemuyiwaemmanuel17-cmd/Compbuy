const express = require('express');
const router = express.Router();
const { asyncHandler } = require('../middleware/errorHandler');
const { authLimiter, otpLimiter } = require('../middleware/security');
const { validate } = require('../validators/schemas');
const {
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
} = require('../controllers/authController');
const { authenticate } = require('../middleware/auth');

// POST /register
router.post('/register', authLimiter, validate(require('../validators/schemas').registerSchema), asyncHandler(register));

// POST /login
router.post('/login', authLimiter, validate(require('../validators/schemas').loginSchema), asyncHandler(login));

// POST /verify-otp
router.post('/verify-otp', otpLimiter, validate(require('../validators/schemas').verifyOtpSchema), authenticate, asyncHandler(verifyOtpHandler));

// POST /mfa/stepup
router.post('/mfa/stepup', authLimiter, asyncHandler(verifyMfaStepUp));

// POST /refresh
router.post('/refresh', asyncHandler(refresh));

// POST /forgot-password
router.post('/forgot-password', authLimiter, validate(require('../validators/schemas').forgotPasswordSchema), asyncHandler(forgotPassword));

// POST /reset-password
router.post('/reset-password', authLimiter, validate(require('../validators/schemas').resetPasswordSchema), asyncHandler(resetPassword));

// POST /logout
router.post('/logout', authenticate, asyncHandler(logout));

// GET /me
router.get('/me', authenticate, asyncHandler(getMe));

// POST /mfa/setup
router.post('/mfa/setup', authenticate, asyncHandler(mfaSetup));

// POST /mfa/activate
router.post('/mfa/activate', authenticate, asyncHandler(mfaActivate));

// GET /devices
router.get('/devices', authenticate, asyncHandler(listDevices));

// DELETE /devices/:id
router.delete('/devices/:id', authenticate, asyncHandler(revokeDevice));

module.exports = router;
