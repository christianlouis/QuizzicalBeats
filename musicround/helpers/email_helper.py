"""
Email helper functions for Quizzical Beats
"""
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from flask import current_app

EMAIL_CONFIGURATION_ERROR = "Email server configuration is incomplete. Check the server logs."
EMAIL_DELIVERY_ERROR = "Email delivery failed. Check the server logs."


def email_configuration_status(required=False):
    """Return SMTP configuration status without exposing configured values."""
    required_keys = ["MAIL_HOST", "MAIL_PORT", "MAIL_USERNAME", "MAIL_PASSWORD", "MAIL_SENDER"]
    missing = [key for key in required_keys if not current_app.config.get(key)]
    return {
        "configured": not missing,
        "missing": missing if required else [],
        "host_configured": bool(current_app.config.get("MAIL_HOST")),
        "port_configured": bool(current_app.config.get("MAIL_PORT")),
        "username_configured": bool(current_app.config.get("MAIL_USERNAME")),
        "password_configured": bool(current_app.config.get("MAIL_PASSWORD")),
        "sender_configured": bool(current_app.config.get("MAIL_SENDER")),
        "tls_enabled": bool(current_app.config.get("MAIL_USE_TLS", False)),
        "ssl_enabled": bool(current_app.config.get("MAIL_USE_SSL", False)),
    }


def verify_email_delivery(recipient=None, send=False):
    """Verify SMTP configuration and optionally send a test message."""
    status = email_configuration_status(required=True)
    result = {
        "ok": status["configured"],
        "dry_run": not send,
        "configured": status["configured"],
        "missing": status["missing"],
        "recipient": recipient or current_app.config.get("MAIL_RECIPIENT"),
        "sent": False,
        "message": "Email configuration is complete." if status["configured"] else EMAIL_CONFIGURATION_ERROR,
        "config": {
            "host_configured": status["host_configured"],
            "port_configured": status["port_configured"],
            "username_configured": status["username_configured"],
            "password_configured": status["password_configured"],
            "sender_configured": status["sender_configured"],
            "tls_enabled": status["tls_enabled"],
            "ssl_enabled": status["ssl_enabled"],
        },
    }
    if not status["configured"] or not send:
        return result
    if not result["recipient"]:
        result.update(
            {
                "ok": False,
                "message": "Email verification recipient is missing.",
                "missing": sorted(set(result["missing"] + ["recipient"])),
            }
        )
        return result

    success, message = send_email(
        recipient=result["recipient"],
        subject="Quizzical Beats email verification",
        body_text=(
            "This is a Quizzical Beats email verification message. "
            "If you received it, SMTP delivery is working."
        ),
    )
    result["sent"] = success
    result["ok"] = success
    result["message"] = "Email verification sent." if success else message
    return result


def send_account_verification_email(recipient, username, verification_url):
    """Send a local-account verification email without exposing token details in logs."""
    return send_email(
        recipient=recipient,
        subject="Verify your Quizzical Beats email address",
        body_text=(
            f"Hello {username},\n\n"
            "Confirm your email address to activate your Quizzical Beats account:\n"
            f"{verification_url}\n\n"
            "This link expires in 24 hours. If you did not create this account, ignore this email."
        ),
    )


def send_email(recipient, subject, body_text, attachments=None):
    """
    Sends an email with optional attachments.
    
    Args:
        recipient (str): Email address of the recipient
        subject (str): Email subject
        body_text (str): Plain text email body
        attachments (list): Optional list of attachment dictionaries with keys:
                            - 'data': The binary data of the attachment
                            - 'filename': Filename for the attachment
                            - 'mimetype': Mimetype string like 'application/pdf'
                            
    Returns:
        tuple: (success, message) where success is a boolean and message contains
               details about the result
    """
    # Get mail configuration from environment variables
    mail_host = current_app.config.get('MAIL_HOST')
    mail_port = current_app.config.get('MAIL_PORT')
    mail_username = current_app.config.get('MAIL_USERNAME')
    mail_password = current_app.config.get('MAIL_PASSWORD')
    mail_sender = current_app.config.get('MAIL_SENDER')
    mail_use_tls = current_app.config.get('MAIL_USE_TLS', False)
    mail_use_ssl = current_app.config.get('MAIL_USE_SSL', False)
    
    # Check if all email configuration parameters are available
    missing_config = []
    if not mail_host:
        missing_config.append("MAIL_HOST")
    if not mail_port:
        missing_config.append("MAIL_PORT")
    if not mail_username:
        missing_config.append("MAIL_USERNAME")
    if not mail_password:
        missing_config.append("MAIL_PASSWORD")
    if not mail_sender:
        missing_config.append("MAIL_SENDER")
    
    if missing_config:
        missing_params = ", ".join(missing_config)
        error_msg = f"Email server configuration is incomplete. Missing parameters: {missing_params}."
        current_app.logger.error(f"Email configuration error: {error_msg}")
        current_app.logger.error(f"Current config values - MAIL_HOST: {'set' if mail_host else 'missing'}, "
                               f"MAIL_PORT: {'set' if mail_port else 'missing'}, "
                               f"MAIL_USERNAME: {'set' if mail_username else 'missing'}, "
                               f"MAIL_PASSWORD: {'set' if mail_password else 'missing'}, "
                               f"MAIL_SENDER: {'set' if mail_sender else 'missing'}")
        return False, EMAIL_CONFIGURATION_ERROR

    # Create message object
    msg = MIMEMultipart()
    msg['From'] = mail_sender
    msg['To'] = recipient
    msg['Subject'] = subject
    
    # Attach text body
    msg.attach(MIMEText(body_text, 'plain'))

    # Attach files if provided
    if attachments:
        for attachment in attachments:
            part = MIMEBase(
                attachment.get('mimetype', 'application/octet-stream').split('/')[0],
                attachment.get('mimetype', 'application/octet-stream').split('/')[1]
            )
            part.set_payload(attachment['data'])
            encoders.encode_base64(part)
            part.add_header(
                'Content-Disposition',
                f'attachment; filename={attachment["filename"]}'
            )
            msg.attach(part)

    try:
        current_app.logger.info(f"Attempting to send email to {recipient} via {mail_host}:{mail_port}")
        smtp_client = smtplib.SMTP_SSL if mail_use_ssl else smtplib.SMTP
        with smtp_client(mail_host, mail_port, timeout=30) as server:
            if mail_use_ssl:
                current_app.logger.debug("Implicit TLS SMTP connection established")
            elif mail_use_tls:
                server.starttls()
                current_app.logger.debug("STARTTLS established")
            else:
                current_app.logger.debug("Plain SMTP connection established")
            server.login(mail_username, mail_password)
            current_app.logger.debug(f"Login successful for {mail_username}")
            server.sendmail(mail_sender, recipient, msg.as_string())
            current_app.logger.info(f"Email sent successfully from {mail_sender} to {recipient}")
        
        return True, f'Email sent successfully to {recipient}!'
            
    except smtplib.SMTPException as e:
        current_app.logger.error("SMTP Error: %s", e, exc_info=True)
        current_app.logger.error(
            "Failed to send email from %s to %s via %s:%s",
            mail_sender,
            recipient,
            mail_host,
            mail_port,
        )
        return False, EMAIL_DELIVERY_ERROR
    except Exception as e:
        current_app.logger.error("Unexpected email delivery error: %s", e, exc_info=True)
        return False, EMAIL_DELIVERY_ERROR
