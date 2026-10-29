"""
POST /api/ytmusic/add - Creación de playlist y adición de canciones (individual o por lotes) en YouTube Music.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import time
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
    action: Literal["create_playlist", "add_item", "add_batch"] = Field(
        default="add_item",
        description="Acción a ejecutar: crear playlist, añadir 1 canción o añadir un lote",
    )
    playlist_id: str | None = Field(default=None, description="ID de la playlist en YouTube Music")
    video_id: str | None = Field(default=None, description="videoId individual a añadir")
    video_ids: list[str] | None = Field(default=None, description="Lista de videoIds para inserción por lotes")
    title: str | None = Field(default=None, description="Título para crear una nueva playlist")
    description: str | None = Field(default="", description="Descripción de la nueva playlist")
    privacy_status: Literal["PRIVATE", "PUBLIC", "UNLISTED"] = Field(default="PRIVATE")


def _clean_yt_text(value: str, max_len: int = 150) -> str:
    cleaned = (value or "").replace("<", "(").replace(">", ")").strip()
    return cleaned[:max_len]


def _is_unauthorized_session_error(exc: Exception | str) -> bool:
    msg = str(exc).lower()
    return (
        "http 401" in msg
        or "401: unauthorized" in msg
        or "not authorized to edit this playlist" in msg
        or "unauthenticated" in msg
    )


@app.post("/")
@app.post("/api/ytmusic/add")
def add_to_ytmusic_playlist(
    payload: YTMusicAddRequest,
    x_ytmusic_cookie: str | None = Header(default=None),
) -> dict[str, Any]:
    """
    Crea una nueva playlist o añade uno o varios videoIds a una playlist existente
    en YouTube Music sin almacenar credenciales ni estado en el servidor.
    """
    cookie_raw = (payload.cookie or x_ytmusic_cookie or "").strip()
    if not cookie_raw:
        raise HTTPException(
            status_code=400,
            detail="Falta la credencial de sesión de YouTube Music (Cookie).",
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
            title = _clean_yt_text(payload.title or "Playlist de Spotify", 150)
            desc = _clean_yt_text(payload.description or "Transferida con SongExtractor", 400)
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
                            "message": "Límite diario de YouTube alcanzado al crear la playlist.",
                        },
                    )
                raise HTTPException(
                    status_code=502,
                    detail=f"YouTube Music no devolvió un identificador de playlist válido: {playlist_id}",
                )
            return {
                "status": "created",
                "playlist_id": playlist_id,
                "playlist_url": f"https://music.youtube.com/playlist?list={playlist_id}",
                "quota_cost": 50,
            }

        # Inserción individual o por lotes (reduce las llamadas autenticadas hasta un 95%)
        ids_to_add: list[str] = []
        if payload.video_ids:
            ids_to_add = [v.strip() for v in payload.video_ids if v and v.strip()]
        elif payload.video_id and payload.video_id.strip():
            ids_to_add = [payload.video_id.strip()]

        if not payload.playlist_id or not ids_to_add:
            raise HTTPException(
                status_code=400,
                detail="Se requieren 'playlist_id' y al menos un 'video_id' para añadir canciones.",
            )

        last_exc: Exception | None = None
        add_result: Any = None
        for attempt in range(1, 3):
            try:
                if attempt > 1:
                    time.sleep(1.2)
                    yt = create_stateless_ytmusic_client(cookie_raw)
                add_result = yt.add_playlist_items(
                    playlistId=payload.playlist_id.strip(),
                    videoIds=ids_to_add,
                    duplicates=True,
                )
                last_exc = None
                break
            except Exception as exc:
                last_exc = exc
                if is_quota_exceeded_error(exc):
                    break

        if last_exc is not None:
            raise last_exc

        if isinstance(add_result, dict):
            status_val = str(add_result.get("status") or "")
            if "FAILURE" in status_val.upper():
                serialized = json.dumps(add_result)
                if is_quota_exceeded_error(serialized):
                    raise HTTPException(
                        status_code=403,
                        detail={
                            "code": "QUOTA_EXCEEDED",
                            "message": "Se alcanzó el límite diario de YouTube. Continúa mañana.",
                        },
                    )

        return {
            "status": "added",
            "playlist_id": payload.playlist_id,
            "video_ids": ids_to_add,
            "added_count": len(ids_to_add),
            "quota_cost": 50 * len(ids_to_add),
        }

    except HTTPException:
        raise
    except Exception as exc:
        clean_err = sanitize_error_message(str(exc), [cookie_raw])
        if _is_unauthorized_session_error(exc):
            raise HTTPException(
                status_code=401,
                detail=(
                    "Tu sesión temporal de YouTube Music caducó (Google rota la cookie de seguridad "
                    "tras varias peticiones o si se cierra la ventana de incógnito). "
                    "Tus canciones ya añadidas están a salvo: vuelve a copiar la Cookie actual desde "
                    "music.youtube.com (F12 → Red → browse), pégala abajo y pulsa Continuar."
                ),
            ) from None
        if is_quota_exceeded_error(exc):
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "QUOTA_EXCEEDED",
                    "message": (
                        "Límite diario de YouTube alcanzado. "
                        "Tu avance está guardado en el navegador para continuar mañana."
                    ),
                },
            ) from None
        raise HTTPException(
            status_code=502,
            detail=f"Error al operar en YouTube Music: {clean_err}",
        ) from None
