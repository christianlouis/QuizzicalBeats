# Installation Guide

This guide explains how to install and set up Quizzical Beats in various environments.

## System Requirements

Before installation, ensure your system meets these requirements:

- **Operating System**: Linux (recommended), macOS, or Windows
- **Python**: Version 3.8 or higher
- **Database**: SQLite (included), PostgreSQL, or MySQL
- **Storage**: Minimum 2GB free space for application and database
- **Memory**: 2GB RAM minimum, 4GB recommended
- **Optional**: Docker and Docker Compose for containerized deployment

## Docker Installation (Recommended)

The easiest way to deploy Quizzical Beats is using Docker:

### Prerequisites

1. Install [Docker](https://docs.docker.com/get-docker/)
2. Install [Docker Compose](https://docs.docker.com/compose/install/)

### Deployment Steps

1. Clone the repository:
   ```bash
   git clone https://github.com/christianlouis/musicround.git
   cd musicround
   ```

2. Configure environment variables:
   ```bash
   cp .env.demo .env
   ```
   Edit the `.env` file to set your configuration options, including API keys and database settings.

3. Start the application:
   ```bash
   docker-compose up -d
   ```

4. Access the application at `http://localhost:5000`

### Docker Volume Configuration

The Docker setup creates several persistent volumes:

- **data**: Contains the SQLite database and uploaded files
- **mp3**: Stores all generated and uploaded MP3 files
- **backups**: Location for automated backups

You can configure these volumes in the `docker-compose.yml` file:

```yaml
volumes:
  - ./data:/app/data
  - ./mp3:/app/mp3
  - ./backups:/app/backups
```

## Manual Installation

For non-Docker environments:

### Prerequisites

1. Install Python 3.8+ and pip
2. Set up a virtual environment (recommended):
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

### Installation Steps

1. Clone the repository:
   ```bash
   git clone https://github.com/christianlouis/musicround.git
   cd musicround
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Configure environment variables:
   ```bash
   cp .env.demo .env
   ```
   Edit the `.env` file with your configuration settings.

4. Create necessary directories:
   ```bash
   mkdir -p data/backups mp3
   ```

5. Initialize the database:
   ```bash
   python run_migration.py
   ```

6. Start the application:
   ```bash
   python run.py
   ```

7. Access the application at `http://localhost:5000`

## Production Deployment

For production environments, consider the following:

### Web Server Configuration

Use a production-ready web server:

1. Install Gunicorn:
   ```bash
   pip install gunicorn
   ```

2. Configure Gunicorn:
   ```bash
   gunicorn -w 4 -b 127.0.0.1:8000 "musicround:create_app()"
   ```

3. Set up Nginx as a reverse proxy:

   ```nginx
   server {
       listen 80;
       server_name your-domain.com;
       
       location / {
           proxy_pass http://127.0.0.1:8000;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
       }
       
       location /static {
           alias /path/to/musicround/static;
           expires 30d;
       }
   }
   ```

4. Set up HTTPS using Certbot (Let's Encrypt):
   ```bash
   sudo certbot --nginx -d your-domain.com
   ```

### Database Configuration

For larger deployments, use PostgreSQL:

1. Install PostgreSQL and create a database:
   ```bash
   sudo apt install postgresql
   sudo -u postgres createuser -P quizzicalbeats
   sudo -u postgres createdb -O quizzicalbeats musicround
   ```

2. Update the database URI in your `.env` file:
   ```
   SQLALCHEMY_DATABASE_URI=postgresql://quizzicalbeats:password@localhost/musicround
   ```

### Security Configuration

1. Generate a strong secret key:
   ```bash
   python -c "import secrets; print('SECRET_KEY=' + secrets.token_hex(32))"
   ```
   Add this to your `.env` file.

2. Set debug mode to False in production:
   ```
   DEBUG=False
   ```

3. Configure proper file permissions:
   ```bash
   sudo chown -R www-data:www-data data mp3 backups
   sudo chmod -R 750 data mp3 backups
   ```

## Setting Up Third-Party Services

### Spotify Integration

1. Go to the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard/)
2. Create a new application
3. Add `http://your-domain.com/auth/spotify/callback` to the Redirect URIs
4. Copy your Client ID and Client Secret to your `.env` file:
   ```
   SPOTIFY_CLIENT_ID=your-client-id
   SPOTIFY_CLIENT_SECRET=your-client-secret
   SPOTIFY_REDIRECT_URI=http://your-domain.com/auth/spotify/callback
   ```

### Dropbox Integration

1. Go to the [Dropbox App Console](https://www.dropbox.com/developers/apps)
2. Create a new app with the following settings:
   - API: Dropbox API
   - Access type: Full Dropbox
   - Name: Quizzical Beats (or your preferred name)
3. Add `http://your-domain.com/users/dropbox/callback` to the OAuth 2 Redirect URIs
4. Copy your App Key and App Secret to your `.env` file:
   ```
   DROPBOX_APP_KEY=your-app-key
   DROPBOX_APP_SECRET=your-app-secret
   DROPBOX_REDIRECT_URI=http://your-domain.com/users/dropbox/callback
   ```
5. Under Permissions, select:
   - files.content.read
   - files.content.write
   - sharing.write

### OpenAI Integration (for AI-powered features)

1. Go to [OpenAI API Keys](https://platform.openai.com/account/api-keys)
2. Create a new secret key
3. Add your API key to your `.env` file:
   ```
   OPENAI_API_KEY=your-api-key
   ```

### Email Configuration

1. Configure your SMTP settings in the `.env` file:
   ```
   MAIL_HOST=smtp.example.com
   MAIL_PORT=587
   MAIL_USE_TLS=True
   MAIL_USERNAME=your-username
   MAIL_PASSWORD=your-password
   MAIL_SENDER=quizzical-beats@example.com
   MAIL_RECIPIENT=admin@example.com
   ```

## Troubleshooting Installation Issues

### Database Migration Errors

If you encounter errors during database migration:

1. Check for database connection issues:
   ```bash
   python -c "from musicround import db; db.create_all()"
   ```

2. Reset the migration if needed:
   ```bash
   rm -f data/song_data.db
   python run_migration.py
   ```

### File Permission Issues

If you encounter file permission errors:

1. Check ownership of data directories:
   ```bash
   ls -la data mp3 backups
   ```

2. Update permissions if needed:
   ```bash
   sudo chown -R $(whoami) data mp3 backups
   ```

### OAuth Configuration Errors

If OAuth authentication fails:

1. Verify that your callback URLs exactly match what's configured in the provider's developer console
2. Check for typos in your client IDs and secrets
3. Ensure the application is in "production" status for Dropbox 
4. Verify that all required scopes/permissions are enabled

### Server Not Starting

If the server fails to start:

1. Check the logs for errors:
   ```bash
   tail -f logs/quizzical-beats.log
   ```

2. Verify that all required dependencies are installed:
   ```bash
   pip install -r requirements.txt
   ```

3. Check if another process is using port 5000:
   ```bash
   sudo lsof -i :5000
   ```