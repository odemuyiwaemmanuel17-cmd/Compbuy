const crypto = require('crypto');
const { query } = require('../config/db');
const logger = require('./logger');

/**
 * Compute hash for a row in the audit chain
 */
function computeRowHash({ prevHash, actorId, action, entityType, entityId, metadata, ip, createdAt }) {
  const data = {
    prevHash,
    actorId,
    action,
    entityType,
    entityId,
    metadata: metadata || {},
    ip,
    createdAt: createdAt ? createdAt.toISOString() : new Date().toISOString()
  };
  return crypto.createHash('sha256').update(JSON.stringify(data)).digest('hex');
}

/**
 * Record an audit event with hash chaining
 * Never throws - catches and logs errors
 */
async function recordAuditEvent({ actorId, action, entityType, entityId, metadata, ip }) {
  try {
    const client = await require('../config/db').getClient();
    
    try {
      await client.query('BEGIN');
      
      // Lock the latest row to prevent race conditions
      const lockResult = await client.query(
        'SELECT row_hash FROM audit_log ORDER BY sequence_num DESC LIMIT 1 FOR UPDATE'
      );
      
      const prevHash = lockResult.rows.length > 0 
        ? lockResult.rows[0].row_hash 
        : '0'.repeat(64); // Genesis hash
      
      const createdAt = new Date();
      const rowHash = computeRowHash({
        prevHash,
        actorId,
        action,
        entityType,
        entityId,
        metadata,
        ip,
        createdAt
      });
      
      await client.query(
        `INSERT INTO audit_log (actor_id, action, entity_type, entity_id, metadata, ip_address, prev_hash, row_hash, created_at)
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)`,
        [actorId, action, entityType, entityId, JSON.stringify(metadata), ip, prevHash, rowHash, createdAt]
      );
      
      await client.query('COMMIT');
    } catch (err) {
      await client.query('ROLLBACK');
      throw err;
    } finally {
      client.release();
    }
  } catch (err) {
    logger.error('Failed to record audit event', { error: err.message, stack: err.stack });
  }
}

/**
 * Verify the integrity of the entire audit chain
 */
async function verifyChainIntegrity() {
  try {
    const result = await query(
      'SELECT id, sequence_num, prev_hash, row_hash, actor_id, action, entity_type, entity_id, metadata, ip_address, created_at FROM audit_log ORDER BY sequence_num ASC'
    );
    
    let expectedPrevHash = '0'.repeat(64);
    
    for (const row of result.rows) {
      const computedHash = computeRowHash({
        prevHash: row.prev_hash,
        actorId: row.actor_id,
        action: row.action,
        entityType: row.entity_type,
        entityId: row.entity_id,
        metadata: row.metadata,
        ip: row.ip_address,
        createdAt: row.created_at
      });
      
      if (computedHash !== row.row_hash) {
        return {
          valid: false,
          brokenAtSequence: row.sequence_num,
          message: `Hash mismatch at sequence ${row.sequence_num}`
        };
      }
      
      if (row.prev_hash !== expectedPrevHash && row.sequence_num !== 1n) {
        return {
          valid: false,
          brokenAtSequence: row.sequence_num,
          message: `Chain break at sequence ${row.sequence_num}`
        };
      }
      
      expectedPrevHash = row.row_hash;
    }
    
    return {
      valid: true,
      totalEntries: result.rows.length
    };
  } catch (err) {
    logger.error('Failed to verify audit chain', { error: err.message, stack: err.stack });
    return {
      valid: false,
      error: err.message
    };
  }
}

module.exports = { computeRowHash, recordAuditEvent, verifyChainIntegrity };
