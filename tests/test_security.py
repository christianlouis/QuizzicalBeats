"""Security tests for Quizzical Beats."""
import pytest
import os
import re


class TestSecurityConfiguration:
    """Test security configuration and settings."""
    
    def test_secret_key_required(self):
        """Test that SECRET_KEY must be set."""
        # Remove SECRET_KEY from environment
        secret_key = os.environ.get('SECRET_KEY')
        if secret_key:
            del os.environ['SECRET_KEY']
        
        # Import should fail if SECRET_KEY not set
        with pytest.raises(ValueError, match="SECRET_KEY environment variable must be set"):
            from musicround.config import Config
            _ = Config.SECRET_KEY
        
        # Restore environment
        if secret_key:
            os.environ['SECRET_KEY'] = secret_key
    
    def test_automation_token_required(self):
        """Test that AUTOMATION_TOKEN must be set."""
        # Remove AUTOMATION_TOKEN from environment
        token = os.environ.get('AUTOMATION_TOKEN')
        if token:
            del os.environ['AUTOMATION_TOKEN']
        
        # Import should fail if AUTOMATION_TOKEN not set
        with pytest.raises(ValueError, match="AUTOMATION_TOKEN environment variable must be set"):
            from musicround.config import Config
            _ = Config.AUTOMATION_TOKEN
        
        # Restore environment
        if token:
            os.environ['AUTOMATION_TOKEN'] = token
    
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
    
    def test_https_recommended(self):
        """Test that HTTPS is documented as recommended."""
        security_md_path = os.path.join(os.path.dirname(__file__), '..', 'SECURITY.md')
        with open(security_md_path, 'r') as f:
            content = f.read()
        
        assert 'HTTPS' in content or 'https' in content, \
            "SECURITY.md should mention HTTPS"
        assert 'USE_HTTPS' in content, \
            "SECURITY.md should document USE_HTTPS setting"


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
