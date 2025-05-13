# Account Management

This guide explains how to manage your Quizzical Beats account, including profile settings, integrations, and authentication options.

## Profile Settings

Manage your personal information and preferences:

1. Click your username in the top-right corner
2. Select "Profile" from the dropdown menu
3. Here you can:
   - Update your username
   - Change your email address
   - Edit your first and last name
   - Modify your password
   - Update your Dropbox export path

## Authentication Methods

Quizzical Beats supports multiple authentication methods:

### Local Username/Password

1. Go to Profile > Change Password
2. You can:
   - Update your current password
   - View your last login time

### OAuth Providers

Connect and use third-party authentication:

1. Navigate to your Profile page
2. Here you can connect/disconnect:
   - Spotify account
   - Google account (if enabled by your administrator)
   - Dropbox account (for file exports)
   - Authentik (if enabled by your administrator)

## Email-Based Account Identification

Quizzical Beats uses your email address as the primary identifier for your account, which provides several benefits:

### Single Account Across Login Methods

- If you login with username/password and later use Google or Authentik with the same email address, **you'll be automatically logged into the same account**
- There's no need to manually link accounts - the system recognizes you based on your email
- Your profile data, saved rounds, and settings remain consistent regardless of how you login

For example:
1. You register with username "musicfan" and email "you@example.com"
2. Later, you click "Sign in with Google" using the same email "you@example.com" 
3. The system will recognize and log you into your existing "musicfan" account
4. All your data, settings, and history will be preserved

### Switching Between Login Methods

You can freely alternate between:
- Username/password login
- Google authentication (if enabled)
- Authentik authentication (if enabled)

As long as all methods use the same email address, you'll always access the same account.

### Benefits

- **Simplified Experience**: No need to remember which login method you used previously
- **Data Consistency**: Your preferences and data remain unified across login methods
- **Flexible Authentication**: Choose the most convenient login method for your current situation

## Managing OAuth Connections

For each connected service:

1. View connection status and details
2. Disconnect services when needed
3. Re-authorize when tokens expire
4. See token expiration information

## Custom Audio Files

Upload and manage your custom audio files:

1. Navigate to Profile > Audio Settings
2. Here you can:
   - Upload custom intro music
   - Upload custom outro music
   - Upload custom replay sound
   - Generate audio using text-to-speech

## Account Security

Keep your account secure:

1. Use a strong, unique password
2. Log out from shared computers
3. Check your last login time
4. Review connected applications regularly

## Troubleshooting

**Can't Log In**:
1. Try the "Forgot Password" option
2. Check that you're using the correct OAuth provider
3. Clear browser cookies and cache
4. Contact your administrator if problems persist

**OAuth Connection Issues**:
1. Disconnect and reconnect the service
2. Ensure you're granting all required permissions
3. Check that your third-party account is active and in good standing