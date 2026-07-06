# Quizzical Beats TODO List

## ✅ Completed Milestones

### Milestone 1: Spotify Integration Fix (Immediate Priority)

* [x] Fix Spotify playlist import functionality

  * [x] Implement proper pagination for playlist retrieval
  * [x] Add better error handling for API rate limits
  * [x] Refactor Spotify client code for maintainability
  * [x] Add logging to track API requests and responses for debugging

### Milestone 2: Authentication Foundation

* [x] Design database schema for users and roles
* [x] Implement basic authentication system with local username/password
* [x] Create user management interfaces (register, login, profile)
* [x] Set up admin role functionality
* [x] Implement secure password handling and session management

### Milestone 3: Spotify Integration with User Accounts

* [x] Migrate Spotify token storage to user-specific model
* [x] Add Spotify OAuth login option
* [x] Create fallback mechanism for service account
* [x] Link user playlists with their Spotify accounts

### Milestone 4: Enhanced User Experience

* [x] Enable user-specific intro/outro/replay MP3s
* [x] Update email system to use logged-in user's email
* [x] Implement user preferences and settings

### Milestone 5: Additional OAuth Providers

* [x] Add Google OAuth integration
* [x] Add Authentik OAuth integration
* [x] Ensure consistent user experience across auth methods

### Milestone 6: Advanced Features & Optimizations

* [x] Create comprehensive logging and monitoring

### Milestone 7: **"Bulletproof Backups" Release** – System Backup & Restore

* [x] Implement full system-wide backup and restore

  * [x] Backup all critical data: DB, rounds, MP3s, user settings
  * [x] Support both manual and scheduled backups
  * [x] Admin UI to download, manage, and restore backups
  * [x] Store backups to local filesystem or optional cloud locations
  * [x] Include versioning to support future schema migration compatibility
  * [x] Add internal backup verification/checksum logic
  * [x] Integrate with Ofelia scheduler for automatic backups
  * [x] Add command-line backup functionality for scripting
  * [x] Implement retention policy for automatic cleanup of old backups
* [x] Add system health check and status dashboard

### Milestone 8: **"Dropbox Dispatch" Release** – Round Export via Dropbox

* [x] Add Dropbox OAuth login per user
* [x] Let users link/unlink and view Dropbox account info
* [x] Export full rounds (metadata + MP3s) as ZIP or PDF
* [x] Push selected rounds to user's Dropbox via UI
* [x] Add fallback handling and Dropbox access token refresh
* [x] Log export actions and errors for transparency

### Milestone 9: **"Documentation Dynamo" Release** – Comprehensive Documentation

* [x] Complete user-facing documentation
  * [x] Create step-by-step user guides with screenshots
  * [x] Add FAQ section based on common support questions
* [x] Developer documentation
  * [x] API documentation with OpenAPI/Swagger spec
  * [x] Database schema documentation with ER diagrams
  * [x] Codebase architecture overview
  * [x] Setup guide for local development environment
* [x] Operations documentation
  * [x] Deployment guide for various environments (Docker, bare metal)
  * [x] Backup and restore procedures
  * [x] Monitoring and alerting setup
  * [x] Troubleshooting common issues
* [x] Create centralized documentation portal
  * [x] Set up MkDocs or similar documentation site
  * [x] Implement search functionality
  * [x] Add version control for documentation
  * [x] Set up automated documentation deployment

---

## 🆕 Upcoming Milestones


### 🎯 Milestone 10: **"Import Infrastructure" Release** – Queue & Worker Setup

* [x] Implement import queue system
* [x] Add background worker process for playlist imports
* [x] Support multiple concurrent import jobs
* [x] Implement priority handling for import jobs
* [x] Add retry tracking and dead-letter handling for failed import jobs

### 🎯 Milestone 11: **"Progress Pulse" Release** – Import Status Tracking

* [x] JSON polling endpoint for import queue and job status
* [x] MCP polling payload for active and recent import jobs
* [ ] Real-time progress indicators for active imports
* [x] Detailed error reporting with retry/dead-letter state
* [x] Manual recovery actions for failed imports
* [ ] Email notifications when imports complete

### 🎯 Milestone 12: **"Search Supercharge" Release** – Enhanced Search

* [ ] Improve search algorithm and relevance scoring
* [x] Normalize, de-duplicate, and curate tag choices in the round builder
* [x] Add advanced song catalog filtering options (year, genre, preview, usage)
* [ ] Implement caching for frequent searches
* [x] Add server-side song catalog pagination for API and agent workflows
* [ ] Ensure proper pagination and performance across all large views

### 🎯 Milestone 13: **"Textual Transport" Release** – Text-Based Playlist Import

* [x] Support for pasting plain text playlists
* [x] Line-by-line parsing with artist/song detection
* [x] Confidence scoring for matches
* [x] MCP review payload for low-confidence matches
* [ ] Manual review interface for low-confidence matches
* [x] Support for various text formats, including headered CSV and plain text
* [x] Create complete rounds from fully resolved text playlists

### 🎯 Milestone 14: **"Curated Collector" Release** – Playlist Scraper

* [ ] Web scraper for Spotify web interface
* [ ] Extract track names and artists from HTML/JSON
* [ ] Format compatibility with text-based import
* [ ] Handle rate limiting and detection prevention

### 🎯 Milestone 15: **"Server Stability" Release** – Production Web Server

* [x] Replace Flask development server with Gunicorn/uWSGI
* [x] Configure proper worker processes and threads
* [x] Implement graceful shutdown and restart capabilities through Gunicorn
* [ ] Add Nginx as reverse proxy with proper caching
* [ ] Set up proper SSL termination and security headers
* [ ] Optimize static file serving

### 🎯 Milestone 16: **"Database Durability" Release** – Concurrent Operations

* [ ] Implement connection pooling
* [x] Add database indexes for catalog, import queue, and scheduled export queries
* [ ] Add broader database query optimizations after profiling production traffic
* [ ] Configure database for concurrent write operations
* [ ] Set up monitoring for database performance
* [ ] Implement read/write splitting if necessary
* [ ] Add database migration safety for zero-downtime upgrades
### 🎯 Milestone 17: **"Scraper Symphony" Release** – External Music Data

* [ ] Identify 2–3 public music chart sources (Billboard, Official Charts, etc.)
* [ ] Build scraper with user-agent rotation and proxy support
* [ ] Normalize results into song data model
* [ ] Link scraped data to existing Spotify records
* [ ] Review interface for admins to validate scraped data
* [ ] Store scraper runs and log errors transparently
* [ ] Add cron-based scheduler for scraper refresh

### 🎯 Milestone 18: **"Alert Amplifier" Release** – Notifications & Emails

* [ ] Email verification for new accounts
* [ ] Notify users when round generation completes
* [x] Notify users of expiring OAuth tokens in the profile UI
* [ ] Send proactive email notifications for expiring OAuth tokens
* [ ] Optional weekly usage summary for admins
* [ ] Push notification support via browser or Telegram

### 🎯 Milestone 19: **"Rhythm Roundsmith" Release** – AI-Generated Quiz Rounds

* [ ] Develop AI module to generate full quiz rounds
  * [ ] Use existing song metadata (genre, year, tempo, artist)
  * [ ] Support different quiz formats: multiple-choice, guess-the-clip, open-ended
  * [x] Create quiz rounds from fully resolved text playlists
  * [x] Let users prompt AI with a theme or vibe (e.g., "Chill 80s", "Dancefloor Divas")
  * [x] Provide recent usage/fatigue context for agentic song selection
  * [x] Draft intro/replay/outro scripts for later TTS generation
  * [x] Store and review generated intro/replay/outro scripts before assigning TTS audio
  * [ ] Include fallback logic when metadata is sparse
* [ ] Let users review/edit AI-generated questions before saving
* [ ] Log prompt/response pairs for model improvement
* [ ] Add backend abstraction to swap AI providers (OpenAI, Mistral, etc.)
* [ ] Build tuning pipeline for prompt quality testing

### 🎯 Milestone 20: **"Storage Sanctuary" Release** – Multi-Provider Storage

* [ ] Implement cloud storage backend abstraction
* [ ] Add support for AWS S3 storage
  * [ ] Configure S3 credentials and bucket management
  * [ ] Support for optional encryption and lifecycle policies
* [ ] Add support for S3-compatible storage (MinIO, Wasabi, etc.)
* [ ] Integrate Dropbox as a storage backend
* [ ] Create unified storage management UI
* [ ] Export backups to cloud storage
* [ ] Store and retrieve music rounds from cloud storage
* [ ] Add background synchronization and status tracking
* [ ] Implement bandwidth-efficient differential uploads

### 🎯 Milestone 21: **"Collaboration Core" Release** – Multi-User Round Sharing

* [ ] Allow shared editing of rounds
* [x] Add persisted round ownership and explicit viewer/editor share grants
* [x] Add owner/visibility indicators and route-level edit checks for browser rounds
* [ ] Add collaboration roles beyond viewer/editor (comment, admin)
* [ ] Invite others to rounds via username/email UI
* [ ] Show who is currently editing (presence indicator)
* [ ] Track revision history and changes
* [ ] Allow public view-only sharing links with optional expiration
* [ ] Display access audit log (who opened/edited and when)

### 🎯 Milestone 22: **"Profile Personalizer" Release** – User Preferences & Tagging

* [x] User-specific intro/outro/replay MP3 fallback system
* [x] Persistent custom user settings
* [x] Expose quizmaster preference context to MCP agents
* [ ] Let users define default round format
* [ ] Implement personal tags for rounds (e.g., "pub night", "2020s", "pop")
* [ ] Add filtering and sorting by tag
* [ ] Dark mode toggle

### 🎯 Milestone 23: **"Performance Pulse" Release** – Scaling & Speed

* [ ] Index high-traffic database fields (tags, dates, users)
* [x] Paginate song and round browser lists server-side
* [x] Paginate song catalog API responses
* [x] Paginate and filter the browser song library server-side
* [ ] Lazy load MP3 previews and large content
* [ ] Add Redis/memory cache layer for read-heavy endpoints
* [ ] Load test with simulated users and large playlists

### 🎯 Milestone 24: **"Deployment Dynamo" Release** – CI/CD and Maintenance

* [x] GitHub Actions CI/CD pipeline for builds and tests
* [ ] Nightly backup job with status alert
* [ ] Add Sentry or similar for exception tracking
* [ ] Updater script for pulling latest Git commits safely
* [x] Add status endpoint (`/healthz`) for uptime monitors

---

## Other Features / Ideas in Progress

* [ ] "Blind Test" toggle per round (hide title/artist metadata)
* [ ] Team scoreboard (live projection mode)
* [ ] Public round library with clone/save features
* [ ] REST API for third-party integration (e.g., with trivia bots)
* [ ] Audio fingerprint validation for user-uploaded MP3s
* [ ] Round analytics: usage frequency, popularity, ratings
* [x] MCP catalog analytics summary for usage frequency and preview coverage
* [ ] Documentation enhancements:
  * [ ] Create video tutorials for complex workflows
  * [ ] Implement keyboard shortcuts in the application
  * [ ] Document keyboard shortcuts for power users when implemented

*Last updated: July 6, 2026*
