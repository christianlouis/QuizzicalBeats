# Exporting Rounds

This guide explains the available methods for exporting your music quiz rounds from Quizzical Beats.

## Available Export Options

Quizzical Beats currently supports the following export options:

- **PDF**: Round document with questions, answers, and song information
- **MP3**: Audio file with all songs concatenated for playback during your quiz
- **JSON**: Metadata about the round and songs (exported automatically with Dropbox exports)
- **Spotify and Deezer** create private playlists of the full recordings in your linked account.

## Spotify and Deezer playlists

1. Open a round you own or can produce. Save any changes to its songs or their order.
2. Under **Playlists**, connect your personal Spotify or Deezer account if prompted.
3. Click **Create Spotify playlist** or **Create Deezer playlist**. Use **Open playlist** to listen in the service.

If Deezer account linking is not configured, the round page offers **Download Deezer
playlist file**. This downloads a UTF-8 XSPF file containing the saved song order and
repeated songs. Open **Import file into Deezer via TuneMyMusic**, upload the file there,
and review the playlist name and selected tracks before confirming the transfer to your
Deezer account. You control the upload. To transfer a changed round, download a fresh
file. The round page reports any saved songs missing from the local catalog.

The playlist takes the round's name. **Update** synchronizes its tracks and order with the
saved round, including removing tracks you took out. Each provider and each linked account
gets its own playlist. Changes made directly to that playlist can be replaced on the next update.

If a recording is unavailable or the artist and title match multiple recordings, the page
lists the affected songs. Choose **Use … available songs** to export just the matches.
Spotify retains repeated recordings. Deezer accepts each recording once and lists any
repeats before you decide. If the service cannot confirm that a playlist is private, the
app keeps its link and waits for you to set it to private before sending any songs.

## Local Export

To export a round to your local device:

1. Navigate to the Rounds page
2. Select the round you want to view
3. Click the "Download MP3" or "Download PDF" button to save the respective file

## Email Delivery

Round email delivery is protected by the package quality gate. Before an email
is sent, Quizzical Beats checks that the round has the expected number of songs,
that preview clips are playable and within the configured length range, and that
the generated MP3/PDF artifacts pass inspection.

If the package gate fails, the email is not sent. The round detail page shows the
repair feedback, including missing or too-short previews and replacement actions.
Scheduled emails use the same gate and keep a failed export message on the round
so the issue can be repaired before resending.

Some checks are warnings rather than delivery blockers. For example, a small MP3
duration difference is shown for review, while a mismatch large enough to suggest
a missing song remains blocked until the MP3 is regenerated or the round is
repaired.

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

## Playing a saved music round in Quizarium

Open the saved round and select **Download for Quizarium** under **Export Options**.
In the Quizarium admin panel, open **Content exchange**, choose the JSON file, and
import it. Each recording keeps its saved position, with one point each for the
artist and song title. The host sees the running order and plays the recordings
from their own source. The file contains the answer key and belongs with the host.
