"""
GET /api/spotify/playlist/{playlist_id}?offset=0&limit=100
GET /api/spotify/playlist?url=...&offset=0&limit=100

Endpoint sin estado que utiliza spotifyscraper para obtener páginas de hasta 100
canciones de una playlist pública de Spotify sin requerir cuenta Premium ni OAuth.
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

from fastapi import FastAPI, HTTPException, Path as PathParam, Query
from fastapi.middleware.cors import CORSMiddleware

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from api._shared import (  # noqa: E402
    extract_and_validate_playlist_id,
    fetch_spotify_playlist_page_stateless,
    sanitize_error_message,
)

app = FastAPI(title="SongExtractor - Spotify Scraper Proxy", docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)


def _handle_playlist_request(target: str, offset: int, limit: int) -> dict[str, Any]:
    try:
        playlist_id = extract_and_validate_playlist_id(target)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    try:
        return fetch_spotify_playlist_page_stateless(
            playlist_id=playlist_id,
            offset=offset,
            limit=limit,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except Exception as exc:
        clean_err = sanitize_error_message(str(exc))
        raise HTTPException(
            status_code=502,
            detail=f"No se pudo obtener la playlist desde Spotify: {clean_err}",
        ) from None


@app.get("/api/spotify/playlist/{playlist_id}")
@app.get("/{playlist_id}")
def get_spotify_playlist_by_id(
    playlist_id: str = PathParam(..., description="ID de 22 caracteres de la playlist de Spotify"),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
) -> dict[str, Any]:
    return _handle_playlist_request(target=playlist_id, offset=offset, limit=limit)


@app.get("/")
@app.get("/api/spotify/playlist")
def get_spotify_playlist_by_query(
    playlist_id: str | None = Query(default=None, description="ID o URL de la playlist de Spotify"),
    url: str | None = Query(default=None, description="URL HTTPS de la playlist de Spotify"),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
) -> dict[str, Any]:
    target = (playlist_id or url or "").strip()
    if not target:
        raise HTTPException(
            status_code=400,
            detail="Debes indicar el parámetro 'playlist_id' o 'url' de la playlist de Spotify.",
        )
    return _handle_playlist_request(target=target, offset=offset, limit=limit)
