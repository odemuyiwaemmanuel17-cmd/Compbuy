const { asyncHandler } = require('../middleware/errorHandler');
const { query } = require('../config/db');
const { recordAuditEvent } = require('../services/auditChain');
const { meetsTier } = require('../services/kycService');
const logger = require('./logger');

const MAX_LISTINGS_UNVERIFIED = parseInt(process.env.MAX_LISTINGS_PER_UNVERIFIED_SELLER, 10) || 1;
const MAX_LISTINGS_VERIFIED = parseInt(process.env.MAX_LISTINGS_PER_VERIFIED_SELLER, 10) || 15;

/**
 * Slugify text with timestamp
 */
function slugify(text) {
  const base = text.toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return `${base}-${Date.now().toString(36)}`;
}

/**
 * Build SQL filters from query params
 */
function buildFilters(q, paramCount = 0) {
  const conditions = [];
  const params = [];
  let idx = paramCount + 1;
  
  if (q.industry) {
    conditions.push(`l.industry ILIKE $${idx}`);
    params.push(`%${q.industry}%`);
    idx++;
  }
  
  if (q.scale) {
    conditions.push(`l.business_scale = $${idx}`);
    params.push(q.scale);
    idx++;
  }
  
  if (q.min_price != null) {
    conditions.push(`l.asking_price >= $${idx}`);
    params.push(q.min_price);
    idx++;
  }
  
  if (q.max_price != null) {
    conditions.push(`l.asking_price <= $${idx}`);
    params.push(q.max_price);
    idx++;
  }
  
  if (q.trust_badge_min != null) {
    conditions.push(`l.trust_badge_level >= $${idx}`);
    params.push(q.trust_badge_min);
    idx++;
  }
  
  if (q.location) {
    conditions.push(`l.location ILIKE $${idx}`);
    params.push(`%${q.location}%`);
    idx++;
  }
  
  if (q.search) {
    conditions.push(`l.search_vector @@ plainto_tsquery('english', $${idx})`);
    params.push(q.search);
    idx++;
  }
  
  // Sort mapping
  const sortMap = {
    newest: 'l.published_at DESC NULLS LAST',
    oldest: 'l.published_at ASC',
    price_asc: 'l.asking_price ASC NULLS LAST',
    price_desc: 'l.asking_price DESC NULLS LAST',
    revenue_desc: 'l.annual_revenue DESC NULLS LAST',
    most_viewed: 'l.view_count DESC'
  };
  const order = sortMap[q.sort] || sortMap.newest;
  
  return { conditions, params, order, nextIdx: idx };
}

/**
 * Get all listings with pagination
 */
const getAll = asyncHandler(async (req, res) => {
  const q = req.query;
  const offset = (q.page - 1) * q.limit;
  
  const { conditions, params, order } = buildFilters(q);
  const whereClause = conditions.length > 0 ? `WHERE ${conditions.join(' AND ')}` : '';
  
  // Count total
  const countResult = await query(
    `SELECT COUNT(*) as total FROM listings l ${whereClause}`,
    params
  );
  const total = parseInt(countResult.rows[0].total, 10);
  
  // Fetch data
  const dataQuery = `
    SELECT l.id, l.title, l.slug, l.description, l.industry, l.sub_industry, 
           l.business_scale, l.location, l.years_established, l.employee_count,
           l.annual_revenue, l.net_profit, l.asking_price, l.currency,
           l.status, l.is_featured, l.trust_badge_level, l.view_count, l.inquiry_count,
           l.published_at, l.created_at,
           (SELECT url FROM listing_images WHERE listing_id = l.id AND is_primary = true LIMIT 1) as primary_image,
           u.first_name as seller_first_name, u.last_name as seller_last_name
    FROM listings l
    JOIN users u ON l.seller_id = u.id
    ${whereClause}
    ORDER BY ${order}
    LIMIT $${params.length + 1} OFFSET $${params.length + 2}
  `;
  
  const result = await query(dataQuery, [...params, q.limit, offset]);
  
  res.json({
    success: true,
    data: result.rows,
    meta: {
      total,
      page: q.page,
      limit: q.limit,
      pages: Math.ceil(total / q.limit)
    }
  });
});

/**
 * Get single listing by ID or slug
 */
const getOne = asyncHandler(async (req, res) => {
  const { id } = req.params;
  
  // Check if UUID or slug
  const isUuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id);
  
  const queryText = isUuid
    ? `SELECT l.*, u.first_name as seller_first_name, u.last_name as seller_last_name, u.email as seller_email
       FROM listings l JOIN users u ON l.seller_id = u.id WHERE l.id = $1`
    : `SELECT l.*, u.first_name as seller_first_name, u.last_name as seller_last_name, u.email as seller_email
       FROM listings l JOIN users u ON l.seller_id = u.id WHERE l.slug = $1`;
  
  const result = await query(queryText, [id]);
  
  if (result.rows.length === 0) {
    return res.status(404).json({ success: false, message: 'Listing not found' });
  }
  
  const listing = result.rows[0];
  
  // Get images
  const imagesResult = await query(
    `SELECT id, url, is_primary, sort_order FROM listing_images WHERE listing_id = $1 ORDER BY sort_order, id`,
    [listing.id]
  );
  
  // Fire-and-forget: increment view count
  query(`UPDATE listings SET view_count = view_count + 1 WHERE id = $1`, [listing.id]).catch(err => {
    logger.error('Failed to increment view count', { error: err.message });
  });
  
  res.json({
    success: true,
    listing: {
      ...listing,
      images: imagesResult.rows
    }
  });
});

/**
 * Create listing
 */
const create = asyncHandler(async (req, res) => {
  const { meetsTier } = require('../services/kycService');
  
  // Check tier requirement (tier2_id_verified minimum)
  if (!meetsTier(req.user.kyc_tier, 'tier2_id_verified')) {
    return res.status(403).json({
      success: false,
      code: 'KYC_TIER_INSUFFICIENT',
      currentTier: req.user.kyc_tier,
      requiredTier: 'tier2_id_verified'
    });
  }
  
  // Check listing count limit
  const maxListings = meetsTier(req.user.kyc_tier, 'tier3_financial_verified') 
    ? MAX_LISTINGS_VERIFIED 
    : MAX_LISTINGS_UNVERIFIED;
  
  const countResult = await query(
    `SELECT COUNT(*) as count FROM listings WHERE seller_id = $1 AND status IN ('live', 'pending_review', 'under_offer')`,
    [req.user.id]
  );
  
  if (parseInt(countResult.rows[0].count, 10) >= maxListings) {
    return res.status(403).json({ 
      success: false, 
      message: `Maximum ${maxListings} listings allowed for your verification tier` 
    });
  }
  
  const data = req.body;
  const slug = slugify(data.title);
  const expiresAt = new Date(Date.now() + parseInt(process.env.LISTING_EXPIRY_DAYS, 10) * 24 * 60 * 60 * 1000);
  
  const result = await query(
    `INSERT INTO listings (seller_id, title, slug, description, industry, sub_industry, business_scale, location,
                          years_established, employee_count, annual_revenue, net_profit, asking_price, reason_for_sale,
                          assets_included, liabilities, inventory_value, currency, cac_number, website_url, expires_at, status)
     VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21, 'pending_review')
     RETURNING id, slug`,
    [req.user.id, data.title, slug, data.description, data.industry, data.sub_industry, data.business_scale, data.location,
     data.years_established, data.employee_count, data.annual_revenue, data.net_profit, data.asking_price, data.reason_for_sale,
     data.assets_included, data.liabilities, data.inventory_value, data.currency, data.cac_number, data.website_url, expiresAt]
  );
  
  recordAuditEvent({ actorId: req.user.id, action: 'LISTING_CREATED', entityType: 'listing', entityId: result.rows[0].id, metadata: { title: data.title }, ip: req.ip });
  
  res.status(201).json({ success: true, listing_id: result.rows[0].id, slug: result.rows[0].slug });
});

/**
 * Update listing
 */
const update = asyncHandler(async (req, res) => {
  const { id } = req.params;
  const data = req.body;
  
  // Verify ownership or admin
  const result = await query(`SELECT seller_id, status FROM listings WHERE id = $1`, [id]);
  if (result.rows.length === 0) {
    return res.status(404).json({ success: false, message: 'Listing not found' });
  }
  
  const listing = result.rows[0];
  const isAdmin = req.user.role === 'admin' || req.user.role === 'super_admin';
  
  if (listing.seller_id !== req.user.id && !isAdmin) {
    return res.status(403).json({ success: false, message: 'Not authorized' });
  }
  
  // Build dynamic SET clause
  const updates = [];
  const params = [];
  let idx = 1;
  
  const updatableFields = ['title', 'description', 'industry', 'sub_industry', 'business_scale', 'location', 
                           'years_established', 'employee_count', 'annual_revenue', 'net_profit', 'asking_price',
                           'reason_for_sale', 'assets_included', 'liabilities', 'inventory_value', 'website_url', 'cac_number'];
  
  for (const field of updatableFields) {
    if (data[field] !== undefined) {
      updates.push(`${field} = $${idx}`);
      params.push(data[field]);
      idx++;
      
      // If financial field changed and listing is live, set to pending_review
      if (['annual_revenue', 'net_profit', 'asking_price'].includes(field) && listing.status === 'live') {
        updates.push(`status = 'pending_review'`);
      }
    }
  }
  
  updates.push(`updated_at = NOW()`);
  params.push(id);
  
  await query(
    `UPDATE listings SET ${updates.join(', ')} WHERE id = $${idx}`,
    params
  );
  
  recordAuditEvent({ actorId: req.user.id, action: 'LISTING_UPDATED', entityType: 'listing', entityId: id, metadata: { fields: Object.keys(data) }, ip: req.ip });
  
  res.json({ success: true });
});

/**
 * Set listing status (admin only)
 */
const setStatus = asyncHandler(async (req, res) => {
  const { id } = req.params;
  const { status } = req.body;
  
  const validStatuses = ['draft', 'pending_review', 'changes_requested', 'live', 'under_offer', 'sold', 'withdrawn', 'suspended'];
  if (!validStatuses.includes(status)) {
    return res.status(400).json({ success: false, message: 'Invalid status' });
  }
  
  const updates = [`status = $2`, `updated_at = NOW()`];
  const params = [id, status];
  let paramIdx = 3;
  
  if (status === 'live') {
    updates.push(`published_at = COALESCE(published_at, NOW())`);
  }
  
  await query(
    `UPDATE listings SET ${updates.join(', ')} WHERE id = $1`,
    params
  );
  
  recordAuditEvent({ actorId: req.user.id, action: 'LISTING_STATUS_CHANGED', entityType: 'listing', entityId: id, metadata: { status }, ip: req.ip });
  
  res.json({ success: true });
});

module.exports = {
  getAll,
  getOne,
  create,
  update,
  setStatus
};
