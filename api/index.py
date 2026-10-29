"""
Punto de entrada FastAPI unificado para desarrollo local y funciones serverless.
Endpoints stateless:
- GET  /api/spotify/playlist/{playlist_id}
- GET  /api/spotify/playlist
- POST /api/ytmusic/search
- POST /api/ytmusic/add
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.spotify.playlist import get_spotify_playlist_by_id, get_spotify_playlist_by_query
from api.ytmusic.add import add_to_ytmusic_playlist
from api.ytmusic.search import search_ytmusic_track

app = FastAPI(title="SongExtractor Stateless API Proxy", docs_url="/api/docs")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

app.add_api_route("/api/spotify/playlist/{playlist_id}", get_spotify_playlist_by_id, methods=["GET"])
app.add_api_route("/api/spotify/playlist", get_spotify_playlist_by_query, methods=["GET"])
app.add_api_route("/api/ytmusic/search", search_ytmusic_track, methods=["POST"])
app.add_api_route("/api/ytmusic/add", add_to_ytmusic_playlist, methods=["POST"])


@app.get("/api/health")
def health_check() -> dict[str, str]:
    return {"status": "ok", "mode": "stateless-scraper-no-oauth"}
