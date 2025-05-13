# Frequently Asked Questions

## General Questions

### What is Quizzical Beats?
Quizzical Beats is a web application designed to help quiz hosts create music quiz rounds. It integrates with Spotify and Deezer to access vast music libraries and provides tools for round generation, song management, and export options.

### Is Quizzical Beats free to use?
Yes, Quizzical Beats is free to use and is released under the MIT license, which allows for both personal and commercial use. You can find the full license details in the LICENSE file in the project repository.

### Which browsers are supported?
Quizzical Beats works with all modern browsers including Chrome, Firefox, Safari, and Edge. For the best experience, we recommend keeping your browser updated to the latest version.

## Account Management

### How do I create an account?
You can create an account by visiting the login page and clicking "Register." You can sign up with an email and password or use OAuth providers like Spotify, Google, or Authentik (if enabled by your administrator).

### Can I change my password?
Yes, you can change your password by going to Profile > Security > Change Password.

### I forgot my password. How do I reset it?
On the login page, click the "Forgot Password" link and follow the instructions sent to your email.

### How do I connect my Spotify account?
Go to Profile > Connected Accounts and click "Connect" next to Spotify. You'll be redirected to Spotify to authorize the connection.

### Why should I connect my Dropbox account?
Connecting your Dropbox account allows you to export quiz rounds directly to your Dropbox, making it easy to access them from any device or share them with others.

## Song Management

### How many songs can I import at once?
You can import up to 100 songs at once when importing from a Spotify or Deezer playlist. For CSV imports, there's a limit of 500 songs per file.

### Why are some of my songs missing preview URLs?
Some streaming services don't provide preview URLs for all tracks. If a song doesn't have a preview URL, you'll need to find an alternative version of the song that has a preview available.

### How can I edit song metadata?
Select the song from your library and click "Edit." You can then modify its metadata including title, artist, album, and year.

### Can I add my own songs not found on Spotify or Deezer?
No, currently Quizzical Beats does not support uploading your own MP3 files. All songs must be imported from supported streaming services like Spotify or Deezer.

## Round Creation

### How many rounds can I create?
There's no fixed limit on the number of rounds you can create, though performance may decrease with very large numbers of rounds (1000+).

### What's the ideal number of songs in a round?
Most quiz hosts find 8-10 songs per round works well, providing enough variety without making the round too long.

### Can I reuse songs across multiple rounds?
Yes, you can add the same song to multiple rounds. The song library keeps track of all your songs, allowing you to reuse them as needed.

### How do I create a themed round?
Use the filter options when creating a round to focus on specific genres, decades, or artists. You can also create a custom round by manually selecting songs that fit your theme.

## Exporting

### What export formats are available?
Quizzical Beats supports exporting rounds as PDF (questions and answers), MP3 (audio files), ZIP (combined package), and JSON (raw data).

### How do I export directly to Dropbox?
Connect your Dropbox account, then when exporting a round, select "Export to Dropbox" as the destination. You can then choose which folder to export to.

### Can I customize the exported PDFs?
No, the PDF export format is standardized and cannot be customized. All PDFs follow a consistent layout that includes round information, song details, and answer fields.

### Why is my export taking a long time?
Exports with many rounds or large audio files may take longer. MP3 generation and packaging can be resource-intensive.

## Troubleshooting

### Spotify or Deezer connection isn't working
Try disconnecting and reconnecting your account. If the issue persists, ensure that your account is active and that you've granted all the required permissions.

### The application seems slow
Performance depends on several factors including your device, internet connection, and the size of your song library. Try clearing your browser cache or using a different browser.

### Audio playback issues
If you're experiencing audio playback issues, check your device volume, try a different browser, or ensure that you have a stable internet connection.

### I found a bug. How do I report it?
Contact your system administrator or send an email to support@kaufdeinquiz.com with details about the bug and steps to reproduce it.

## Administration

### How do I back up my data?
Administrators can create backups through the Admin > System > Backup interface. Backups can be scheduled or created manually and include the database, media files, and configuration.

### How do I restore from a backup?
Go to Admin > System > Restore, select the backup file, and follow the instructions to restore your data.

### Can I run Quizzical Beats offline?
Quizzical Beats requires internet access to connect to Spotify, Deezer, and other services. However, once songs are imported, you can use some features offline.

### How do I update Quizzical Beats?
Administrators can update the application by pulling the latest version from the repository and restarting the application. For Docker installations, update the container image.