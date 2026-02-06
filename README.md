# Quizzical Beats

<p align="center">
  <img src="docs/static/img/logo.png" alt="Quizzical Beats Logo" width="350">
</p>

<p align="center">
  <a href="https://quizzicalbeats.readthedocs.io/"><strong>📚 Documentation</strong></a> •
  <a href="#features">Features</a> •
  <a href="#getting-started">Getting Started</a> •
  <a href="#deployment">Deployment</a> •
  <a href="#license">License</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/security-hardened-green" alt="Security Hardened">
  <img src="https://img.shields.io/badge/code%20quality-A-brightgreen" alt="Code Quality">
  <img src="https://img.shields.io/badge/python-3.11+-blue" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT License">
</p>

**Quizzical Beats** (formerly MusicRound) is a Flask-based web application for building engaging music quiz rounds for pub quizzes. Leveraging the Spotify and Deezer APIs, it allows you to generate rounds based on the least-used genres, decades, or completely random criteria, making your quizzes dynamic and entertaining.

---

## Features

- **Multi-Service Music Integration**:
  - **Spotify Integration**: Import songs and playlists directly from Spotify using their API.
  - **Deezer Integration**: Alternative source for songs and playlists.
  - **Last.fm Integration**: Automatically enrich tracks with genre metadata.

- **Dynamic Round Creation**:
  - Randomly generated rounds.
  - Based on least-used genres or decades.
  - Tag-based rounds for custom categorization.
  - Unique and diverse song selections.

- **Powerful Export Options**:
  - Export rounds as printable **PDFs** with questions and answers.
  - Create playable **MP3s** with song snippets.
  - Generate **ZIP** packages with all round contents.
  - **Dropbox Integration** for cloud storage of rounds.

- **User Management**:
  - Multiple authentication methods (local, Spotify, Google, Authentik).
  - User-specific settings and preferences.
  - Role-based access control.

- **System Administration**:
  - Comprehensive backup and restore functionality.
  - System health monitoring dashboard.
  - User and content management tools.

---

## Getting Started

### Prerequisites

- **Python**: Version 3.9 or higher.
- **Spotify Developer Account**: [Create a Spotify Developer App](https://developer.spotify.com/dashboard/applications) to retrieve your client ID and secret.
- **Last.fm API Key**: Sign up at [Last.fm](https://www.last.fm/api) to obtain an API key.
- **Dropbox Developer Account** (optional): [Create a Dropbox App](https://www.dropbox.com/developers/apps) for export functionality.
- **Deezer Developer Account** (optional): [Create a Deezer App](https://developers.deezer.com/myapps) for additional music sources.

### Installation

#### Docker Installation (Recommended)

1. Clone the repository:
   ```bash
   git clone https://github.com/christianlouis/QuizzicalBeats.git
   cd QuizzicalBeats
   ```

2. Configure environment variables in a `.env` file (copy from `.env.example`):
   ```env
   SPOTIFY_CLIENT_ID=your_spotify_client_id
   SPOTIFY_CLIENT_SECRET=your_spotify_client_secret
   SPOTIFY_REDIRECT_URI=http://localhost:5000/auth/spotify/callback
   LASTFM_API_KEY=your_lastfm_api_key
   # Add other configuration options as needed
   ```

3. Start the Docker containers:
   ```bash
   docker-compose up -d
   ```

4. Access the application at `http://localhost:5000`.

#### Manual Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/christianlouis/QuizzicalBeats.git
   cd QuizzicalBeats
   ```

2. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Set up environment variables in a `.env` file (copy from `.env.example`).

5. Initialize the database:
   ```bash
   python run_migration.py
   ```

6. Start the application:
   ```bash
   python run.py
   ```

7. Access the application at `http://localhost:5000`.

---

## Deployment

For production deployment, we recommend using Docker with proper security configurations. See our [Installation Guide](https://quizzicalbeats.readthedocs.io/admin-guide/installation.html) in the documentation for detailed deployment instructions.

### Security Considerations

- Always use HTTPS in production
- Set up proper authentication methods
- Use strong, unique secrets and passwords
- Configure backups regularly

---

## Documentation

Comprehensive documentation is available at [quizzicalbeats.readthedocs.io](https://quizzicalbeats.readthedocs.io/), including:

- [User Guide](https://quizzicalbeats.readthedocs.io/user-guide/getting-started.html)
- [Admin Guide](https://quizzicalbeats.readthedocs.io/admin-guide/installation.html)
- [Developer Guide](https://quizzicalbeats.readthedocs.io/developer-guide/architecture.html)
- [API Reference](https://quizzicalbeats.readthedocs.io/developer-guide/api-reference.html)
- [FAQ](https://quizzicalbeats.readthedocs.io/faq.html)

### Additional Documentation

- [SECURITY.md](SECURITY.md) - Security policy, best practices, and vulnerability reporting
- [ROADMAP.md](ROADMAP.md) - Project roadmap, milestones, and future plans
- [AGENTS.md](AGENTS.md) - Guidelines for AI coding agents and developers
- [CONTRIBUTING.md](CONTRIBUTING.md) - Contribution guidelines
- [TODO.md](TODO.md) - Detailed task list and completed milestones

---

## Project Structure

The project follows a modular Flask application structure:

```
musicround/              # Main application package
├── __init__.py          # Application factory
├── config.py            # Configuration management
├── models.py            # Database models
├── version.py           # Version information
├── helpers/             # Utility modules
├── mp3/                 # Audio file storage
├── routes/              # Route blueprints
├── static/              # Static assets
└── templates/           # HTML templates
```

---

## License

This project is licensed under the **MIT License**. See `LICENSE` for details.

---

## Contributing

We welcome contributions! Please see our [Contributing Guide](https://quizzicalbeats.readthedocs.io/developer-guide/contributing.html) for details on how to get started.

---

## Contact

- **Developer**: Christian Krakau-Louis
- **Email**: [christian@kaufdeinquiz.com](mailto:christian@kaufdeinquiz.com)
- **GitHub**: [christianlouis](https://github.com/christianlouis)

---

<p align="center">
  <em>Where trivia meets the rhythm.</em>
</p>
