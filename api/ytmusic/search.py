"""
POST /api/ytmusic/search - Búsqueda sin estado de canciones en YouTube Music.
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from api._shared import (  # noqa: E402
    create_stateless_ytmusic_client,
    is_quota_exceeded_error,
    sanitize_error_message,
    score_yt_candidate,
)

app = FastAPI(title="SongExtractor - YouTube Music Search Proxy", docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["*"],
)


class YTMusicSearchRequest(BaseModel):
    cookie: str | None = Field(
        default=None,
        description="Cadena de cabecera Cookie o JSON de browser.json de YouTube Music",
    )
    title: str = Field(..., min_length=1, description="Título de la canción")
    artist: str = Field(default="", description="Artista principal")
    album: str = Field(default="", description="Nombre del álbum")
    duration_ms: int | None = Field(default=None, description="Duración en milisegundos")
    isrc: str | None = Field(default=None, description="Código ISRC opcional")


@app.post("/")
@app.post("/api/ytmusic/search")
def search_ytmusic_track(
    payload: YTMusicSearchRequest,
    x_ytmusic_cookie: str | None = Header(default=None),
) -> dict[str, Any]:
    """
    Realiza la búsqueda de una canción en YouTube Music totalmente en memoria y
    devuelve el mejor resultado junto con su puntuación de confianza.
    """
    cookie_raw = (payload.cookie or x_ytmusic_cookie or "").strip()
    if not cookie_raw:
        raise HTTPException(
            status_code=400,
            detail="Falta la cookie de sesión de YouTube Music (browser.json).",
        )

    try:
        yt = create_stateless_ytmusic_client(cookie_raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except Exception as exc:
        clean_err = sanitize_error_message(str(exc), [cookie_raw])
        raise HTTPException(
            status_code=400,
            detail=f"No se pudo inicializar la sesión de YouTube Music: {clean_err}",
        ) from None

    query = f"{payload.title} {payload.artist}".strip()

    try:
        results = yt.search(query, filter="songs")
        if not results:
            results = yt.search(query, filter="videos")
    except Exception as exc:
        clean_err = sanitize_error_message(str(exc), [cookie_raw])
        if is_quota_exceeded_error(exc):
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "QUOTA_EXCEEDED",
                    "message": (
                        "Se ha alcanzado el límite de cuota o tasa de YouTube Music (403 quotaExceeded). "
                        "El estado está guardado en tu navegador; puedes reanudar en la siguiente sesión."
                    ),
                },
            ) from None
        raise HTTPException(
            status_code=502,
            detail=f"Error al buscar en YouTube Music: {clean_err}",
        ) from None

    valid_candidates = [
        r for r in (results or []) if isinstance(r, dict) and r.get("videoId")
    ]
    if not valid_candidates:
        return {
            "found": False,
            "confidence": 0.0,
            "match": None,
        }

    scored = []
    for candidate in valid_candidates[:5]:
        conf = score_yt_candidate(
            title=payload.title,
            artist=payload.artist,
            duration_ms=payload.duration_ms,
            candidate=candidate,
        )
        artists_str = ", ".join(
            a.get("name", "")
            for a in (candidate.get("artists") or [])
            if isinstance(a, dict) and a.get("name")
        )
        thumbs = candidate.get("thumbnails") or []
        thumb_url = thumbs[-1].get("url") if thumbs and isinstance(thumbs[-1], dict) else None
        scored.append(
            (
                conf,
                {
                    "videoId": candidate["videoId"],
                    "title": candidate.get("title") or payload.title,
                    "artist": artists_str or payload.artist,
                    "album": (candidate.get("album") or {}).get("name")
                    if isinstance(candidate.get("album"), dict)
                    else "",
                    "duration": candidate.get("duration") or "",
                    "duration_seconds": candidate.get("duration_seconds"),
                    "thumbnail": thumb_url,
                },
            )
        )

    best_conf, best_item = scored[0]
    for conf, item in scored[1:]:
        if conf > best_conf + 0.12:
            best_conf, best_item = conf, item

    return {
        "found": True,
        "confidence": best_conf,
        "low_confidence": best_conf < 0.55,
        "match": best_item,
    }

