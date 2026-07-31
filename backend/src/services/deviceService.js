const crypto = require('crypto');
const { UAParser } = require('ua-parser-js');
const { query } = require('../config/db');
const logger = require('./logger');

/**
 * Build a device fingerprint from request headers and UA
 */
function buildFingerprint(req) {
  const deviceId = req.headers['x-device-id'] || '';
  const platform = req.headers['x-platform'] || '';
  
  const ua = new UAParser(req.headers['user-agent'] || '');
  const uaResult = ua.getResult();
  
  const raw = `${deviceId}|${platform}|${uaResult.os.name || ''}|${uaResult.browser.name || ''}`;
  return crypto.createHash('sha256').update(raw).digest('hex').slice(0, 128);
}

/**
 * Register or update a device for a user
 */
async function registerOrUpdateDevice(userId, req) {
  const fingerprint = buildFingerprint(req);
  const ua = new UAParser(req.headers['user-agent'] || '');
  const uaResult = ua.getResult();
  
  const platform = req.headers['x-platform'] || uaResult.os.name || 'Unknown';
  const deviceName = req.headers['x-device-name'] || `${uaResult.browser.name || ''} on ${uaResult.os.name || ''}`.trim() || 'Unknown Device';
  
  try {
    // Check if device exists for this user
    const result = await query(
      `SELECT id, device_name, trust_status 
       FROM user_devices 
       WHERE user_id = $1 AND device_fingerprint = $2`,
      [userId, fingerprint]
    );
    
    if (result.rows.length > 0) {
      // Update last seen
      await query(
        `UPDATE user_devices 
         SET last_seen_at = NOW(), last_seen_ip = $2 
         WHERE id = $1`,
        [result.rows[0].id, req.ip]
      );
      
      return {
        deviceId: result.rows[0].id,
        isNew: false,
        trustStatus: result.rows[0].trust_status,
        deviceName: result.rows[0].device_name
      };
    }
    
    // Insert new device
    const insertResult = await query(
      `INSERT INTO user_devices (user_id, device_fingerprint, device_name, platform, trust_status, first_seen_at, last_seen_at, last_seen_ip)
       VALUES ($1, $2, $3, $4, 'pending', NOW(), NOW(), $5)
       RETURNING id`,
      [userId, fingerprint, deviceName, platform, req.ip]
    );
    
    logger.warn('New device registered', { userId, deviceId: insertResult.rows[0].id, deviceName, ip: req.ip });
    
    return {
      deviceId: insertResult.rows[0].id,
      isNew: true,
      trustStatus: 'pending',
      deviceName
    };
  } catch (err) {
    logger.error('Failed to register device', { error: err.message, stack: err.stack });
    throw err;
  }
}

/**
 * List all non-revoked devices for a user
 */
async function listUserDevices(userId) {
  try {
    const result = await query(
      `SELECT id, device_fingerprint, device_name, platform, trust_status, first_seen_at, last_seen_at, last_seen_ip
       FROM user_devices
       WHERE user_id = $1 AND trust_status != 'revoked'
       ORDER BY last_seen_at DESC`,
      [userId]
    );
    
    return result.rows.map(row => ({
      deviceId: row.id,
      fingerprint: row.device_fingerprint,
      deviceName: row.device_name,
      platform: row.platform,
      trustStatus: row.trust_status,
      firstSeenAt: row.first_seen_at,
      lastSeenAt: row.last_seen_at,
      lastSeenIp: row.last_seen_ip
    }));
  } catch (err) {
    logger.error('Failed to list user devices', { error: err.message, stack: err.stack });
    throw err;
  }
}

/**
 * Revoke a device and its sessions
 */
async function revokeDevice(userId, deviceId) {
  try {
    await query(
      `UPDATE user_devices 
       SET trust_status = 'revoked', revoked_at = NOW() 
       WHERE id = $1 AND user_id = $2`,
      [deviceId, userId]
    );
    
    await query(
      `UPDATE sessions 
       SET status = 'revoked', revoked_at = NOW() 
       WHERE device_id = $1`,
      [deviceId]
    );
    
    return { success: true };
  } catch (err) {
    logger.error('Failed to revoke device', { error: err.message, stack: err.stack });
    throw err;
  }
}

module.exports = { buildFingerprint, registerOrUpdateDevice, listUserDevices, revokeDevice };
