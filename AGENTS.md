# AI Agent Instructions for Quizzical Beats

This document provides guidelines for AI coding agents working on the Quizzical Beats repository.

## Project Overview

**Quizzical Beats** is a Flask-based web application for creating music quiz rounds for pub quizzes. It integrates with multiple music APIs (Spotify, Deezer, Last.fm) and provides PDF/MP3 export capabilities.

## Technology Stack

- **Backend**: Python 3.11+, Flask 3.x
- **Database**: SQLAlchemy ORM (SQLite dev, PostgreSQL/MySQL production)
- **Frontend**: Jinja2 templates, vanilla JavaScript
- **APIs**: Spotify, Deezer, Last.fm, OpenAI, Dropbox
- **Authentication**: Flask-Login, Authlib (OAuth)
- **Deployment**: Docker, Docker Compose

## Repository Structure

```
musicround/              # Main application package
├── __init__.py          # Application factory
├── config.py            # Configuration management
├── models.py            # Database models (SQLAlchemy)
├── helpers/             # Utility modules
├── routes/              # Flask blueprints (auth, api, core, generate, etc.)
├── static/              # CSS, JavaScript, images
└── templates/           # Jinja2 HTML templates

tests/                   # Test suite
docs/                    # MkDocs documentation
migrations/              # Database migration scripts
```

## Code Style Guidelines

### Python Style
- Follow **PEP 8** with maximum line length of **100 characters**
- Use **4 spaces** for indentation (no tabs)
- Provide docstrings for all functions and classes (Google style)
- Use type hints where beneficial

```python
def process_playlist(playlist_id: str, user_id: int) -> dict:
    """Process a Spotify playlist and import songs.
    
    Args:
        playlist_id: The Spotify playlist ID
        user_id: The user's database ID
        
    Returns:
        Dictionary containing import results with keys:
            - success: Boolean indicating success
            - songs_imported: Number of songs imported
            - errors: List of error messages (if any)
    """
    pass
```

### Flask Best Practices
- Organize routes using blueprints
- Prefer class-based views for complex endpoints
- Use Flask-WTF for form handling
- Always validate and sanitize user inputs
- Use SQLAlchemy ORM (never raw SQL without parameterization)

### Security Requirements
- **NEVER** commit API keys, secrets, or passwords
- **ALWAYS** use environment variables for sensitive data
- Validate all user inputs
- Use parameterized queries (SQLAlchemy ORM does this)
- Escape all template outputs (Jinja2 auto-escaping)
- Check [SECURITY.md](SECURITY.md) before making security-related changes

## Development Workflow

### Before Making Changes

1. **Understand the codebase**:
   - Read related code in `musicround/routes/` and `musicround/helpers/`
   - Check existing tests in `tests/`
   - Review documentation in `docs/`

2. **Check existing issues and roadmap**:
   - Review [TODO.md](TODO.md) for planned features
   - Check [ROADMAP.md](ROADMAP.md) for strategic direction
   - Search GitHub issues for related discussions

3. **Set up development environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

### Making Changes

1. **Create minimal, focused changes**:
   - Make the smallest change that solves the problem
   - Don't refactor unrelated code
   - Don't fix unrelated bugs or style issues

2. **Write tests**:
   - Add tests for new functionality in `tests/`
   - Update existing tests if behavior changes
   - Run tests: `pytest tests/ -v`

3. **Update documentation**:
   - Update docstrings for modified functions
   - Update `docs/` if user-facing changes
   - Update `README.md` if installation/setup changes

### Testing

```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_metadata.py -v

# Run with coverage
pytest --cov=musicround tests/
```

### Linting and Code Quality

```bash
# Format code (if black is installed)
black musicround/ --line-length 100

# Check code style
flake8 musicround/ --max-line-length=100

# Type checking (if mypy is installed)
mypy musicround/
```

## Common Tasks

### Adding a New Route

```python
# In musicround/routes/new_feature.py
from flask import Blueprint, render_template, request
from flask_login import login_required, current_user

new_feature_bp = Blueprint('new_feature', __name__)

@new_feature_bp.route('/new-feature')
@login_required
def index():
    """Display the new feature page."""
    return render_template('new_feature/index.html')
```

Then register in `musicround/__init__.py`:
```python
from musicround.routes.new_feature import new_feature_bp
app.register_blueprint(new_feature_bp)
```

### Adding a Database Model

```python
# In musicround/models.py
class NewModel(db.Model):
    """Description of what this model represents."""
    
    __tablename__ = 'new_model'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<NewModel {self.name}>'
```

Then create a migration:
```bash
flask db migrate -m "Add NewModel"
flask db upgrade
```

### Adding a Configuration Variable

```python
# In musicround/config.py
class Config:
    NEW_SETTING = os.getenv("NEW_SETTING", "default_value")
```

Add to `.env.example`:
```env
# Description of what this does
NEW_SETTING=default_value
```

## Database Migrations

- Migration files are in `migrations/`
- Use `run_migration.py` to run migrations
- Always test migrations on a backup database first
- Document schema changes in migration message

```bash
# Create a new migration
python run_migration.py

# Or manually
flask db migrate -m "Description of change"
flask db upgrade
```

## API Integration Guidelines

### Spotify API
- Token management in `musicround/helpers/spotify_helper.py`
- Use existing client manager: `SpotifyClientManager`
- Handle rate limits gracefully (retry with backoff)
- Always refresh expired tokens

### OAuth Integration
- OAuth routes in `musicround/routes/auth.py`
- Store tokens encrypted in database (User model)
- Implement token refresh before expiration
- Follow existing patterns for new OAuth providers

## Error Handling

```python
# Use Flask error handlers
from musicround.errors import APIError

@app.errorhandler(APIError)
def handle_api_error(error):
    return render_template('error.html', error=error), error.status_code

# In your code
if not valid:
    raise APIError("Invalid input", status_code=400)
```

## Logging

```python
import logging

logger = logging.getLogger(__name__)

# Use appropriate log levels
logger.debug("Detailed debugging information")
logger.info("Informational messages")
logger.warning("Warning messages")
logger.error("Error messages")
logger.critical("Critical errors")
```

## Commit Messages

Follow conventional commit format:

```
<type>(<scope>): <subject>

<body>

<footer>
```

Types:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting)
- `refactor`: Code refactoring
- `test`: Adding or updating tests
- `chore`: Maintenance tasks
- `security`: Security fixes

Examples:
```
feat(import): Add support for Deezer playlist import

Implemented Deezer API client and playlist parsing.
Supports public and user playlists.

Fixes #123

---

fix(auth): Refresh Spotify tokens before expiration

Previously tokens would expire during long operations.
Now checks expiration 5 minutes in advance.

---

security: Upgrade authlib to 1.6.5

Fixes CVE-2024-XXXXX (JWT validation bypass)
```

## Pull Request Guidelines

1. Fill out the PR template completely
2. Reference related issues with `Fixes #123` or `Relates to #456`
3. Include before/after screenshots for UI changes
4. List any database migrations required
5. Note any breaking changes
6. Ensure all tests pass
7. Check security implications

## Testing Strategy

### What to Test
- Business logic in helpers and models
- API integration error handling
- Authentication and authorization
- Database operations
- Input validation

### What Not to Test
- Third-party library internals
- Database engine specifics
- Flask framework itself

### Test Structure
```python
# tests/test_feature.py
import pytest
from musicround import create_app, db
from musicround.models import User

@pytest.fixture
def app():
    """Create application for testing."""
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()

def test_feature(app):
    """Test description."""
    # Arrange
    user = User(username='test', email='test@example.com')
    
    # Act
    result = some_function(user)
    
    # Assert
    assert result == expected_value
```

## Documentation

- User documentation in `docs/user-guide/`
- Admin documentation in `docs/admin-guide/`
- Developer documentation in `docs/developer-guide/`
- API documentation in `docs/developer-guide/api-reference.md`
- Use MkDocs markdown format

## Common Pitfalls to Avoid

1. **Don't use default SECRET_KEY**: Must be set via environment variable
2. **Don't commit .env files**: Use .env.example as template
3. **Don't store credentials in code**: Use environment variables
4. **Don't make breaking changes without migration path**: Document upgrade steps
5. **Don't skip input validation**: All user input is untrusted
6. **Don't use raw SQL**: Use SQLAlchemy ORM for safety
7. **Don't forget CSRF protection**: Use Flask-WTF forms
8. **Don't expose sensitive data in logs**: Sanitize before logging

## Useful Commands

```bash
# Development server
python run.py

# Run migrations
python run_migration.py

# Run tests
pytest tests/ -v

# Check dependencies for vulnerabilities
pip install safety
safety check

# Docker commands
docker-compose up -d
docker-compose logs -f
docker-compose down

# Database backup
# (Use built-in backup functionality in web UI or /backup endpoint)
```

## Getting Help

- Check [documentation](https://quizzicalbeats.readthedocs.io/)
- Review [FAQ](https://quizzicalbeats.readthedocs.io/faq.html)
- Search [GitHub issues](https://github.com/christianlouis/QuizzicalBeats/issues)
- Read [CONTRIBUTING.md](CONTRIBUTING.md)
- Contact: christian@kaufdeinquiz.com

## References

- [Flask Documentation](https://flask.palletsprojects.com/)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)
- [Spotify Web API](https://developer.spotify.com/documentation/web-api/)
- [PEP 8 Style Guide](https://peps.python.org/pep-0008/)
- [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html)

---

*Last updated: February 2026*

