import json
import os
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

DATA_DIR = Path(os.getenv("RADAR_DATA_DIR", "/data"))
DB_PATH = DATA_DIR / "radar.sqlite3"
FPCALC = os.getenv("FPCALC_BIN", "fpcalc")
ADMIN_TOKEN = os.getenv("RADAR_ADMIN_TOKEN", "")
MAX_BYTES = 8 * 1024 * 1024
MIN_BYTES = 8 * 1024
MAX_SECONDS = 20
ALLOWED_ORIGIN = os.getenv("RADAR_ALLOWED_ORIGIN", "https://valutedmusic.site")
ALLOWED_TYPES = {
    "audio/mpeg", "audio/mp3", "audio/mp4", "audio/aac", "audio/wav",
    "audio/x-wav", "audio/ogg", "audio/webm", "audio/flac",
    "application/octet-stream",
}

app = FastAPI(title="VALUTED MUSIC Radar", docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[ALLOWED_ORIGIN],
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["Content-Type", "X-Radar-Admin"],
)

def db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            artist TEXT NOT NULL,
            album TEXT DEFAULT '',
            release_year TEXT DEFAULT '',
            genre TEXT DEFAULT '',
            music_url TEXT DEFAULT '',
            fingerprint TEXT NOT NULL,
            duration REAL NOT NULL,
            created_at INTEGER NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tracks_title_artist ON tracks(title, artist)")
    conn.commit()
    return conn

def fingerprint(path: str, max_length: int = MAX_SECONDS):
    proc = subprocess.run(
        [FPCALC, "-raw", "-json", "-length", str(max_length), path],
        capture_output=True, text=True, timeout=45, check=False
    )
    if proc.returncode != 0:
        raise ValueError("Audio could not be decoded by Chromaprint")
    result = json.loads(proc.stdout.strip().splitlines()[-1])
    values = result.get("fingerprint")
    if not isinstance(values, list) or len(values) < 20:
        raise ValueError("The sample is too short to fingerprint reliably")
    return [int(v) & 0xFFFFFFFF for v in values], float(result.get("duration", 0))

def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()

def best_match(query, candidates):
    # Compare query windows at every possible alignment. Score is the
    # percentage of aligned subfingerprints within 6 differing bits.
    best_score, best_offset = 0.0, 0
    for offset in range(max(1, len(candidates) - len(query) + 1)):
        pairs = min(len(query), len(candidates) - offset)
        if pairs < 16:
            continue
        close = sum(hamming(query[i], candidates[offset + i]) <= 6 for i in range(pairs))
        score = close / pairs
        if score > best_score:
            best_score, best_offset = score, offset
    return best_score, best_offset

@app.get("/health")
def health():
    with db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
    return {"ok": True, "engine": "Chromaprint", "indexed_tracks": count, "external_recognition_api": False}

@app.post("/admin/index")
async def index_track(
    audio: UploadFile = File(...),
    title: str = Form(...),
    artist: str = Form(...),
    album: str = Form(""),
    release_year: str = Form(""),
    genre: str = Form(""),
    music_url: str = Form(""),
    x_radar_admin: Optional[str] = Header(default=None),
):
    if not ADMIN_TOKEN or x_radar_admin != ADMIN_TOKEN:
        raise HTTPException(403, "Admin authorization required")
    payload = await audio.read(MAX_BYTES + 1)
    if len(payload) < MIN_BYTES or len(payload) > MAX_BYTES:
        raise HTTPException(413, "Audio must be between 8 KB and 8 MB")
    suffix = Path(audio.filename or "sample.bin").suffix[:8] or ".bin"
    with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
        tmp.write(payload)
        tmp.flush()
        try:
            fp, duration = fingerprint(tmp.name, max_length=600)
        except Exception as exc:
            raise HTTPException(422, str(exc))
    with db() as conn:
        conn.execute(
            """INSERT INTO tracks(title,artist,album,release_year,genre,music_url,fingerprint,duration,created_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (title.strip(), artist.strip(), album.strip(), release_year.strip(),
             genre.strip(), music_url.strip(), json.dumps(fp), duration, int(time.time()))
        )
        conn.commit()
    return {"indexed": True, "title": title, "artist": artist, "fingerprint_frames": len(fp)}

@app.post("/recognize")
async def recognize(audio: UploadFile = File(...)):
    if audio.content_type and audio.content_type.lower() not in ALLOWED_TYPES:
        raise HTTPException(415, "Unsupported audio format")
    payload = await audio.read(MAX_BYTES + 1)
    if len(payload) < MIN_BYTES or len(payload) > MAX_BYTES:
        raise HTTPException(413, "Audio must be between 8 KB and 8 MB")
    suffix = Path(audio.filename or "recording.bin").suffix[:8] or ".bin"
    with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
        tmp.write(payload)
        tmp.flush()
        try:
            query, duration = fingerprint(tmp.name)
        except Exception as exc:
            raise HTTPException(422, str(exc))
    with db() as conn:
        rows = conn.execute("SELECT * FROM tracks").fetchall()
    if not rows:
        return {"match": None, "message": "The private VALUTED MUSIC fingerprint library is empty."}
    ranked = []
    for row in rows:
        candidate = json.loads(row["fingerprint"])
        score, offset = best_match(query, candidate)
        ranked.append((score, offset, row))
    score, offset, row = max(ranked, key=lambda item: item[0])
    # Conservative threshold: return no match rather than guessing.
    if score < 0.72:
        return {"match": None, "message": "No confident match in the VALUTED MUSIC library."}
    return {
        "match": {
            "title": row["title"], "artist": row["artist"], "album": row["album"],
            "release_year": row["release_year"], "genre": row["genre"],
            "music_url": row["music_url"], "confidence": round(score, 3)
        }
    }
