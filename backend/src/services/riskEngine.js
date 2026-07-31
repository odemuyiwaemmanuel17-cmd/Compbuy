const { query } = require('../config/db');
const logger = require('./logger');
const geoip = require('geoip-lite');

const SUSPICIOUS_THRESHOLD = parseInt(process.env.SUSPICIOUS_LOGIN_RISK_THRESHOLD, 10) || 60;

/**
 * Compute login risk score (0-100)
 */
async function computeLoginRisk({ userId, ip, deviceFingerprint, email }) {
  const reasons = [];
  let score = 0;
  
  // Get country from IP
  const geo = geoip.lookup(ip);
  const country = geo ? geo.country : 'Unknown';
  
  // 1. Device signals
  if (!deviceFingerprint) {
    score += 10;
    reasons.push('No device fingerprint');
  } else {
    try {
      const deviceResult = await query(
        `SELECT trust_status FROM user_devices WHERE user_id = $1 AND device_fingerprint = $2`,
        [userId, deviceFingerprint]
      );
      
      if (deviceResult.rows.length === 0) {
        score += 25;
        reasons.push('Unrecognized device');
      } else if (deviceResult.rows[0].trust_status === 'revoked') {
        score += 40;
        reasons.push('Revoked device');
      }
    } catch (err) {
      logger.error('Device lookup failed in risk computation', { error: err.message });
    }
  }
  
  // 2. New country check
  if (country !== 'Unknown') {
    try {
      const sessionCountries = await query(
        `SELECT DISTINCT ip_address::text 
         FROM sessions 
         WHERE user_id = $1 
         ORDER BY created_at DESC 
         LIMIT 5`,
        [userId]
      );
      
      const knownCountries = new Set();
      for (const row of sessionCountries.rows) {
        const sessionGeo = geoip.lookup(row.ip_address);
        if (sessionGeo && sessionGeo.country) {
          knownCountries.add(sessionGeo.country);
        }
      }
      
      if (knownCountries.size > 0 && !knownCountries.has(country)) {
        score += 20;
        reasons.push(`Login from new country: ${country}`);
      }
    } catch (err) {
      logger.error('Country check failed', { error: err.message });
    }
  }
  
  // 3. Velocity check (10 min)
  try {
    const velocityResult = await query(
      `SELECT COUNT(*) as attempt_count 
       FROM login_events 
       WHERE user_id = $1 AND created_at > NOW() - INTERVAL '10 minutes'`,
      [userId]
    );
    
    const attemptCount = parseInt(velocityResult.rows[0].attempt_count, 10);
    if (attemptCount >= 8) {
      score += 35;
      reasons.push('High login velocity (8+ attempts in 10min)');
    } else if (attemptCount >= 4) {
      score += 15;
      reasons.push('Elevated login velocity');
    }
  } catch (err) {
    logger.error('Velocity check failed', { error: err.message });
  }
  
  // 4. Fail ratio check (24h)
  try {
    const failResult = await query(
      `SELECT 
         COUNT(*) FILTER (WHERE success = false) as fails,
         COUNT(*) as total
       FROM login_events
       WHERE user_id = $1 AND created_at > NOW() - INTERVAL '24 hours'`,
      [userId]
    );
    
    const fails = parseInt(failResult.rows[0].fails, 10);
    const total = parseInt(failResult.rows[0].total, 10);
    
    if (total >= 3 && fails / total > 0.6) {
      score += 15;
      reasons.push('High failure ratio (>60%)');
    }
  } catch (err) {
    logger.error('Fail ratio check failed', { error: err.message });
  }
  
  // 5. IP lockout history (7d)
  try {
    const lockoutResult = await query(
      `SELECT COUNT(*) as lockout_count
       FROM users
       WHERE id = $1 
         AND locked_until > NOW() - INTERVAL '7 days'`,
      [userId]
    );
    
    // This is a simplified check - would need login_events tracking lockouts
    // For now, we skip this signal or implement differently
  } catch (err) {
    logger.error('Lockout check failed', { error: err.message });
  }
  
  // Cap at 100
  score = Math.min(score, 100);
  
  const requiresStepUp = score >= SUSPICIOUS_THRESHOLD;
  
  if (requiresStepUp) {
    logger.warn('Step-up authentication required', { userId, score, reasons, ip });
  }
  
  return { score, reasons, requiresStepUp, country };
}

/**
 * Adjust user trust score
 */
async function adjustUserTrust(userId, delta, reason) {
  try {
    const result = await query(
      `UPDATE users 
       SET trust_score = GREATEST(0, LEAST(100, trust_score + $2)),
           updated_at = NOW()
       WHERE id = $1
       RETURNING trust_score`,
      [userId, delta]
    );
    
    logger.info('User trust adjusted', { userId, delta, reason, newScore: result.rows[0]?.trust_score });
    return result.rows[0]?.trust_score || 50;
  } catch (err) {
    logger.error('Failed to adjust user trust', { error: err.message });
    throw err;
  }
}

module.exports = { computeLoginRisk, adjustUserTrust };
