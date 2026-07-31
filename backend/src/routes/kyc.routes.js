const express = require('express');
const router = express.Router();
const { asyncHandler } = require('../middleware/errorHandler');
const { uploadLimiter, uploadKyc } = require('../middleware/security');
const { validate } = require('../validators/schemas');
const { authenticate } = require('../middleware/auth');
const { authorize } = require('../middleware/auth');
const {
  submitNationalId,
  uploadDocument,
  getStatus,
  getReviewQueue,
  approveDocumentHandler,
  rejectDocumentHandler
} = require('../controllers/kycController');

// All routes require authentication
router.use(authenticate);

// POST /national-id
router.post('/national-id', validate(require('../validators/schemas').submitNationalIdSchema), asyncHandler(submitNationalId));

// POST /documents
router.post('/documents', uploadLimiter, uploadKyc, asyncHandler(uploadDocument));

// GET /status
router.get('/status', asyncHandler(getStatus));

// GET /queue (admin only)
router.get('/queue', authorize('admin', 'super_admin'), asyncHandler(getReviewQueue));

// PATCH /documents/:id/approve (admin only)
router.patch('/documents/:id/approve', authorize('admin', 'super_admin'), asyncHandler(approveDocumentHandler));

// PATCH /documents/:id/reject (admin only)
router.patch('/documents/:id/reject', authorize('admin', 'super_admin'), asyncHandler(rejectDocumentHandler));

module.exports = router;
