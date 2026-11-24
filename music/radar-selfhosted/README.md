# VALUTED MUSIC Radar — self-hosted, no external recognition API

This service uses the open-source Chromaprint fingerprint generator and a private SQLite fingerprint library. It does not call AudD, AcoustID, Shazam, Spotify, Apple Music, or another recognition provider.

## What it can and cannot do

- Listens to a microphone recording or accepts an audio upload from the VALUTED MUSIC page.
- Fingerprints the sample locally on this server and compares it with tracks we have indexed.
- Returns title, artist, album, year, genre, and the VALUTED MUSIC page URL stored with that track.
- Returns no match when confidence is below the conservative threshold.
- It cannot identify songs absent from our private fingerprint library. Metadata-only catalogue records are not enough; we need lawful audio files to fingerprint.
- It does not recognize humming or singing.

Chromaprint generates fingerprints; it is not a worldwide music-recognition catalogue. The official project describes its focus as matching near-identical recordings. See https://acoustid.org/chromaprint and https://github.com/acoustid/chromaprint.

## Run

Build and run with persistent storage:

```sh
docker build -t valuted-music-radar .
docker run -d --name valuted-music-radar \
  -p 8080:8080 \
  -v valuted-radar-data:/data \
  -e RADAR_ADMIN_TOKEN='SET_A_LONG_RANDOM_SECRET' \
  -e RADAR_ALLOWED_ORIGIN='https://valutedmusic.site' \
  --restart unless-stopped valuted-music-radar
```

Put the service behind HTTPS using a reverse proxy. Do not expose port 8080 directly to the public internet. Keep the admin token private.

## Add a track to the private library

Only index audio files that VALUTED MUSIC is authorized to process. Send the file and metadata to the protected admin route:

```sh
curl -X POST 'https://YOUR-OWN-RADAR-HOST/admin/index' \
  -H 'X-Radar-Admin: YOUR_ADMIN_TOKEN' \
  -F 'audio=@licensed-track.mp3' \
  -F 'title=Track title' \
  -F 'artist=Artist name' \
  -F 'album=Album name' \
  -F 'release_year=2026' \
  -F 'genre=Pop' \
  -F 'music_url=https://valutedmusic.site/blogs/news/track-handle'
```

## Recognize a microphone sample or uploaded clip

POST multipart form field `audio` to `/recognize`. The browser should capture a short 10–20 second sample and send it to this endpoint. Microphone permission is requested by the browser; the site must be served over HTTPS.

## Operational safeguards

- Persist `/data`; otherwise the fingerprint library is lost when the container is replaced.
- Keep admin indexing protected and rate-limit public recognition at the reverse proxy.
- The first version uses a straightforward alignment scan intended for a small pilot library. Benchmark and move to a dedicated fingerprint index before scaling to a large catalogue.
- No audio samples are intentionally retained after processing; the SQLite database stores fingerprints and metadata only.
- The service is not deployed by this repository commit. Hosting, HTTPS, a secure admin token, a rights-cleared seed library, and browser wiring are still required.
