# MusicRound

**MusicRound** is a Flask-based web application for building engaging music rounds for pub quizzes. Leveraging the Spotify API, it allows you to generate rounds based on the least-used genres, decades, or completely random criteria, making your quizzes dynamic and entertaining.

---

## Features

- **Spotify Integration**: Import songs and playlists directly from Spotify using their API.
- **Dynamic Round Creation**:
  - Randomly generated songs.
  - Based on least-used genres or decades.
  - Unique and diverse song selections.
- **Preview and Export**:
  - Include Spotify preview links in rounds.
  - Export rounds as printable **PDFs** and playable **MP3s**.
- **Last.fm Integration**: Automatically enrich tracks with genre metadata.
- **Email Delivery**: Email generated quiz rounds to the designated recipient.

---

## Getting Started

### Prerequisites

- **Python**: Version 3.6 or higher.
- **Spotify Developer Account**: [Create a Spotify Developer App](https://developer.spotify.com/dashboard/applications) to retrieve your client ID and secret.
- **Last.fm API Key**: Sign up at [Last.fm](https://www.last.fm/api) to obtain an API key.

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/christianlouis/musicround.git
   cd musicround
   ```

2. Create a virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Set up environment variables in a `.env` file:
   ```env
   SPOTIFY_CLIENT_ID=your_spotify_client_id
   SPOTIFY_CLIENT_SECRET=your_spotify_client_secret
   SPOTIFY_REDIRECT_URI=http://localhost:5000/callback
   LASTFM_API_KEY=your_lastfm_api_key
   ```

5. Initialize the SQLite database:
   ```bash
   python
   >>> from app import db
   >>> db.create_all()
   >>> exit()
   ```

6. Start the application:
   ```bash
   python app.py
   ```

7. Open your browser and navigate to `http://localhost:5000`.

---

## APIs Used

- **Spotify API**:
  - Used to import songs, playlists, and retrieve song metadata.
  - [API Documentation](https://developer.spotify.com/documentation/web-api/)

- **Last.fm API**:
  - Enriches tracks with genre information.
  - [API Documentation](https://www.last.fm/api)

### Provided APIs

**MusicRound** also provides APIs to fetch data from the application. For example:

- `GET /rounds`: Fetch all rounds created.
- `POST /rounds`: Create a new round using specified criteria.
- `GET /songs`: Retrieve all songs in the database.

For detailed API usage, refer to the in-app documentation or inspect the routes in `app.py`.

---

## Changelog

### Version 1.0
- Initial release.
- Features:
  - Spotify and Last.fm integration.
  - Random, genre-based, and decade-based round generation.
  - PDF and MP3 export functionality.
  - Email delivery of rounds.

---

## Project Structure

```
musicround/
├── app.py               # Main application logic
├── config.py            # Configuration settings
├── templates/           # HTML templates for rendering views
├── static/              # Static files (CSS, JS)
├── requirements.txt     # Python dependencies
├── instance/            # SQLite database folder
├── mp3/                 # Audio files for MP3 generation
├── pdf_reports/         # Generated PDF reports
├── README.md            # Project documentation
└── rounds/              # MP3 cache for quiz rounds
```

---

## License

This project is licensed under the **MIT License**. See `LICENSE` for details.

---

## Contributing

We welcome contributions! To contribute:

1. Fork the repository.
2. Create a feature branch:
   ```bash
   git checkout -b feature/your-feature-name
   ```
3. Commit your changes:
   ```bash
   git commit -m "Add your feature description"
   ```
4. Push the branch:
   ```bash
   git push origin feature/your-feature-name
   ```
5. Open a pull request.

---

## Contact

- **Developer**: Christian Krakau-Louis
- **Email**: [christian@kaufdeinquiz.com](mailto:christian@kaufdeinquiz.com)
- **GitHub**: [christianlouis](https://github.com/christianlouis)
