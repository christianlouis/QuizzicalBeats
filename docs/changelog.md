# Changelog

This document tracks all notable changes made to Quizzical Beats across different versions.

## v1.0.0 - May 10, 2025

### Milestone 9: "Documentation Dynamo"
- Added comprehensive documentation system with MkDocs
- Created user guides with detailed instructions
- Added developer documentation with architecture overview
- Implemented administrator documentation
- Added FAQ section covering common questions
- Created installation and configuration guides
- Added OAuth integration documentation

## v0.9.0 - April 15, 2025

### Milestone 8: "Dropbox Dispatch"
- Added Dropbox OAuth integration for user accounts
- Implemented round export directly to Dropbox
- Added user interface for Dropbox account management
- Created export logs and status tracking
- Added fallback handling for Dropbox token expiration
- Implemented automatic token refresh for Dropbox API

## v0.8.0 - March 2, 2025

### Milestone 7: "Bulletproof Backups"
- Implemented comprehensive backup system
- Added backup scheduling with Ofelia integration
- Created backup verification and integrity checks
- Added restore functionality for system recovery
- Implemented backup retention policies
- Added system health dashboard
- Created command-line backup tools

## v0.7.0 - February 10, 2025

### Milestone 6: "Advanced Features & Optimizations"
- Implemented comprehensive logging system
- Added system monitoring dashboard
- Optimized database queries for better performance
- Improved error handling and user feedback
- Enhanced security with improved authentication flows

## v0.6.0 - January 25, 2025

### Milestone 5: "Additional OAuth Providers"
- Added Google OAuth integration
- Implemented Authentik OAuth support
- Created unified authentication experience
- Added profile linking between OAuth accounts
- Enhanced security for third-party authentication

## v0.5.0 - January 8, 2025

### Milestone 4: "Enhanced User Experience"
- Added support for user-specific intro/outro/replay MP3s
- Updated email system to use logged-in user's email
- Implemented user preferences and settings system
- Improved UI/UX for round creation and management
- Added customizable export settings

## v0.4.0 - December 15, 2024

### Milestone 3: "Spotify Integration with User Accounts"
- Migrated Spotify token storage to user-specific model
- Added Spotify OAuth login option
- Created fallback mechanism for service account
- Linked user playlists with their Spotify accounts
- Enhanced Spotify data synchronization

## v0.3.0 - December 1, 2024

### Milestone 2: "Authentication Foundation"
- Designed and implemented database schema for users and roles
- Created basic authentication system with local username/password
- Implemented user management interfaces
- Added admin role functionality
- Enhanced security with proper password handling and session management

## v0.2.0 - November 15, 2024

### Milestone 1: "Spotify Integration Fix"
- Fixed Spotify playlist import functionality
- Implemented proper pagination for playlist retrieval
- Added better error handling for API rate limits
- Refactored Spotify client code for maintainability
- Enhanced logging for API requests and responses

## v0.1.0 - November 1, 2024

### Initial Release
- Basic Flask application structure
- Simple round creation functionality
- Manual song entry capabilities
- Basic export functionality
- Minimal UI with core features