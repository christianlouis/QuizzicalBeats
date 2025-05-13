"""
Version information for the Quizzical Beats application.
This module provides version details that can be displayed in both CLI and UI.
"""

# Version information
VERSION_INFO = {
    "version": "1.9.0",
    "release_name": "Documentation Dynamo",
    "release_date": "2025-05-12",
    "build_number": "20250512001"
}

def get_version_str(include_build=False):
    """
    Return a formatted version string.
    
    Args:
        include_build: Whether to include the build number
        
    Returns:
        str: Formatted version string
    """
    if include_build:
        return f"v{VERSION_INFO['version']} ({VERSION_INFO['release_name']}) - Build {VERSION_INFO['build_number']}"
    else:
        return f"v{VERSION_INFO['version']} ({VERSION_INFO['release_name']})"