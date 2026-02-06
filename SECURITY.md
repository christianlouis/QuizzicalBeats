# Security Policy

## Supported Versions

We take security seriously and actively maintain the latest version of Quizzical Beats.

| Version | Supported          |
| ------- | ------------------ |
| Latest  | :white_check_mark: |
| < Latest| :x:                |

## Reporting a Vulnerability

If you discover a security vulnerability in Quizzical Beats, please report it responsibly:

1. **DO NOT** open a public GitHub issue
2. Email security details to: christian@kaufdeinquiz.com
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if available)

We will respond within 48 hours and work with you to understand and address the issue.

## Security Best Practices

### Deployment Security

#### 1. Environment Variables

**CRITICAL**: Never use default values in production!

```bash
# Generate secure secrets
python -c 'import secrets; print(secrets.token_hex(32))'  # For SECRET_KEY
python -c 'import secrets; print(secrets.token_urlsafe(32))'  # For AUTOMATION_TOKEN
```

**Required secure variables:**
- `SECRET_KEY`: Flask session encryption (32+ bytes hex)
- `AUTOMATION_TOKEN`: API authentication (32+ bytes URL-safe)

#### 2. HTTPS Configuration

**REQUIRED for production:**

```env
USE_HTTPS=True
PREFERRED_URL_SCHEME=https
DEBUG=False
```

Use a reverse proxy (nginx, Traefik, Caddy) for SSL termination.

#### 3. Database Security

- Use PostgreSQL or MySQL in production (not SQLite)
- Enable database encryption at rest
- Use strong database passwords
- Restrict database network access
- Regular backups with encryption

#### 4. OAuth Configuration

**Redirect URI Security:**
- Use HTTPS redirect URIs in production
- Never use wildcards in redirect URIs
- Validate all OAuth state parameters

**Token Storage:**
- OAuth tokens are encrypted in the database
- Use secure session storage (Redis recommended)
- Set appropriate token expiration times

#### 5. API Keys Protection

**Storage:**
- Store API keys in `.env` file only
- Never commit `.env` to version control
- Use secret management services (e.g., AWS Secrets Manager, HashiCorp Vault)

**Rotation:**
- Rotate Spotify/Deezer API credentials regularly
- Update OAuth client secrets periodically
- Monitor API key usage for anomalies

### Application Security

#### 1. Authentication

- Use strong passwords (12+ characters, mixed case, numbers, symbols)
- Enable multi-factor authentication via OAuth providers
- Implement account lockout after failed login attempts
- Use secure password hashing (werkzeug PBKDF2-SHA256)

#### 2. Session Management

- Sessions expire after inactivity
- Use secure, httponly cookies
- CSRF protection enabled (Flask-WTF)
- Session data encrypted with SECRET_KEY

#### 3. Input Validation

- All user inputs are validated
- SQL injection protected via SQLAlchemy ORM
- XSS protection via template auto-escaping
- File upload validation (type, size limits)

#### 4. Rate Limiting

**Recommendations:**
```python
# Add to production deployment
- Login endpoints: 5 attempts per minute
- API endpoints: 100 requests per minute
- File uploads: 10 per hour
```

#### 5. Dependency Management

**Current Known Issues:**
- ~~authlib < 1.6.5~~ (FIXED: upgraded to 1.6.5+)

**Maintenance:**
```bash
# Check for vulnerabilities
pip install safety
safety check

# Update dependencies
pip list --outdated
pip install --upgrade <package>
```

### Infrastructure Security

#### 1. Docker Security

**Best practices:**
```dockerfile
# Use non-root user
USER musicround

# Minimize attack surface
FROM python:3.11-slim

# Security updates
RUN apt-get update && apt-get upgrade -y
```

#### 2. Network Security

- Use firewall rules (only expose ports 80, 443)
- Implement DDoS protection (Cloudflare, AWS Shield)
- Use VPN for administrative access
- Enable audit logging

#### 3. File System Security

```bash
# Secure file permissions
chmod 600 .env
chmod 700 data/
chmod 755 musicround/

# Restrict write access
chown -R musicround:musicround /app
```

#### 4. Backup Security

- Encrypt backups at rest and in transit
- Store backups in separate location/region
- Test backup restoration regularly
- Implement retention policies (30-90 days)

### Monitoring and Logging

#### 1. Security Logging

**Log these events:**
- Failed login attempts
- Password changes
- OAuth token creation/refresh
- API key usage
- Admin actions
- File uploads/downloads

#### 2. Alerting

**Configure alerts for:**
- Multiple failed logins
- Unusual API traffic patterns
- Database errors
- Backup failures
- Certificate expiration

#### 3. Audit Trail

```python
# Enable comprehensive logging
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
```

## Security Checklist for Production

- [ ] Generated secure SECRET_KEY (32+ bytes)
- [ ] Generated secure AUTOMATION_TOKEN (32+ bytes)
- [ ] Set DEBUG=False
- [ ] Enabled HTTPS (USE_HTTPS=True)
- [ ] Using production database (PostgreSQL/MySQL)
- [ ] Database credentials are strong and unique
- [ ] All OAuth redirect URIs use HTTPS
- [ ] API keys rotated from defaults
- [ ] Reverse proxy configured (nginx/Traefik)
- [ ] Firewall rules enabled
- [ ] SSL certificate valid and auto-renewing
- [ ] Automated backups configured
- [ ] Backup encryption enabled
- [ ] Security monitoring enabled
- [ ] Logs reviewed regularly
- [ ] Dependencies up to date
- [ ] File permissions restricted
- [ ] Running as non-root user
- [ ] Rate limiting implemented
- [ ] CSRF protection enabled

## Security Updates

We recommend:
1. Subscribe to security advisories for Python, Flask, and dependencies
2. Review [GitHub Security Advisories](https://github.com/christianlouis/QuizzicalBeats/security/advisories)
3. Monitor the [CHANGELOG](https://quizzicalbeats.readthedocs.io/changelog.html) for security updates
4. Join our security mailing list (coming soon)

## Compliance

### Data Protection

- User data stored securely with encryption
- OAuth tokens encrypted at rest
- Personal information minimization
- Data retention policies implemented

### GDPR Considerations

- User data export available
- Account deletion supported
- Privacy policy available
- Cookie consent implemented

## Security Tools

### Recommended Tools

```bash
# Static analysis
pip install bandit
bandit -r musicround/

# Dependency scanning
pip install safety
safety check

# Secret detection
git-secrets --scan

# Container scanning
docker scan quizzicalbeats:latest
```

### CI/CD Security

**GitHub Actions recommended checks:**
- Dependency vulnerability scanning
- Static code analysis (CodeQL)
- Secret scanning
- Container image scanning
- License compliance

## Known Security Considerations

### Current Limitations

1. **SQLite in Development**: Not suitable for concurrent production use
2. **File System Storage**: MP3 files stored locally (consider S3 for scale)
3. **Session Storage**: In-memory sessions don't scale (use Redis)
4. **Rate Limiting**: Not implemented (add nginx/Cloudflare)

### Future Improvements

- [ ] Add two-factor authentication (TOTP)
- [ ] Implement rate limiting middleware
- [ ] Add security headers middleware
- [ ] Content Security Policy (CSP)
- [ ] Subresource Integrity (SRI)
- [ ] Add honeypot fields to forms
- [ ] Implement IP reputation checking
- [ ] Add user session management dashboard

## Resources

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [Flask Security Guide](https://flask.palletsprojects.com/en/latest/security/)
- [Python Security Best Practices](https://python.readthedocs.io/en/latest/library/security_warnings.html)
- [Docker Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Docker_Security_Cheat_Sheet.html)

## Contact

For security concerns, contact:
- Email: christian@kaufdeinquiz.com
- Maintainer: Christian Krakau-Louis
- Response Time: Within 48 hours

---

*Last updated: February 2026*
