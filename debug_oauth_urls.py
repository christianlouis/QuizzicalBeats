#!/usr/bin/env python3
"""
This script helps debug OAuth URL generation when behind a reverse proxy.
It's especially useful for debugging HTTPS redirection issues.

Usage:
    python debug_oauth_urls.py [--https] [--host hostname] [--port portnumber]

Options:
    --https     Force HTTPS URL generation regardless of request headers
    --host      Set the hostname (default: localhost)
    --port      Set the port number (default: 5000)
"""

import sys
import os
import argparse
from flask import Flask, request, jsonify
from dotenv import load_dotenv

# Make sure we can import from the musicround package
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Parse command line arguments
parser = argparse.ArgumentParser(description="Debug OAuth URL generation")
parser.add_argument("--https", action="store_true", 
                    help="Force HTTPS URL generation")
parser.add_argument("--host", default="localhost",
                    help="Set the hostname (default: localhost)")
parser.add_argument("--port", type=int, default=5000,
                    help="Set the port number (default: 5000)")
args = parser.parse_args()

# Load environment variables
load_dotenv()

# If .env.oauth exists, load it too (it has OAuth specific settings)
if os.path.exists(".env.oauth"):
    load_dotenv(".env.oauth")

# If .env.oauth.production exists and --https is specified, load that instead
if args.https and os.path.exists(".env.oauth.production"):
    load_dotenv(".env.oauth.production", override=True)
    print("Loading production OAuth settings from .env.oauth.production")

# Create a small Flask app just for debugging
app = Flask(__name__)

# Override config with command line args
app.config["USE_HTTPS"] = args.https
app.config["PREFERRED_URL_SCHEME"] = "https" if args.https else "http"

@app.route("/")
def debug_oauth():
    """Generate debug information for OAuth URLs"""
    from musicround.helpers.auth_helpers import get_oauth_redirect_uri
    
    # Generate endpoints to test
    endpoints = [
        ("auth.callback", None),
        ("users.spotify_link_callback", None),
        ("users.google_callback", None),
        ("users.authentik_callback", None),
        ("users.dropbox_callback", None)
    ]
    
    # Generate test URLs
    test_urls = {}
    for endpoint, provider in endpoints:
        try:
            # We need to be in an app context to use url_for
            with app.app_context():
                # Allow KeyErrors to propagate so we know which endpoints don't exist
                url = get_oauth_redirect_uri(endpoint, provider)
                test_urls[endpoint] = url
        except Exception as e:
            test_urls[endpoint] = f"ERROR: {str(e)}"
    
    # Get request info
    headers = {
        key: value for key, value in request.headers.items()
        if key.lower() in ('x-forwarded-for', 'x-forwarded-proto', 
                          'x-forwarded-host', 'host', 'origin', 'referer')
    }
    
    # Return detailed info
    return jsonify({
        "test_urls": test_urls,
        "config": {
            "USE_HTTPS": app.config.get("USE_HTTPS", False),
            "PREFERRED_URL_SCHEME": app.config.get("PREFERRED_URL_SCHEME", "http"),
            "STATIC_OAUTH_URLS": app.config.get("STATIC_OAUTH_URLS", False),
            "args": {
                "https": args.https,
                "host": args.host,
                "port": args.port
            },
        },
        "headers": headers,
        "request_info": {
            "url": request.url,
            "base_url": request.base_url,
            "host": request.host,
            "scheme": request.scheme,
        }
    })

if __name__ == "__main__":
    print(f"Starting OAuth URL Debug server on http://{args.host}:{args.port}")
    print(f"USE_HTTPS is set to: {app.config['USE_HTTPS']}")
    print(f"PREFERRED_URL_SCHEME is set to: {app.config['PREFERRED_URL_SCHEME']}")
    print(f"Visit http://{args.host}:{args.port}/ to see debug information")
    
    app.run(host=args.host, port=args.port, debug=True)
