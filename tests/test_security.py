"""Security tests for Quizzical Beats."""
import pytest
import os
import re
import importlib
from unittest.mock import patch
import musicround.config


class TestSecurityConfiguration:
    """Test security configuration and settings."""
    
    def test_secret_key_required(self):
        """Test that SECRET_KEY must be set."""
        # Remove SECRET_KEY from environment
        secret_key = os.environ.get('SECRET_KEY')
        if secret_key:
            del os.environ['SECRET_KEY']
        
        try:
            # Force module reload to re-evaluate class-level checks
            with pytest.raises(ValueError, match="SECRET_KEY environment variable must be set"):
                importlib.reload(musicround.config)
        finally:
            # Restore environment
            if secret_key:
                os.environ['SECRET_KEY'] = secret_key
                # Reload with correct env so other tests work
                importlib.reload(musicround.config)
    
    def test_automation_token_required(self):
        """Test that AUTOMATION_TOKEN must be set."""
        # Remove AUTOMATION_TOKEN from environment
        token = os.environ.get('AUTOMATION_TOKEN')
        if token:
            del os.environ['AUTOMATION_TOKEN']
        
        try:
            # Force module reload to re-evaluate class-level checks
            with pytest.raises(ValueError, match="AUTOMATION_TOKEN environment variable must be set"):
                importlib.reload(musicround.config)
        finally:
            # Restore environment
            if token:
                os.environ['AUTOMATION_TOKEN'] = token
                # Reload with correct env so other tests work
                importlib.reload(musicround.config)
    
    def test_no_credentials_in_code(self):
        """Test that no credentials are hardcoded in Python files."""
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        musicround_dir = os.path.join(project_root, 'musicround')
        
        # Patterns that indicate potential credentials
        dangerous_patterns = [
            r'password\s*=\s*["\'][^"\']{8,}["\']',  # password = "something"
            r'token\s*=\s*["\'][A-Za-z0-9]{20,}["\']',  # token = "longstring"
            r'api[_-]?key\s*=\s*["\'][A-Za-z0-9]{20,}["\']',  # api_key = "key"
            r'secret\s*=\s*["\'][A-Za-z0-9]{20,}["\']',  # secret = "value"
        ]
        
        issues = []
        
        for root, dirs, files in os.walk(musicround_dir):
            # Skip __pycache__ and test files
            dirs[:] = [d for d in dirs if d != '__pycache__']
            
            for file in files:
                if not file.endswith('.py'):
                    continue
                
                filepath = os.path.join(root, file)
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    
                    for pattern in dangerous_patterns:
                        matches = re.finditer(pattern, content, re.IGNORECASE)
                        for match in matches:
                            # Exclude common test/example patterns
                            matched_text = match.group(0)
                            if any(safe in matched_text.lower() for safe in [
                                'test', 'example', 'placeholder', 'changeme', 
                                'your-', 'secret-key-here', 'getenvi'
                            ]):
                                continue
                            
                            issues.append({
                                'file': filepath,
                                'line': content[:match.start()].count('\n') + 1,
                                'match': matched_text
                            })
        
        if issues:
            message = "Found potential hardcoded credentials:\n"
            for issue in issues[:5]:  # Show first 5
                message += f"  {issue['file']}:{issue['line']}: {issue['match']}\n"
            pytest.fail(message)
    
    def test_env_example_exists(self):
        """Test that .env.example file exists."""
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        env_example = os.path.join(project_root, '.env.example')
        assert os.path.exists(env_example), ".env.example file should exist"
    
    def test_security_md_exists(self):
        """Test that SECURITY.md file exists."""
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        security_md = os.path.join(project_root, 'SECURITY.md')
        assert os.path.exists(security_md), "SECURITY.md file should exist"


class TestDependencySecurity:
    """Test dependency security."""
    
    def test_authlib_version(self):
        """Test that authlib is at least version 1.6.5."""
        requirements_path = os.path.join(
            os.path.dirname(__file__), '..', 'requirements.txt'
        )
        
        with open(requirements_path, 'r') as f:
            content = f.read()
        
        # Check for authlib with version constraint
        assert 'authlib>=1.6.5' in content, \
            "authlib should be pinned to >= 1.6.5 to fix known vulnerabilities"

    def test_pyjwt_version(self):
        """Test that PyJWT is at least version 2.10.1."""
        requirements_path = os.path.join(
            os.path.dirname(__file__), '..', 'requirements.txt'
        )

        with open(requirements_path, 'r') as f:
            content = f.read()

        assert 'PyJWT>=2.10.1' in content, \
            "PyJWT should be pinned to >= 2.10.1 to fix known vulnerabilities"

    def test_idna_version(self):
        """Test that idna is at least version 3.11."""
        requirements_path = os.path.join(
            os.path.dirname(__file__), '..', 'requirements.txt'
        )

        with open(requirements_path, 'r') as f:
            content = f.read()

        assert 'idna>=3.11' in content, \
            "idna should be pinned to >= 3.11 to fix known vulnerabilities"


class TestInputValidation:
    """Test that user input is properly validated."""
    
    def test_sql_injection_prevention(self):
        """Test that SQLAlchemy ORM is used (not raw SQL)."""
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        musicround_dir = os.path.join(project_root, 'musicround')
        
        # Look for dangerous SQL patterns
        dangerous_patterns = [
            r'\.execute\(["\'].*%s.*["\']',  # .execute("... %s ...")
            r'\.execute\(["\'].*\+.*["\']',  # .execute("... " + var)
            r'\.execute\(f["\']',  # .execute(f"...")
        ]
        
        issues = []
        
        for root, dirs, files in os.walk(musicround_dir):
            dirs[:] = [d for d in dirs if d != '__pycache__']
            
            for file in files:
                if not file.endswith('.py'):
                    continue
                
                filepath = os.path.join(root, file)
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    
                    for pattern in dangerous_patterns:
                        matches = re.finditer(pattern, content)
                        for match in matches:
                            issues.append({
                                'file': filepath,
                                'line': content[:match.start()].count('\n') + 1,
                                'match': match.group(0)
                            })
        
        # migrations are allowed to use raw SQL
        issues = [i for i in issues if '/migrations/' not in i['file']]
        
        if issues:
            message = "Found potential SQL injection risks:\n"
            for issue in issues[:5]:
                message += f"  {issue['file']}:{issue['line']}: {issue['match']}\n"
            pytest.fail(message)


class TestSecureDefaults:
    """Test that secure defaults are in place."""
    
    def test_debug_disabled_by_default(self):
        """Test that DEBUG is disabled by default in config."""
        # Check .env.example
        env_example_path = os.path.join(os.path.dirname(__file__), '..', '.env.example')
        with open(env_example_path, 'r') as f:
            content = f.read()
        
        # Should have DEBUG=False
        assert 'DEBUG=False' in content, ".env.example should have DEBUG=False"
        assert 'DEBUG2=False' in content, ".env.example should have DEBUG2=False"

    def test_config_debug_defaults_false(self, monkeypatch):
        """Test that debug config defaults are disabled without env overrides."""
        monkeypatch.setenv('SECRET_KEY', 'test-secret-key-for-security-test')
        monkeypatch.setenv('AUTOMATION_TOKEN', 'test-automation-token-for-security-test')
        monkeypatch.delenv('DEBUG', raising=False)
        monkeypatch.delenv('DEBUG2', raising=False)

        config_module = importlib.reload(musicround.config)

        assert config_module.Config.DEBUG is False
        assert config_module.Config.DEBUG2 is False

    def test_cookie_security_defaults(self, monkeypatch):
        """Test secure session and remember-cookie defaults."""
        monkeypatch.setenv('SECRET_KEY', 'test-secret-key-for-security-test')
        monkeypatch.setenv('AUTOMATION_TOKEN', 'test-automation-token-for-security-test')
        monkeypatch.setenv('USE_HTTPS', 'True')

        config_module = importlib.reload(musicround.config)

        assert config_module.Config.SESSION_COOKIE_SECURE is True
        assert config_module.Config.SESSION_COOKIE_HTTPONLY is True
        assert config_module.Config.SESSION_COOKIE_SAMESITE == 'Lax'
        assert config_module.Config.REMEMBER_COOKIE_SECURE is True
        assert config_module.Config.REMEMBER_COOKIE_HTTPONLY is True
        assert config_module.Config.REMEMBER_COOKIE_SAMESITE == 'Lax'
        assert config_module.Config.PERMANENT_SESSION_LIFETIME.total_seconds() == 12 * 3600

        monkeypatch.setenv('USE_HTTPS', 'False')
        importlib.reload(musicround.config)
    
    def test_https_recommended(self):
        """Test that HTTPS is documented as recommended."""
        security_md_path = os.path.join(os.path.dirname(__file__), '..', 'SECURITY.md')
        with open(security_md_path, 'r') as f:
            content = f.read()
        
        assert 'HTTPS' in content or 'https' in content, \
            "SECURITY.md should mention HTTPS"
        assert 'USE_HTTPS' in content, \
            "SECURITY.md should document USE_HTTPS setting"


class TestAuthRateLimiting:
    """Test authentication throttling."""

    def test_login_rate_limit_blocks_repeated_failures(self, app, client):
        """Test repeated bad logins are throttled."""
        from musicround.routes import users as users_routes

        users_routes._LOGIN_FAILURES.clear()
        app.config['LOGIN_RATE_LIMIT_ATTEMPTS'] = 2
        app.config['LOGIN_RATE_LIMIT_WINDOW_SECONDS'] = 900

        payload = {'username': 'rate-limit-user', 'password': 'wrong-password'}
        first = client.post('/users/login', data=payload)
        second = client.post('/users/login', data=payload)
        third = client.post('/users/login', data=payload)

        assert first.status_code == 200
        assert second.status_code == 200
        assert third.status_code == 429

    def test_create_backup_accepts_header_automation_token(self, app, client):
        """Test backup automation uses header-only token auth without login."""
        app.config['AUTOMATION_TOKEN'] = 'automation-secret'

        with patch('musicround.helpers.backup_helper.create_backup') as mock_create:
            mock_create.return_value = {'status': 'success', 'message': 'created'}
            response = client.post(
                '/users/create-backup',
                headers={'X-Automation-Token': 'automation-secret'},
            )

        assert response.status_code == 200
        assert response.get_json()['status'] == 'success'
        mock_create.assert_called_once()

    def test_create_backup_rejects_query_string_token(self, app, client):
        """Test automation tokens are not accepted in URLs."""
        app.config['AUTOMATION_TOKEN'] = 'automation-secret'

        with patch('musicround.helpers.backup_helper.create_backup') as mock_create:
            response = client.post(
                '/users/create-backup?token=automation-secret',
                headers={'Accept': 'application/json'},
            )

        assert response.status_code == 401
        mock_create.assert_not_called()

    def test_create_backup_rate_limits_bad_automation_tokens(self, app, client):
        """Test repeated invalid automation headers are throttled."""
        from musicround.routes import users as users_routes

        users_routes._AUTOMATION_FAILURES.clear()
        app.config['AUTOMATION_TOKEN'] = 'automation-secret'
        app.config['AUTOMATION_RATE_LIMIT_ATTEMPTS'] = 1
        app.config['AUTOMATION_RATE_LIMIT_WINDOW_SECONDS'] = 300

        first = client.post(
            '/users/create-backup',
            headers={'X-Automation-Token': 'wrong-token'},
        )
        second = client.post(
            '/users/create-backup',
            headers={'X-Automation-Token': 'wrong-token'},
        )

        assert first.status_code == 401
        assert second.status_code == 429


class TestSecretManagement:
    """Test secret management practices."""
    
    def test_gitignore_includes_env(self):
        """Test that .env is in .gitignore."""
        gitignore_path = os.path.join(os.path.dirname(__file__), '..', '.gitignore')
        with open(gitignore_path, 'r') as f:
            content = f.read()
        
        assert '.env' in content, ".env should be in .gitignore"
    
    def test_no_env_files_committed(self):
        """Test that actual .env files are not in git."""
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        
        # .env.example is OK, but .env should not exist in repo
        # (it will exist locally but should be gitignored)
        # We're checking if demo files have placeholder values
        
        demo_files = ['.env.demo', '.env.oauth', '.env.oauth.production']
        for demo_file in demo_files:
            demo_path = os.path.join(project_root, demo_file)
            if os.path.exists(demo_path):
                with open(demo_path, 'r') as f:
                    content = f.read()
                
                # Check that these don't contain real-looking credentials
                # Real API keys are usually 32+ characters of alphanumeric
                patterns = [
                    r'[A-Za-z0-9]{40,}',  # Very long alphanumeric strings
                ]
                
                for pattern in patterns:
                    matches = re.findall(pattern, content)
                    for match in matches:
                        # Skip if it's obviously a placeholder
                        if any(x in match.lower() for x in [
                            'your-', 'example', 'changeme', 'placeholder'
                        ]):
                            continue
                        
                        # This might be a real credential
                        if len(match) > 40:
                            pytest.fail(
                                f"Found potential real credential in {demo_file}: "
                                f"{match[:20]}... (redacted)"
                            )
