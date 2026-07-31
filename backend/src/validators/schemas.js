const { z } = require('zod');
const { parsePhoneNumberFromString } = require('libphonenumber-js');

// Common password patterns to reject
const COMMON_PASSWORD_STARTS = ['password', '123456', 'qwerty', 'admin', 'letmein', 'welcome', 'monkey', 'dragon'];

/**
 * Strong password validation
 */
const passwordSchema = z.string().superRefine((val, ctx) => {
  if (val.length < 14) {
    ctx.addIssue({ code: z.ZodIssueCode.custom, message: 'Password must be at least 14 characters' });
  }
  if (!/[A-Z]/.test(val)) {
    ctx.addIssue({ code: z.ZodIssueCode.custom, message: 'Password must contain an uppercase letter' });
  }
  if (!/[a-z]/.test(val)) {
    ctx.addIssue({ code: z.ZodIssueCode.custom, message: 'Password must contain a lowercase letter' });
  }
  if (!/[0-9]/.test(val)) {
    ctx.addIssue({ code: z.ZodIssueCode.custom, message: 'Password must contain a number' });
  }
  if (!/[!@#$%^&*(),.?":{}|<>_\-+=\[\]\\;'`~]/.test(val)) {
    ctx.addIssue({ code: z.ZodIssueCode.custom, message: 'Password must contain a special character' });
  }
  if (/(.)\1{3,}/.test(val)) {
    ctx.addIssue({ code: z.ZodIssueCode.custom, message: 'Password cannot have 4+ repeated characters' });
  }
  const lowerVal = val.toLowerCase();
  for (const pattern of COMMON_PASSWORD_STARTS) {
    if (lowerVal.startsWith(pattern)) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, message: 'Password uses a common pattern' });
      break;
    }
  }
});

/**
 * Nigerian phone validation
 */
function validateNigerianPhone(val) {
  try {
    const phone = parsePhoneNumberFromString(val, 'NG');
    return phone && phone.isValid() && phone.country === 'NG';
  } catch {
    return false;
  }
}

const registerSchema = z.object({
  first_name: z.string().min(2).max(50),
  last_name: z.string().min(2).max(50),
  email: z.string().email(),
  phone: z.string().refine(validateNigerianPhone, { message: 'Invalid Nigerian phone number' }),
  password: passwordSchema,
  role: z.enum(['buyer', 'seller', 'broker']),
  accept_terms: z.boolean().refine(v => v === true, { message: 'You must accept the terms' })
});

const loginSchema = z.object({
  email: z.string().email(),
  password: z.string().min(1),
  remember: z.boolean().optional()
});

const verifyOtpSchema = z.object({
  otp: z.string().length(6).regex(/^\d{6}$/)
});

const mfaVerifySchema = z.object({
  code: z.string().length(6).regex(/^\d{6}$/)
});

const forgotPasswordSchema = z.object({
  email: z.string().email()
});

const resetPasswordSchema = z.object({
  token: z.string(),
  password: passwordSchema
});

const changePasswordSchema = z.object({
  current_password: z.string().min(1),
  new_password: passwordSchema
});

const submitNationalIdSchema = z.object({
  bvn: z.string().length(11).regex(/^\d{11}$/).optional(),
  nin: z.string().length(11).regex(/^\d{11}$/).optional()
}).refine(data => data.bvn || data.nin, { message: 'Either BVN or NIN is required' });

const createListingSchema = z.object({
  title: z.string().min(5).max(200),
  description: z.string().min(50).max(5000),
  industry: z.string().max(100),
  sub_industry: z.string().max(100).optional(),
  business_scale: z.enum(['micro', 'small', 'medium', 'large', 'multinational']),
  location: z.string().max(200),
  years_established: z.number().int().positive().optional(),
  employee_count: z.number().int().positive().optional(),
  annual_revenue: z.number().nonnegative().optional(),
  net_profit: z.number().optional(),
  asking_price: z.number().positive(),
  reason_for_sale: z.string().max(300).optional(),
  assets_included: z.string().optional(),
  liabilities: z.number().default(0),
  inventory_value: z.number().default(0),
  currency: z.string().length(3).default('NGN'),
  website_url: z.string().url().optional().or(z.literal('')),
  cac_number: z.string().optional()
});

const updateListingSchema = z.object({
  title: z.string().min(5).max(200).optional(),
  description: z.string().min(50).max(5000).optional(),
  industry: z.string().max(100).optional(),
  sub_industry: z.string().max(100).optional(),
  business_scale: z.enum(['micro', 'small', 'medium', 'large', 'multinational']).optional(),
  location: z.string().max(200).optional(),
  years_established: z.number().int().positive().optional(),
  employee_count: z.number().int().positive().optional(),
  annual_revenue: z.number().nonnegative().optional(),
  net_profit: z.number().optional(),
  asking_price: z.number().positive().optional(),
  reason_for_sale: z.string().max(300).optional(),
  assets_included: z.string().optional(),
  liabilities: z.number().optional(),
  inventory_value: z.number().optional(),
  website_url: z.string().url().optional().or(z.literal('')),
  cac_number: z.string().optional()
});

const listingQuerySchema = z.object({
  page: z.coerce.number().int().positive().default(1),
  limit: z.coerce.number().int().positive().max(50).default(20),
  industry: z.string().optional(),
  scale: z.string().optional(),
  min_price: z.coerce.number().nonnegative().optional(),
  max_price: z.coerce.number().nonnegative().optional(),
  trust_badge_min: z.coerce.number().int().min(0).max(5).optional(),
  location: z.string().optional(),
  search: z.string().optional(),
  sort: z.enum(['newest', 'oldest', 'price_asc', 'price_desc', 'revenue_desc', 'most_viewed']).default('newest')
});

const createInquirySchema = z.object({
  subject: z.string().min(5).max(200),
  message: z.string().min(20).max(2000),
  inquiry_type: z.string().max(80).default('general'),
  accept_nda: z.boolean().refine(v => v === true, { message: 'You must accept the NDA' })
});

const sendMessageSchema = z.object({
  body: z.string().min(1).max(5000)
});

const updateProfileSchema = z.object({
  first_name: z.string().min(2).max(50).optional(),
  last_name: z.string().min(2).max(50).optional(),
  bio: z.string().max(500).optional(),
  linkedin_url: z.string().url().optional().or(z.literal('')),
  professional_headline: z.string().max(100).optional()
});

/**
 * Validation middleware factory
 */
function validate(schema, source = 'body') {
  return (req, res, next) => {
    const result = schema.safeParse(req[source]);
    
    if (!result.success) {
      const errors = result.error.errors.map(e => ({
        field: e.path.join('.'),
        message: e.message
      }));
      return res.status(422).json({
        success: false,
        message: 'Validation failed',
        errors
      });
    }
    
    req[source] = result.data;
    next();
  };
}

module.exports = {
  registerSchema,
  loginSchema,
  verifyOtpSchema,
  mfaVerifySchema,
  forgotPasswordSchema,
  resetPasswordSchema,
  changePasswordSchema,
  submitNationalIdSchema,
  createListingSchema,
  updateListingSchema,
  listingQuerySchema,
  createInquirySchema,
  sendMessageSchema,
  updateProfileSchema,
  validate,
  validateNigerianPhone
};
