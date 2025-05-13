# OAuth Integration Callback URLs

This document provides information about the OAuth callback URLs used in Quizzical Beats for various authentication providers.

## Overview

When configuring OAuth providers (Google, Authentik, Spotify, Dropbox), you need to set up redirect/callback URLs in each provider's developer console. These URLs tell the provider where to send users after they authenticate.

## Callback URLs by Provider

### Google OAuth

**Callback URL:** `https://your-domain.com/users/login/google/callback`  
**Local Development:** `http://localhost:5000/users/login/google/callback`

When configuring Google OAuth in the Google Cloud Console:
1. Go to "APIs & Services" > "Credentials"
2. Create or edit an OAuth 2.0 Client ID
3. Add the above URLs to the "Authorized redirect URIs" section

### Authentik OAuth

**Callback URL:** `https://your-domain.com/users/login/authentik/callback`  
**Local Development:** `http://localhost:5000/users/login/authentik/callback`

When configuring Authentik:
1. Create an OAuth2/OIDC Provider
2. Add the above URLs to the "Redirect URIs" field
3. Ensure the scopes include "openid", "profile", and "email"

### Spotify API

**Callback URL:** `https://your-domain.com/users/spotify-callback`  
**Local Development:** `http://localhost:5000/users/spotify-callback`

When configuring Spotify in the Spotify Developer Dashboard:
1. Go to your app's settings
2. Add the above URLs to the "Redirect URIs" section
3. Save the changes

### Dropbox API

**Callback URL:** `https://your-domain.com/users/dropbox-callback`  
**Local Development:** `http://localhost:5000/users/dropbox-callback`

When configuring Dropbox in the Dropbox Developer Console:
1. Go to your app's settings in the [Dropbox App Console](https://www.dropbox.com/developers/apps)
2. Under "OAuth 2", add the above URLs to the "Redirect URIs" section
3. Make sure you've selected the correct permission scopes:
   - `files.content.read`
   - `files.content.write`
   - `sharing.write`
   - `offline_access` (for refresh tokens)
4. Set the app status to "Production" if it's still in development mode
5. In the "Permissions" tab, ensure all required scopes are selected

## Environment Variables

Make sure to update the following environment variables in your `.env` file to match your configured callback URLs:

```
# For Google OAuth
GOOGLE_REDIRECT_URI=http://localhost:5000/users/login/google/callback

# For Authentik OAuth
AUTHENTIK_REDIRECT_URI=http://localhost:5000/users/login/authentik/callback

# For Spotify API
SPOTIFY_REDIRECT_URI=http://localhost:5000/users/spotify-callback

# For Dropbox API
# DROPBOX_REDIRECT_URI=http://localhost:5000/users/dropbox-callback
# Note: The Dropbox URL is automatically generated using Flask's url_for function
```

In production, update these URLs to use your actual domain.

## Additional Notes

1. Make sure your application is properly configured to handle these callback routes.
2. For security, always use HTTPS URLs in production environments.
3. When testing locally with HTTP, some providers may require you to explicitly allow HTTP redirects for development.
4. If you're using Docker or other containerization, ensure your application is accessible at the configured URLs.
5. Dropbox requires the app to be in "Production" mode for non-developers to use it.

## Troubleshooting

If you encounter OAuth errors such as "invalid_redirect_uri" or "redirect_uri_mismatch":

1. Verify that the callback URL is exactly the same in both your OAuth provider configuration and your application code.
2. Check that the protocol (http vs https) matches what's configured.
3. Ensure there are no trailing slashes unless specifically required.
4. For development behind NAT/firewalls, you may need to use a service like ngrok to create a public URL.
5. Check that the response data format matches what your code expects. For Google OAuth, ensure your code is accessing fields correctly (Google uses 'sub' for user IDs rather than 'id').
6. Enable debug logging to inspect the full OAuth response payload to identify missing or incorrectly named fields.
7. Verify that your OAuth scopes in the provider configuration match the scopes requested in your application code.
8. Test with a minimal set of scopes first, then add more as needed once the basic flow works.

### Dropbox-Specific Troubleshooting

If you see "This app is not valid" error from Dropbox:
1. Make sure your app is configured in the [Dropbox App Console](https://www.dropbox.com/developers/apps)
2. Verify that your app key and app secret in your config match what's in the Dropbox console
3. Ensure your redirect URI is correctly registered in the Dropbox console
4. Check if your app needs to be in "Production" mode (it may be in development mode)
5. Verify that you've selected all required permission scopes in the Dropbox console