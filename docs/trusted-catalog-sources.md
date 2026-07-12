# Trusted catalog sources

Quizzical Beats treats discovery, identity resolution, and import as separate steps.
A source is only refreshable when it has a provider-specific adapter and a fixture
test. A candidate must have a stable Spotify or Deezer track ID before approval.

## Production-ready adapters

| Source | Signal | Input | Stable identity | Adapter status |
| --- | --- | --- | --- | --- |
| [Spotify Top 10k snapshot](https://annas-archive.pk/blog/spotify/spotify-top-10k-songs-table.html) | broad popularity | HTML table | Spotify ID and ISRC | verified |
| [Official Singles Chart](https://www.officialcharts.com/charts/singles-chart/) | UK chart | server-rendered HTML | title and artist, then offline resolution | verified |
| [Deezer Top Tracks](https://api.deezer.com/chart/0/tracks?limit=100) | global chart | JSON API | Deezer track ID; ISRC from track lookup | verified |
| [NDR 2 playlist](https://www.ndr.de/ndr2/programm/ndr2-playlist,radioplaylist-ndr2-100.html) | German radio airplay | server-rendered HTML | title and artist, then offline resolution | verified |
| [ListenBrainz weekly recordings](https://api.listenbrainz.org/1/stats/sitewide/recordings?range=week&count=100) | open weekly listens | JSON API | MusicBrainz recording ID, then recording resolution | verified |

## Resolution services

| Service | Use | Constraint |
| --- | --- | --- |
| Internal Spotify archive | exact ISRC, Spotify ID, and conservative title/artist matching | metadata snapshot, read-only |
| [Deezer track API](https://api.deezer.com/track/3135556) | Deezer ID to ISRC and current preview metadata | bounded provider calls |
| [MusicBrainz recordings](https://musicbrainz.org/doc/MusicBrainz_API/Search) | recording identity and ISRC lookup | meaningful User-Agent and at most one call per second |

## Researched but not refreshable

| Source | Finding | Next requirement |
| --- | --- | --- |
| [RADIO BOB! playlist](https://www.radiobob.de/musik/playlist) | The web client references an IRIS search service and station 69 for the national stream, but the observed endpoint returns 404 externally and history requires login. | obtain a documented or permitted endpoint before adding an adapter |
| [setlist.fm API](https://api.setlist.fm/docs/1.0/index.html) | Structured artist/set/song data, useful for live staples and festival themes. It identifies artists with MusicBrainz IDs but not specific commercial recordings. | API key, per-artist query plan, and recording-resolution step |
| [Apple Music charts](https://developer.apple.com/documentation/applemusicapi/charts) | Structured storefront charts with Apple song IDs. | developer token plus Apple-ID-to-ISRC resolution |
| [Last.fm top tracks](https://www.last.fm/api/show/chart.getTopTracks) | Structured popularity signal with artist and track text. | API key and recording-resolution step |
| Billboard charts | Current pages return anti-automation/marketing HTML rather than chart rows. | licensed or documented chart feed |
| German official charts | Current public endpoint rejects the application fetch. | licensed or documented chart feed |
| Festival line-up pages | They contain artists, not tracks. | explicit artist-to-track selection policy, such as top recordings or recent setlists |

Album charts and festival line-ups remain research sources. They must never be
passed through the track parser because an album or artist cannot identify the
recording that should be imported.
