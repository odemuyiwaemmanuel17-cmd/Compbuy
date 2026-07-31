/**
 * Async handler wrapper for route handlers
 */
function asyncHandler(fn) {
  return (req, res, next) => {
    Promise.resolve(fn(req, res, next)).catch(next);
  };
}

/**
 * Custom error class with status code and code
 */
class AppError extends Error {
  constructor(message, statusCode = 500, code) {
    super(message);
    this.statusCode = statusCode;
    this.code = code;
    this.isOperational = true;
    Error.captureStackTrace(this, this.constructor);
  }
}

/**
 * Global error handler middleware
 */
function errorHandler(err, req, res, next) {
  const logger = require('../utils/logger');
  
  let statusCode = err.statusCode || 500;
  let message = err.message || 'Internal server error';
  let code = err.code;
  
  // PostgreSQL errors
  if (err.code === '23505') {
    statusCode = 409;
    message = 'Resource already exists';
    code = 'DUPLICATE_RESOURCE';
  } else if (err.code === '23503') {
    statusCode = 400;
    message = 'Invalid reference';
    code = 'FOREIGN_KEY_VIOLATION';
  }
  
  // JWT errors
  if (err.name === 'JsonWebTokenError') {
    statusCode = 401;
    message = 'Invalid token';
    code = 'INVALID_TOKEN';
  } else if (err.name === 'TokenExpiredError') {
    statusCode = 401;
    message = 'Token expired';
    code = 'TOKEN_EXPIRED';
  }
  
  // Multer errors
  if (err.name === 'MulterError') {
    statusCode = 400;
    if (err.code === 'LIMIT_FILE_SIZE') {
      message = 'File too large';
      code = 'FILE_TOO_LARGE';
    } else if (err.code === 'LIMIT_UNEXPECTED_FILE') {
      message = 'Unexpected field';
      code = 'UNEXPECTED_FIELD';
    }
  }
  
  // Log 500 errors with stack
  if (statusCode === 500) {
    logger.error('Unhandled error', {
      message: err.message,
      stack: err.stack,
      url: req.url,
      method: req.method
    });
  }
  
  const response = {
    success: false,
    message
  };
  
  if (code) {
    response.code = code;
  }
  
  if (process.env.NODE_ENV === 'development' && statusCode === 500) {
    response.stack = err.stack;
  }
  
  res.status(statusCode).json(response);
}

/**
 * 404 Not Found handler
 */
function notFound(req, res, next) {
  res.status(404).json({
    success: false,
    message: `Route ${req.method} ${req.url} not found`
  });
}

module.exports = { asyncHandler, AppError, errorHandler, notFound };
