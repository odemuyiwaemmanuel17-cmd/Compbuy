const rateLimit = require('express-rate-limit');
const multer = require('multer');
const path = require('path');
const fs = require('fs');
const crypto = require('crypto');
const logger = require('./logger');

// Rate limiters
const defaultLimiter = rateLimit({
  windowMs: parseInt(process.env.RATE_LIMIT_WINDOW_MS, 10) || 900000,
  max: parseInt(process.env.RATE_LIMIT_MAX_REQUESTS, 10) || 100,
  message: { success: false, message: 'Too many requests, please try again later' },
  standardHeaders: true,
  legacyHeaders: false
});

const authLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  max: parseInt(process.env.AUTH_RATE_LIMIT_MAX, 10) || 8,
  message: { success: false, message: 'Too many authentication attempts' },
  skipSuccessfulRequests: true,
  standardHeaders: true,
  legacyHeaders: false
});

const otpLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  max: parseInt(process.env.OTP_RATE_LIMIT_MAX, 10) || 4,
  message: { success: false, message: 'Too many OTP attempts' },
  standardHeaders: true,
  legacyHeaders: false
});

const uploadLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  max: parseInt(process.env.UPLOAD_RATE_LIMIT_MAX, 10) || 20,
  message: { success: false, message: 'Too many upload attempts' },
  standardHeaders: true,
  legacyHeaders: false
});

// Ensure upload directories exist
const UPLOAD_DIR = process.env.UPLOAD_DIR || 'uploads';
const uploadDirs = ['images', 'documents', 'kyc'];
uploadDirs.forEach(dir => {
  const dirPath = path.join(__dirname, '..', '..', UPLOAD_DIR, dir);
  if (!fs.existsSync(dirPath)) {
    fs.mkdirSync(dirPath, { recursive: true });
  }
});

// Multer storage configuration
const storage = (subdir, allowedMimes, maxSizeMB) => multer.diskStorage({
  destination: (req, file, cb) => {
    const destPath = path.join(__dirname, '..', '..', UPLOAD_DIR, subdir);
    cb(null, destPath);
  },
  filename: (req, file, cb) => {
    const ext = path.extname(file.originalname).toLowerCase();
    const randomName = crypto.randomBytes(16).toString('hex');
    cb(null, `${randomName}${ext}`);
  }
});

const fileFilter = (allowedMimes) => (req, file, cb) => {
  if (allowedMimes.includes(file.mimetype)) {
    cb(null, true);
  } else {
    cb(new Error(`Invalid file type: ${file.mimetype}`), false);
  }
};

const MAX_FILE_SIZE_MB = parseInt(process.env.MAX_FILE_SIZE_MB, 10) || 15;

// Upload configurations
const uploadImage = multer({
  storage: storage('images', ['image/jpeg', 'image/png', 'image/webp'], MAX_FILE_SIZE_MB),
  fileFilter: fileFilter(['image/jpeg', 'image/png', 'image/webp']),
  limits: { fileSize: MAX_FILE_SIZE_MB * 1024 * 1024, files: 10 }
}).array('images', 10);

const uploadDocument = multer({
  storage: storage('documents', ['application/pdf', 'image/jpeg', 'image/png'], MAX_FILE_SIZE_MB),
  fileFilter: fileFilter(['application/pdf', 'image/jpeg', 'image/png']),
  limits: { fileSize: MAX_FILE_SIZE_MB * 1024 * 1024, files: 5 }
}).single('file');

const uploadKyc = multer({
  storage: storage('kyc', ['application/pdf', 'image/jpeg', 'image/png'], MAX_FILE_SIZE_MB),
  fileFilter: fileFilter(['application/pdf', 'image/jpeg', 'image/png']),
  limits: { fileSize: MAX_FILE_SIZE_MB * 1024 * 1024, files: 1 }
}).single('file');

/**
 * Hash a file synchronously
 */
function hashFile(filePath) {
  const content = fs.readFileSync(filePath);
  return crypto.createHash('sha256').update(content).digest('hex');
}

module.exports = {
  defaultLimiter,
  authLimiter,
  otpLimiter,
  uploadLimiter,
  uploadImage,
  uploadDocument,
  uploadKyc,
  hashFile
};
