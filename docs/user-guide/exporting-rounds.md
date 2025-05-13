# Exporting Rounds

This guide explains the available methods for exporting your music quiz rounds from Quizzical Beats.

## Available Export Options

Quizzical Beats currently supports the following export options:

- **PDF**: Round document with questions, answers, and song information
- **MP3**: Audio file with all songs concatenated for playback during your quiz
- **JSON**: Metadata about the round and songs (exported automatically with Dropbox exports)

## Local Export

To export a round to your local device:

1. Navigate to the Rounds page
2. Select the round you want to view
3. Click the "Download MP3" or "Download PDF" button to save the respective file

## Dropbox Export

Quizzical Beats integrates with Dropbox to easily store your rounds in the cloud:

### Connecting to Dropbox

1. Go to your Profile page
2. Find the "Connected Services" section
3. Click "Connect Dropbox"
4. Follow the authorization prompts from Dropbox
5. Once connected, your Dropbox status will show as "Connected"

### Setting Your Dropbox Export Path

1. Go to your Profile page > Edit Profile
2. Find the "Dropbox Export Path" field
3. Enter your preferred folder path or use the default "/QuizzicalBeats"
4. If your account is connected, you can click "Browse" to select a folder
5. Save your changes

### Exporting Rounds to Dropbox

1. Navigate to the Rounds page
2. Select the round you want to export
3. Click "Export to Dropbox" button in the export options section
4. In the export modal, choose whether to include MP3 files
5. Click "Export Round" to send the files to your configured Dropbox folder

The system will create a folder structure in your Dropbox with the following format:
```
/[Your Export Path]/Round_[ID]_[Round Name]/
  ├── round_[ID].mp3  (if MP3 option was selected)
  ├── round_[ID].pdf
  └── Metadata/
      └── round_[ID]_metadata.json
```

After the export completes successfully, you will see shared links to access each exported file directly.

## Troubleshooting Exports

### Failed Dropbox Export
1. Check your Dropbox connection status in your Profile
2. If your token has expired, reconnect your Dropbox account 
3. If the export fails because MP3 generation is required, click the provided link to generate the MP3 first
4. Verify you have sufficient Dropbox storage space
5. Check for any error messages displayed during the export process

### MP3 Export Issues
1. Ensure all songs in the round have valid preview URLs
2. Try regenerating the round MP3 by clicking the "Generate MP3" button on the round page
3. If some songs lack preview URLs, you may need to edit those songs to add valid URLs