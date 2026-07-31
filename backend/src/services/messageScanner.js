/**
 * Message scanner for detecting off-platform communication attempts
 * Pure functions, no imports
 */

const PHONE_REGEX = /(?:^|\s|(?<=\D))(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{2,4}\)?[\s.-]?)?\d{3,4}[\s.-]?\d{4}(?:\s*(?:x|ext|extension)[\s.-]?\d{1,5})?(?=\s|$)/gi;
const EMAIL_REGEX = /[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/gi;

const OFF_PLATFORM_PHRASES = [
  'whatsapp',
  'telegram',
  'pay directly',
  'bank transfer to me',
  'send money to',
  'off platform',
  'off the platform',
  'avoid fees',
  'skip the fee',
  'my account number',
  'wire directly',
  'cash payment',
  'meet outside',
  'outside this platform'
];

/**
 * Scan message body for flags
 * @param {string} body - Message content
 * @returns {{flagged: boolean, flags: string[], riskLevel: 'none'|'medium'|'high'}}
 */
function scanMessage(body) {
  if (!body || typeof body !== 'string') {
    return { flagged: false, flags: [], riskLevel: 'none' };
  }
  
  const lowerBody = body.toLowerCase();
  const flags = [];
  
  // Check for phone numbers
  const phones = lowerBody.match(PHONE_REGEX);
  if (phones && phones.length > 0) {
    flags.push('phone_number');
  }
  
  // Check for emails
  const emails = lowerBody.match(EMAIL_REGEX);
  if (emails && emails.length > 0) {
    flags.push('email_address');
  }
  
  // Check for off-platform phrases
  let hasOffPlatformLanguage = false;
  for (const phrase of OFF_PLATFORM_PHRASES) {
    if (lowerBody.includes(phrase)) {
      flags.push(`off_platform:${phrase}`);
      hasOffPlatformLanguage = true;
    }
  }
  
  // Determine risk level
  let riskLevel = 'none';
  if (hasOffPlatformLanguage) {
    riskLevel = 'high';
  } else if (flags.length > 0) {
    riskLevel = 'medium';
  }
  
  return {
    flagged: flags.length > 0,
    flags,
    riskLevel
  };
}

module.exports = { scanMessage };
