# Contributing to Quizzical Beats

This guide provides information for developers who want to contribute to the Quizzical Beats project.

## Getting Started

### Development Environment Setup

1. Fork the repository on GitHub
2. Clone your fork locally:
   ```bash
   git clone https://github.com/YOUR-USERNAME/musicround.git
   cd musicround
   ```

3. Set up a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

4. Install development dependencies:
   ```bash
   pip install -r requirements-dev.txt
   ```

5. Set up pre-commit hooks:
   ```bash
   pre-commit install
   ```

6. Configure your environment variables for development:
   ```bash
   cp .env.example .env.dev
   # Edit .env.dev with your development settings
   ```

## Development Workflow

### Branching Strategy

We use a simplified Git flow approach:

- `main`: Production-ready code
- `develop`: Main development branch
- Feature branches: Created from `develop` for new features
- Bugfix branches: Created from `develop` for bug fixes
- Hotfix branches: Created from `main` for critical fixes

Naming conventions:
- Feature branches: `feature/short-description`
- Bug fix branches: `bugfix/issue-number-description`
- Hotfix branches: `hotfix/issue-number-description`

### Making Changes

1. Create a new branch from `develop`:
   ```bash
   git checkout develop
   git pull origin develop
   git checkout -b feature/your-feature-name
   ```

2. Make your changes, following the coding standards

3. Run tests to ensure your changes don't break existing functionality:
   ```bash
   pytest
   ```

4. Commit your changes with a descriptive message:
   ```bash
   git commit -am "Add feature: short description

   More detailed explanation of the changes if needed.
   Fixes #123"
   ```

5. Push your branch to your fork:
   ```bash
   git push origin feature/your-feature-name
   ```

6. Create a pull request from your branch to the `develop` branch of the main repository

## Coding Standards

### Python Style Guide

We follow PEP 8 with some modifications:

- Line length: 100 characters maximum
- Use 4 spaces for indentation (no tabs)
- Use docstrings for all classes and functions
- Follow Google's Python Style Guide for docstrings

### Flask-Specific Guidelines

- Organize routes by functionality in blueprints
- Keep view functions small and focused
- Use decorators for common patterns
- Prefer class-based views for complex endpoints

### Testing Guidelines

- Write tests for all new features
- Maintain or improve test coverage
- Structure tests in a similar way to the code they test
- Use fixtures for common setup
- Mock external services in tests

## Pull Request Process

1. Ensure your code passes all tests and linting checks
2. Update documentation if your changes affect it
3. Add your changes to the CHANGELOG.md under "Unreleased"
4. Request a review from at least one maintainer
5. Address any feedback from the reviewer
6. Once approved, a maintainer will merge your PR

## Database Migrations

When making changes to the database schema:

1. Create a new migration script in the `migrations/` directory
2. Name it descriptively (e.g., `add_user_preferences.py`)
3. Implement both upgrade and downgrade paths
4. Test the migration in both directions
5. Document the changes in the database schema documentation

Example migration script:

```python
# migrations/add_user_preferences.py

def upgrade(db):
    db.execute("""
    ALTER TABLE user 
    ADD COLUMN preferences JSON NULL
    """)

def downgrade(db):
    db.execute("""
    ALTER TABLE user
    DROP COLUMN preferences
    """)
```

## Documentation Guidelines

When contributing to the documentation:

1. Use Markdown for all documentation files
2. Keep language clear and concise
3. Include code examples where appropriate
4. Follow the existing documentation structure
5. Update the documentation when implementing new features

## Release Process

Our release process follows these steps:

1. Features and bugfixes are merged into `develop`
2. When ready for release, we:
   - Create a release branch `release/X.Y.Z`
   - Update version number in `version.py`
   - Finalize CHANGELOG.md
   - Run final tests
3. The release branch is merged into `main`
4. A tag is created for the release
5. `main` is merged back into `develop`

## Getting Help

If you need help or have questions:

- Check the existing documentation
- Look at similar features or patterns in the codebase
- Reach out on the project issues page
- Contact the maintainers directly

## Code of Conduct

Please note that this project is released with a Contributor Code of Conduct. By participating in this project you agree to abide by its terms.

### Our Standards

- Be respectful and inclusive
- Accept constructive criticism gracefully
- Focus on what's best for the community
- Show empathy towards other community members

## License

By contributing to Quizzical Beats, you agree that your contributions will be licensed under the project's MIT License.