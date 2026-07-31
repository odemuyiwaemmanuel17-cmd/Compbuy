const express = require('express');
const router = express.Router();
const { asyncHandler } = require('../middleware/errorHandler');
const { validate } = require('../validators/schemas');
const { authenticate, authorize, optionalAuth } = require('../middleware/auth');
const { meetsTier } = require('../services/kycService');
const {
  getAll,
  getOne,
  create,
  update,
  setStatus
} = require('../controllers/listingController');

// GET / (optional auth for personalization)
router.get('/', optionalAuth, validate(require('../validators/schemas').listingQuerySchema, 'query'), asyncHandler(getAll));

// GET /:id (optional auth)
router.get('/:id', optionalAuth, asyncHandler(getOne));

// POST / (authenticated sellers/brokers/admins with tier2+)
router.post('/', authenticate, authorize('seller', 'broker', 'admin'), validate(require('../validators/schemas').createListingSchema), asyncHandler(create));

// PUT /:id (owner or admin)
router.put('/:id', authenticate, validate(require('../validators/schemas').updateListingSchema), asyncHandler(update));

// PATCH /:id/status (admin only)
router.patch('/:id/status', authenticate, authorize('admin', 'super_admin'), asyncHandler(setStatus));

module.exports = router;
