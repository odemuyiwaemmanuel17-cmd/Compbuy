const nodemailer = require('nodemailer');
const logger = require('./logger');

const SMTP_HOST = process.env.SMTP_HOST;
const SMTP_PORT = parseInt(process.env.SMTP_PORT, 10) || 587;
const SMTP_SECURE = process.env.SMTP_SECURE === 'true';
const SMTP_USER = process.env.SMTP_USER;
const SMTP_PASS = process.env.SMTP_PASS;
const EMAIL_FROM = process.env.EMAIL_FROM || 'Compbuy <noreply@compbuy.ng>';

// Create transporter
const transporter = nodemailer.createTransport({
  host: SMTP_HOST,
  port: SMTP_PORT,
  secure: SMTP_SECURE,
  auth: SMTP_USER && SMTP_PASS ? {
    user: SMTP_USER,
    pass: SMTP_PASS
  } : undefined
});

/**
 * Base HTML template for branded emails
 */
function createHtmlTemplate({ title, content, footerText }) {
  return `
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${title}</title>
</head>
<body style="margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background-color:#f2f0ea;">
  <table role="presentation" style="width:100%;border-collapse:collapse;">
    <tr>
      <td align="center" style="padding:40px 20px;">
        <table role="presentation" style="max-width:600px;width:100%;border-collapse:collapse;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.1);">
          <!-- Header -->
          <tr>
            <td style="background:#0a0f1c;padding:32px;text-align:center;">
              <h1 style="margin:0;color:#b8923f;font-family:Georgia,serif;font-size:28px;font-style:italic;">Comp<wbr>buy</h1>
              <p style="margin:8px 0 0;color:#faf9f6;font-size:14px;opacity:0.8;">Nigeria's Verified Marketplace</p>
            </td>
          </tr>
          <!-- Body -->
          <tr>
            <td style="padding:40px 32px;background:#faf9f6;">
              ${content}
            </td>
          </tr>
          <!-- Footer -->
          <tr>
            <td style="background:#111827;padding:24px 32px;text-align:center;color:#e8e4d9;font-size:13px;">
              ${footerText || '<p style="margin:0;">&copy; 2025 Compbuy. All rights reserved.</p>'}
              <p style="margin:12px 0 0;opacity:0.7;">This is an automated message. Please do not reply.</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
  `.trim();
}

/**
 * Send verification email
 */
async function sendVerificationEmail(user, verifyToken) {
  const verifyUrl = `${process.env.FRONTEND_URL}/verify-email?token=${verifyToken}`;
  
  const content = `
    <h2 style="margin:0 0 16px;color:#0a0f1c;font-size:22px;">Verify Your Email</h2>
    <p style="margin:0 0 16px;color:#111827;line-height:1.6;">Welcome to Compbuy, ${user.first_name || 'there'}!</p>
    <p style="margin:0 0 24px;color:#111827;line-height:1.6;">Please verify your email address to complete your registration:</p>
    <table role="presentation"><tr><td align="center" style="padding:16px 32px;background:#b8923f;border-radius:6px;">
      <a href="${verifyUrl}" style="color:#0a0f1c;text-decoration:none;font-weight:600;">Verify Email Address</a>
    </td></tr></table>
    <p style="margin:24px 0 0;color:#6b7280;font-size:14px;">Or copy this link: ${verifyUrl}</p>
  `;
  
  await sendEmail({
    to: user.email,
    subject: 'Verify Your Compbuy Account',
    html: createHtmlTemplate({ title: 'Verify Email', content, footerText: '' })
  });
}

/**
 * Send password reset email
 */
async function sendPasswordResetEmail(user, resetToken) {
  const resetUrl = `${process.env.FRONTEND_URL}/reset-password?token=${resetToken}`;
  
  const content = `
    <h2 style="margin:0 0 16px;color:#0a0f1c;font-size:22px;">Password Reset Request</h2>
    <p style="margin:0 0 16px;color:#111827;line-height:1.6;">You requested a password reset for your Compbuy account.</p>
    <p style="margin:0 0 24px;color:#111827;line-height:1.6;">Click below to set a new password:</p>
    <table role="presentation"><tr><td align="center" style="padding:16px 32px;background:#b8923f;border-radius:6px;">
      <a href="${resetUrl}" style="color:#0a0f1c;text-decoration:none;font-weight:600;">Reset Password</a>
    </td></tr></table>
    <p style="margin:24px 0 0;color:#6b7280;font-size:14px;">This link expires in 1 hour. If you didn't request this, please ignore.</p>
  `;
  
  await sendEmail({
    to: user.email,
    subject: 'Reset Your Compbuy Password',
    html: createHtmlTemplate({ title: 'Password Reset', content, footerText: '' })
  });
}

/**
 * Send new device alert
 */
async function sendNewDeviceAlert(user, deviceName, ip) {
  const content = `
    <h2 style="margin:0 0 16px;color:#0a0f1c;font-size:22px;">New Device Login Alert</h2>
    <p style="margin:0 0 16px;color:#111827;line-height:1.6;">We detected a login to your Compbuy account from a new device:</p>
    <div style="background:#f2f0ea;padding:16px;border-radius:6px;margin:16px 0;">
      <p style="margin:0 0 8px;"><strong>Device:</strong> ${deviceName || 'Unknown'}</p>
      <p style="margin:0;"><strong>IP Address:</strong> ${ip || 'Unknown'}</p>
    </div>
    <p style="margin:0 0 24px;color:#111827;line-height:1.6;">If this wasn't you, please secure your account immediately.</p>
  `;
  
  await sendEmail({
    to: user.email,
    subject: 'New Device Login to Your Compbuy Account',
    html: createHtmlTemplate({ title: 'Security Alert', content, footerText: '' })
  });
}

/**
 * Send KYC status email
 */
async function sendKycStatusEmail(user, status, reason) {
  const statusLabels = { approved: 'Approved', rejected: 'Needs Attention', under_review: 'Under Review' };
  const statusColors = { approved: '#1f7a4d', rejected: '#c14a3a', under_review: '#2b4480' };
  
  const content = `
    <h2 style="margin:0 0 16px;color:#0a0f1c;font-size:22px;">KYC Document ${statusLabels[status] || status}</h2>
    <p style="margin:0 0 16px;color:#111827;line-height:1.6;">Your submitted document has been reviewed.</p>
    ${reason ? `<p style="margin:0 0 24px;color:#111827;line-height:1.6;"><strong>Note:</strong> ${reason}</p>` : ''}
    <p style="margin:24px 0 0;color:#6b7280;font-size:14px;">Log in to your dashboard to view details.</p>
  `;
  
  await sendEmail({
    to: user.email,
    subject: `KYC Document ${statusLabels[status] || status}`,
    html: createHtmlTemplate({ title: 'KYC Update', content, footerText: '' })
  });
}

/**
 * Send inquiry notification to seller
 */
async function sendInquiryNotification(seller, buyer, listing) {
  const content = `
    <h2 style="margin:0 0 16px;color:#0a0f1c;font-size:22px;">New Inquiry on Your Listing</h2>
    <p style="margin:0 0 16px;color:#111827;line-height:1.6;">${buyer.first_name || 'A buyer'} has sent an inquiry about:</p>
    <p style="margin:0 0 16px;color:#b8923f;font-weight:600;">${listing.title}</p>
    <p style="margin:0 0 24px;color:#111827;line-height:1.6;">Log in to your dashboard to respond.</p>
  `;
  
  await sendEmail({
    to: seller.email,
    subject: `New Inquiry: ${listing.title}`,
    html: createHtmlTemplate({ title: 'New Inquiry', content, footerText: '' })
  });
}

/**
 * Internal send function - fire and forget
 */
async function sendEmail({ to, subject, html }) {
  if (!SMTP_HOST || !SMTP_USER || !SMTP_PASS) {
    logger.warn('SMTP not configured, skipping email', { to, subject });
    return;
  }
  
  try {
    await transporter.sendMail({
      from: EMAIL_FROM,
      to,
      subject,
      html
    });
    logger.info('Email sent', { to, subject });
  } catch (err) {
    logger.error('Failed to send email', { error: err.message, to, subject });
  }
}

module.exports = {
  sendVerificationEmail,
  sendPasswordResetEmail,
  sendNewDeviceAlert,
  sendKycStatusEmail,
  sendInquiryNotification
};
