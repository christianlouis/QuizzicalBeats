# Quizzical Beats - Project Roadmap

**Version**: 2026.Q3
**Last Updated**: July 9, 2026

## Vision Statement

Quizzical Beats aims to be the premier platform for creating, managing, and delivering engaging music quiz experiences. Our roadmap focuses on reliability, scalability, user experience, and AI-powered innovation.

## Current Status

**Latest Release**: v1.10 - "Import Infrastructure"
**Active Development**: v2.x - Reliability, Performance, and Agentic Round Production
**Repository Health**: 🟡 Production-hardening in progress; managed database cutover is complete, artifact storage and managed-database backups remain the main HA blockers

---

## 🎯 Strategic Priorities (2026)

### Q1 2026: Foundation & Security
**Focus**: Security hardening, stability, and production readiness

### Q2 2026: Scale & Performance  
**Focus**: Concurrent operations, infrastructure, queue systems

### Q3 2026: Intelligence & Automation
**Focus**: AI features, scraping, advanced search

### Q4 2026: Collaboration & Cloud
**Focus**: Multi-user features, cloud storage, sharing

---

## 📋 Release Schedule

### ✅ Completed Releases

#### v1.0 - "Spotify Integration Fix"
*Released: Q4 2024*
- ✅ Spotify playlist import with pagination
- ✅ API rate limit handling
- ✅ Refactored Spotify client
- ✅ Comprehensive logging

#### v1.1 - "Authentication Foundation"
*Released: Q4 2024*
- ✅ User database schema
- ✅ Local authentication system
- ✅ User management interfaces
- ✅ Role-based access control
- ✅ Secure password handling

#### v1.2 - "Spotify OAuth Integration"
*Released: Q1 2025*
- ✅ User-specific Spotify tokens
- ✅ OAuth login option
- ✅ Service account fallback
- ✅ Playlist-user linking

#### v1.3 - "Enhanced User Experience"
*Released: Q1 2025*
- ✅ Custom intro/outro/replay MP3s
- ✅ User-specific email settings
- ✅ User preferences system

#### v1.4 - "Multi-Provider OAuth"
*Released: Q2 2025*
- ✅ Google OAuth integration
- ✅ Authentik OAuth integration
- ✅ Unified authentication experience

#### v1.5 - "Advanced Features"
*Released: Q2 2025*
- ✅ Comprehensive logging
- ✅ System monitoring

#### v1.6 - "Bulletproof Backups"
*Released: Q3 2025*
- ✅ Full system backup/restore
- ✅ Scheduled backups (Ofelia)
- ✅ Admin backup management UI
- ✅ Backup versioning
- ✅ Retention policies
- ✅ CLI backup tools

#### v1.7 - "Dropbox Dispatch"
*Released: Q4 2025*
- ✅ Dropbox OAuth per-user
- ✅ Round export to Dropbox
- ✅ ZIP and PDF export
- ✅ Token refresh handling

#### v1.8 - "Documentation Dynamo"
*Released: Q4 2025*
- ✅ User guide with screenshots
- ✅ FAQ section
- ✅ API documentation
- ✅ Architecture documentation
- ✅ Deployment guides
- ✅ MkDocs portal
- ✅ ReadTheDocs integration

#### v1.9 - "Security Hardening" 
*Released: Q1 2026*
- ✅ Upgraded authlib to 1.6.5+ (CVE fixes)
- ✅ Required secure SECRET_KEY
- ✅ Required secure AUTOMATION_TOKEN
- ✅ Comprehensive SECURITY.md
- ✅ .env.example template
- ✅ Security documentation

#### v1.10 - "Import Infrastructure"
*Released: Q2 2026*
- ✅ Database-backed import queue foundation
- ✅ Background import workers
- ✅ Import queue status surfaces for users and agents
- ✅ Initial MCP automation support for round production workflows
- ✅ Server-side catalog pagination and filters

---

### 🚀 Upcoming Releases

#### v2.0 - "Import Infrastructure" *(Q1 2026 - HIGH PRIORITY)*
**Status**: 🟡 In Progress
**Priority**: Critical  
**Effort**: 2-3 weeks

**Goals**: Harden the v1.10 import infrastructure foundation for production-scale autonomous workflows.

**Features**:
- [x] Database-backed import queue system
- [x] Background worker processes
- [x] Concurrent import job support
- [x] Priority queue handling
- [x] Job retry logic
- [x] Dead letter queue for failures

**Success Metrics**:
- Import 1000+ song playlists without timeout
- Support 5+ concurrent imports
- 99% job completion rate

**Dependencies**:
- Worker orchestration (Docker Compose)
- Redis/RQ or Celery remains optional if import volume outgrows the database-backed queue

---

#### v2.1 - "Progress Pulse" *(Q1 2026 - HIGH PRIORITY)*
**Status**: 🟡 In Progress
**Priority**: High  
**Effort**: 1-2 weeks

**Goals**: Real-time import status tracking

**Features**:
- [x] JSON polling endpoint for queue and job status
- [ ] WebSocket/SSE progress updates
- [ ] Progress bars for active imports
- [x] Detailed error reporting with retry/dead-letter state
- [x] Manual recovery options for failed imports
- [ ] Email notifications on completion
- [ ] Import history dashboard

**Success Metrics**:
- Real-time progress updates (<1s latency)
- Clear error messages for 90%+ failures
- User satisfaction with transparency

**Dependencies**:
- v2.0 (Import Infrastructure)
- Flask-SocketIO or SSE

---

#### v2.2 - "Server Stability" *(Q1 2026 - HIGH PRIORITY)*
**Status**: ✅ Complete
**Priority**: Critical  
**Effort**: 1 week

**Goals**: Production-grade web server

**Features**:
- [x] Replace Flask dev server with Gunicorn
- [x] Configure worker processes and threads
- [x] Graceful shutdown/restart through Gunicorn entrypoint
- [x] Reverse proxy assumptions documented and smoke-tested
- [x] SSL termination verified by deployment smoke
- [x] Static file optimization
- [x] Response compression
- [x] Security headers

**Success Metrics**:
- Handle 100+ concurrent users
- <500ms median response time
- 99.9% uptime
- Zero downtime deployments

**Dependencies**:
- Docker configuration updates
- Edge or reverse-proxy configuration

---

#### v2.3 - "Database Durability" *(Q2 2026 - HIGH PRIORITY)*
**Status**: 🟡 In Progress
**Priority**: High  
**Effort**: 1-2 weeks

**Goals**: Production database configuration

**Features**:
- [ ] Connection pooling (SQLAlchemy pool)
- [ ] Database query optimization
- [x] Index creation for common catalog, import queue, and scheduled export queries
- [ ] Concurrent write handling
- [ ] Database performance monitoring
- [ ] Read replica support (optional)
- [ ] Zero-downtime migrations

**Success Metrics**:
- Support 50+ concurrent connections
- <100ms query execution (95th percentile)
- No deadlocks or transaction conflicts

**Dependencies**:
- PostgreSQL or MySQL recommended
- Monitoring tools (Prometheus/Grafana)

---

#### v2.4 - "Search Supercharge" *(Q2 2026 - MEDIUM PRIORITY)*
**Status**: 🟢 Complete
**Priority**: Medium  
**Effort**: 2 weeks

**Goals**: Advanced search capabilities

**Features**:
- [x] Shared catalog search across UI and MCP
- [x] Relevance scoring improvements with match explanations
- [x] Advanced song catalog filters (title/artist query, year, genre, preview, usage)
- [x] Tag and tempo filters for agent replacement workflows
- [x] Search result caching
- [x] Faceted search
- [x] Search suggestions/autocomplete
- [x] Search analytics

**Success Metrics**:
- Search results <200ms
- 80%+ user satisfaction with relevance
- Support 10,000+ song database efficiently

**Dependencies**:
- v2.3 (Database Durability)
- Optional: Elasticsearch

---

#### v2.5 - "Performance Pulse" *(Q2 2026 - MEDIUM PRIORITY)*
**Status**: ✅ Complete
**Priority**: Medium  
**Effort**: 1-2 weeks

**Goals**: Application performance optimization

**Features**:
- [x] Database index optimization
- [x] Lazy loading for heavy preview controls
- [x] Pagination for large song and round datasets
- [x] Server-side pagination for the song catalog API
- [x] Server-side pagination and filters for the browser song library
- [x] Server-side pagination for the browser rounds list
- [x] Bounded MP3 preview rendering in large lists
- [x] Catalog analytics summary for usage and preview coverage
- [x] Process-local query result caching
- [x] Performance smoke suite for search, imports, round review, and MCP-like summaries

**Future Scaling Options**:
- [ ] Redis caching layer
- [ ] CDN for static assets
- [ ] Dedicated MP3 preview streaming path

**Success Metrics**:
- Page load <1s (90th percentile)
- Support 10,000+ songs in library
- <100MB memory per worker

**Dependencies**:
- v2.2 (Server Stability)
- Redis for caching

---

#### v2.6 - "Textual Transport" *(Q2 2026 - MEDIUM PRIORITY)*
**Status**: 🟡 In Progress
**Priority**: Medium  
**Effort**: 2 weeks

**Goals**: Text-based playlist import

**Features**:
- [x] Plain text playlist parsing
- [x] CSV format support
- [x] Artist/song detection algorithms
- [x] Confidence scoring for matches
- [x] MCP review payload for unresolved text rows
- [ ] Manual review interface
- [ ] Bulk import workflow
- [ ] Format templates

**Success Metrics**:
- 90%+ accurate matching for clean input
- Support 500+ songs per import
- Clear review workflow for low-confidence matches

---

#### v3.0 - "Rhythm Roundsmith" *(Q3 2026 - HIGH PRIORITY)*
**Status**: 🟡 In Progress
**Priority**: High  
**Effort**: 3-4 weeks

**Goals**: AI-powered quiz generation

**Features**:
- [ ] AI quiz round generation
- [ ] Multiple quiz formats (MCQ, clips, open-ended)
- [x] Theme-based planning brief for agentic generation
- [ ] Metadata-driven questions
- [x] Complete round creation from fully resolved text playlists
- [ ] User review/edit interface
- [x] Recent usage and fatigue context for prompt optimization
- [x] Planned quiz date records for agentic scheduled generation
- [x] Browser round calendar for planned quiz dates
- [x] Draft intro/replay/outro script support for generated rounds
- [x] Persisted script review workflow before TTS assignment
- [ ] AI provider abstraction (OpenAI, Anthropic, local)
- [ ] Cost tracking

**Success Metrics**:
- Generate engaging rounds in <30s
- 80%+ user satisfaction with AI questions
- <$0.10 cost per round generation

**Dependencies**:
- OpenAI API or compatible
- Prompt engineering

---

#### v3.1 - "Curated Collector" *(Q3 2026 - MEDIUM PRIORITY)*
**Status**: 🔴 Not Started  
**Priority**: Medium  
**Effort**: 2-3 weeks

**Goals**: Web scraping for playlists

**Features**:
- [ ] Spotify web scraper
- [ ] HTML/JSON extraction
- [ ] Rate limiting and rotation
- [ ] User-agent rotation
- [ ] Proxy support
- [ ] Scraper detection avoidance
- [ ] Compliance with ToS

**Success Metrics**:
- Successfully scrape 95%+ playlists
- Avoid detection/blocking
- Extract complete metadata

**Legal Note**: ⚠️ Scraping must comply with platform ToS

---

#### v3.2 - "Scraper Symphony" *(Q3 2026 - LOW PRIORITY)*
**Status**: 🔴 Not Started  
**Priority**: Low  
**Effort**: 3 weeks

**Goals**: External music chart data

**Features**:
- [ ] Billboard chart scraper
- [ ] Official Charts scraper
- [ ] 2-3 additional sources
- [ ] Data normalization
- [ ] Spotify record linking
- [ ] Admin review interface
- [ ] Scheduled scraper runs
- [ ] Error logging

**Success Metrics**:
- Weekly chart updates
- 95%+ successful Spotify matching
- Comprehensive historical data

---

#### v3.3 - "Alert Amplifier" *(Q3 2026 - MEDIUM PRIORITY)*
**Status**: 🟡 Mostly Complete
**Priority**: Medium  
**Effort**: 1-2 weeks

**Goals**: Comprehensive notification system

**Features**:
- [ ] Email verification
- [x] Import completion and dead-letter notifications
- [x] Blocked-round repair notifications with quality-gate hints
- [x] OAuth token expiration warnings in the profile UI
- [x] Proactive OAuth token expiration email CLI
- [x] Admin usage summaries with import, failed-send, service-health, and backup-readiness findings
- [ ] Push notifications (browser/Telegram)
- [x] Notification preferences
- [x] Digest emails

**Success Metrics**:
- <5s notification delivery
- 90%+ email deliverability
- User-controlled notification settings

---

#### v4.0 - "Storage Sanctuary" *(Q4 2026 - HIGH PRIORITY)*
**Status**: 🔴 Not Started  
**Priority**: High  
**Effort**: 3-4 weeks

**Goals**: Cloud storage integration

**Features**:
- [ ] Storage backend abstraction
- [ ] AWS S3 support
- [ ] S3-compatible storage (MinIO, Wasabi)
- [ ] Dropbox storage backend
- [ ] Unified management UI
- [ ] Cloud backup storage
- [ ] MP3 cloud storage
- [ ] Differential uploads
- [ ] Background synchronization

**Success Metrics**:
- Support 100GB+ storage
- <$10/month storage costs
- Automatic failover between providers

**Dependencies**:
- boto3 (AWS SDK)
- Storage abstraction layer

---

#### v4.1 - "Collaboration Core" *(Q4 2026 - MEDIUM PRIORITY)*
**Status**: 🟡 In Progress
**Priority**: Medium  
**Effort**: 3 weeks

**Goals**: Multi-user collaboration

**Features**:
- [ ] Shared round editing
- [x] Persisted round ownership and viewer/editor share grants
- [x] Browser owner/visibility filtering and edit-route access checks
- [ ] Collaboration roles beyond viewer/editor (comment/admin)
- [ ] User invitations via email/username UI
- [ ] Presence indicators
- [ ] Revision history
- [ ] Public sharing links
- [ ] Access audit logs
- [ ] Comment threads

**Success Metrics**:
- Real-time collaboration (<2s sync)
- Support 10+ simultaneous editors
- Full audit trail for compliance

---

#### v4.2 - "Profile Personalizer" *(Q4 2026 - LOW PRIORITY)*
**Status**: 🟡 Partially Complete
**Priority**: Low  
**Effort**: 1 week

**Features**:
- [x] Custom user MP3 fallbacks
- [x] Persistent user settings
- [ ] Default round format preferences
- [ ] Personal tag system
- [x] Curated tag filtering and sorting in the round builder, including internal/noisy tag suppression
- [ ] Dark mode toggle
- [ ] UI customization

---

#### v4.3 - "Deployment Dynamo" *(Q4 2026 - HIGH PRIORITY)*
**Status**: ✅ Complete
**Priority**: High  
**Effort**: 2 weeks

**Goals**: CI/CD and automation

**Features**:
- [x] GitHub Actions CI/CD pipeline
- [x] Automated testing
- [x] Automated Docker builds
- [x] Backup readiness checks for managed SQL deployments
- [ ] Sentry error tracking
- [x] Deployment smoke CLI for release verification
- [x] Health check endpoint (/healthz)
- [x] Admin digest surfaces service-health and backup-readiness findings

**Success Metrics**:
- <10min build and deploy time
- Automated security scanning
- Zero-downtime deployments

---

## 🔮 Future Considerations (2027+)

## GitHub Issue Alignment

The issue backlog has been split into repository-local slices and live
operational work in [Agentic Backlog Status](docs/developer-guide/backlog-status.md).
Agents should use that crosswalk before starting new work so completed slices
such as import retry handling, text playlist parsing, round readiness badges,
quizmaster context, planned quiz dates, and TTS script review are not rebuilt.

### Ideas Under Evaluation

#### "Blind Test" Mode
- Hide title/artist metadata during play
- Reveal answers on command
- Scoring system

#### Team Scoreboard
- Live projection mode
- Real-time score tracking
- Leaderboard display

#### Public Round Library
- Community-shared rounds
- Clone and customize
- Rating and reviews
- Trending rounds

#### REST API
- Third-party integrations
- Trivia bot support
- Mobile app backend
- Webhook support

#### Audio Fingerprinting
- Validate user uploads
- Detect duplicates
- Copyright compliance

#### Round Analytics
- Usage frequency
- Popularity metrics
- User ratings
- A/B testing

#### Video Tutorials
- Complex workflow guides
- YouTube integration
- Interactive help

#### Keyboard Shortcuts
- Power user features
- Accessibility improvements
- Documentation

---

## 📊 Metrics & KPIs

### User Metrics
- Monthly Active Users (MAU)
- Round Creation Rate
- Export Success Rate
- User Retention (30/60/90 day)

### Performance Metrics
- Page Load Time (p50, p95, p99)
- API Response Time
- Error Rate (<0.1% target)
- Uptime (99.9% target)

### Technical Metrics
- Test Coverage (>80% target)
- Code Quality Score
- Security Vulnerabilities (0 high/critical)
- Dependency Freshness

---

## 🎯 Success Criteria

### By Q2 2026
- [ ] 100+ active users
- [ ] 99.5% uptime
- [ ] <1s median page load
- [ ] Support 10,000+ songs per user
- [ ] All critical security issues resolved

### By Q4 2026
- [ ] 500+ active users
- [ ] 99.9% uptime
- [ ] AI-generated rounds feature
- [ ] Cloud storage integration
- [ ] Collaboration features
- [ ] Full CI/CD pipeline

---

## 📞 Feedback & Contributions

We welcome community feedback on this roadmap!

- **GitHub Discussions**: Share ideas and vote on features
- **GitHub Issues**: Report bugs and request features
- **Email**: christian@kaufdeinquiz.com

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines.

---

## 📝 Changelog

| Date | Change |
|------|--------|
| 2026-07 | Marked managed database cutover complete and narrowed remaining HA blockers to artifact storage and managed-database backups |
| 2026-07 | Realigned roadmap status with v1.10 Import Infrastructure and PR #142 reliability work |
| 2026-02 | Added v1.9 Security Hardening release |
| 2026-02 | Initial comprehensive roadmap created |
| 2025-12 | v1.8 Documentation Dynamo completed |
| 2025-10 | v1.7 Dropbox Dispatch completed |

---

*This roadmap is subject to change based on user feedback, technical constraints, and strategic priorities.*
