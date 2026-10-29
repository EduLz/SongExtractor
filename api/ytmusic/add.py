"""
POST /api/ytmusic/add - Creación de playlist y adición de canciones sin estado en YouTube Music.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any, Literal

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
)

app = FastAPI(title="SongExtractor - YouTube Music Add Proxy", docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["*"],
)


class YTMusicAddRequest(BaseModel):
    cookie: str | None = Field(
        default=None,
        description="Cadena de cabecera Cookie o JSON de browser.json de YouTube Music",
    )
    action: Literal["create_playlist", "add_item"] = Field(
        default="add_item",
        description="Acción a ejecutar: crear playlist o añadir canción",
    )
    playlist_id: str | None = Field(default=None, description="ID de la playlist en YouTube Music")
    video_id: str | None = Field(default=None, description="videoId de la canción a añadir")
    title: str | None = Field(default=None, description="Título para crear una nueva playlist")
    description: str | None = Field(default="", description="Descripción de la nueva playlist")
    privacy_status: Literal["PRIVATE", "PUBLIC", "UNLISTED"] = Field(default="PRIVATE")


def _clean_yt_text(value: str, max_len: int = 150) -> str:
    cleaned = (value or "").replace("<", "(").replace(">", ")").strip()
    return cleaned[:max_len]


@app.post("/")
@app.post("/api/ytmusic/add")
def add_to_ytmusic_playlist(
    payload: YTMusicAddRequest,
    x_ytmusic_cookie: str | None = Header(default=None),
) -> dict[str, Any]:
    """
    Crea una nueva playlist o añade un videoId a una playlist existente en YouTube Music
    sin almacenar credenciales ni estado en el servidor.
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
            detail=f"Error al validar las credenciales de YouTube Music: {clean_err}",
        ) from None

    try:
        if payload.action == "create_playlist":
            title = _clean_yt_text(payload.title or "Spotify Migrated Playlist", 150)
            desc = _clean_yt_text(payload.description or "Migrada con SongExtractor", 400)
            playlist_id = yt.create_playlist(
                title=title,
                description=desc,
                privacy_status=payload.privacy_status,
            )
            if not playlist_id or not isinstance(playlist_id, str) or "error" in playlist_id.lower():
                if is_quota_exceeded_error(str(playlist_id)):
                    raise HTTPException(
                        status_code=403,
                        detail={
                            "code": "QUOTA_EXCEEDED",
                            "message": "Cuota de YouTube agotada al intentar crear la playlist (403 quotaExceeded).",
                        },
                    )
                raise HTTPException(
                    status_code=502,
                    detail=f"YouTube Music no devolvió un ID de playlist válido: {playlist_id}",
                )
            return {
                "status": "created",
                "playlist_id": playlist_id,
                "playlist_url": f"https://music.youtube.com/playlist?list={playlist_id}",
                "quota_cost": 50,
            }

        # Acción por defecto: add_item
        if not payload.playlist_id or not payload.video_id:
            raise HTTPException(
                status_code=400,
                detail="Se requieren 'playlist_id' y 'video_id' para añadir una canción.",
            )

        add_result = yt.add_playlist_items(
            playlistId=payload.playlist_id.strip(),
            videoIds=[payload.video_id.strip()],
            duplicates=False,
        )

        if isinstance(add_result, dict):
            status_val = str(add_result.get("status") or "")
            if "FAILURE" in status_val.upper():
                serialized = json.dumps(add_result)
                if is_quota_exceeded_error(serialized):
                    raise HTTPException(
                        status_code=403,
                        detail={
                            "code": "QUOTA_EXCEEDED",
                            "message": "Se agotó la cuota diaria de YouTube (403 quotaExceeded). Reanuda mañana.",
                        },
                    )

        return {
            "status": "added",
            "playlist_id": payload.playlist_id,
            "video_id": payload.video_id,
            "quota_cost": 50,
        }

    except HTTPException:
        raise
    except Exception as exc:
        clean_err = sanitize_error_message(str(exc), [cookie_raw])
        if is_quota_exceeded_error(exc):
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "QUOTA_EXCEEDED",
                    "message": (
                        "Cuota diaria de YouTube agotada (HTTP 403 quotaExceeded). "
                        "Tu progreso está guardado en el navegador para continuar en la próxima sesión."
                    ),
                },
            ) from None
        raise HTTPException(
            status_code=502,
            detail=f"Error al operar en YouTube Music: {clean_err}",
        ) from None

