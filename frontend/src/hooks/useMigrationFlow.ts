import { useCallback, useEffect, useReducer, useRef } from 'react';
import {
  addTracksBatchToYTMusicPlaylist,
  createYTMusicPlaylist,
  fetchSpotifyPlaylistPage,
  parseSpotifyPlaylistUrl,
  QuotaExceededError,
  searchYTMusicTrack,
  SessionExpiredError,
  STORAGE_KEYS,
} from '../lib/api';
import {
  FlowStep,
  PlaylistMetadata,
  SpotifyTrack,
  TrackMigrationRecord,
  UploadStateSession,
} from '../lib/types';

export interface MigrationState {
  step: FlowStep;
  playlistUrl: string;
  isExtracting: boolean;
  extractionProgress: { loaded: number; total: number; playlistName?: string };
  metadata: PlaylistMetadata | null;
  tracks: SpotifyTrack[];
  ytCookie: string;
  ytPlaylistTitle: string;
  ytPrivacy: 'PRIVATE' | 'PUBLIC' | 'UNLISTED';
  respectQuotaLimit: boolean;
  delayMs: number;
  uploadState: UploadStateSession | null;
  isMigrating: boolean;
  isPaused: boolean;
  needsCookieRefresh: boolean;
  currentTrackIndex: number | null;
  quotaExceededBanner: string | null;
  errorBanner: string | null;
}

type Action =
  | { type: 'SET_STEP'; step: FlowStep }
  | { type: 'SET_URL'; url: string }
  | { type: 'START_EXTRACTION' }
  | { type: 'SET_METADATA'; metadata: PlaylistMetadata }
  | {
      type: 'APPEND_TRACKS';
      tracks: SpotifyTrack[];
      loaded: number;
      total: number;
      playlistName?: string;
    }
  | { type: 'FINISH_EXTRACTION' }
  | { type: 'SET_YT_COOKIE'; cookie: string }
  | { type: 'SET_YT_TITLE'; title: string }
  | { type: 'SET_YT_PRIVACY'; privacy: 'PRIVATE' | 'PUBLIC' | 'UNLISTED' }
  | { type: 'SET_RESPECT_QUOTA'; value: boolean }
  | { type: 'SET_DELAY_MS'; delayMs: number }
  | { type: 'SET_UPLOAD_STATE'; uploadState: UploadStateSession }
  | { type: 'START_MIGRATION' }
  | { type: 'PAUSE_MIGRATION' }
  | { type: 'SET_COOKIE_EXPIRED'; message: string }
  | { type: 'FINISH_MIGRATION'; toSummary: boolean }
  | { type: 'SET_CURRENT_TRACK'; index: number | null }
  | { type: 'SET_QUOTA_BANNER'; message: string | null }
  | { type: 'SET_ERROR'; message: string | null }
  | { type: 'HYDRATE_SESSION'; partial: Partial<MigrationState> }
  | { type: 'RESET_ALL' };

const initialState: MigrationState = {
  step: 'connect',
  playlistUrl: '',
  isExtracting: false,
  extractionProgress: { loaded: 0, total: 0 },
  metadata: null,
  tracks: [],
  ytCookie: '',
  ytPlaylistTitle: '',
  ytPrivacy: 'PRIVATE',
  respectQuotaLimit: true,
  delayMs: 600,
  uploadState: null,
  isMigrating: false,
  isPaused: false,
  needsCookieRefresh: false,
  currentTrackIndex: null,
  quotaExceededBanner: null,
  errorBanner: null,
};

const BATCH_SIZE = 15;

function reducer(state: MigrationState, action: Action): MigrationState {
  switch (action.type) {
    case 'SET_STEP':
      return { ...state, step: action.step, errorBanner: null };
    case 'SET_URL':
      return { ...state, playlistUrl: action.url, errorBanner: null };
    case 'START_EXTRACTION':
      return {
        ...state,
        isExtracting: true,
        errorBanner: null,
        tracks: [],
        extractionProgress: { loaded: 0, total: 0 },
      };
    case 'SET_METADATA':
      return {
        ...state,
        metadata: action.metadata,
        ytPlaylistTitle: state.ytPlaylistTitle || action.metadata.name,
        extractionProgress: {
          loaded: state.extractionProgress.loaded,
          total: action.metadata.total_tracks,
          playlistName: action.metadata.name,
        },
      };
    case 'APPEND_TRACKS':
      return {
        ...state,
        tracks: [...state.tracks, ...action.tracks],
        extractionProgress: {
          loaded: action.loaded,
          total: action.total,
          playlistName: action.playlistName || state.extractionProgress.playlistName,
        },
      };
    case 'FINISH_EXTRACTION':
      return { ...state, isExtracting: false, step: 'preview' };
    case 'SET_YT_COOKIE':
      sessionStorage.setItem(STORAGE_KEYS.YTMUSIC_COOKIE, action.cookie);
      return {
        ...state,
        ytCookie: action.cookie,
        needsCookieRefresh: false,
        errorBanner: null,
      };
    case 'SET_YT_TITLE':
      return { ...state, ytPlaylistTitle: action.title };
    case 'SET_YT_PRIVACY':
      return { ...state, ytPrivacy: action.privacy };
    case 'SET_RESPECT_QUOTA':
      return { ...state, respectQuotaLimit: action.value };
    case 'SET_DELAY_MS':
      return { ...state, delayMs: Math.max(400, action.delayMs) };
    case 'SET_UPLOAD_STATE':
      sessionStorage.setItem(STORAGE_KEYS.UPLOAD_STATE, JSON.stringify(action.uploadState));
      return { ...state, uploadState: action.uploadState };
    case 'START_MIGRATION':
      return {
        ...state,
        step: 'migrate',
        isMigrating: true,
        isPaused: false,
        needsCookieRefresh: false,
        errorBanner: null,
        quotaExceededBanner: null,
      };
    case 'PAUSE_MIGRATION':
      return { ...state, isMigrating: false, isPaused: true, currentTrackIndex: null };
    case 'SET_COOKIE_EXPIRED':
      return {
        ...state,
        isMigrating: false,
        isPaused: true,
        needsCookieRefresh: true,
        currentTrackIndex: null,
        errorBanner: action.message,
      };
    case 'FINISH_MIGRATION':
      return {
        ...state,
        isMigrating: false,
        isPaused: false,
        currentTrackIndex: null,
        step: action.toSummary ? 'summary' : state.step,
      };
    case 'SET_CURRENT_TRACK':
      return { ...state, currentTrackIndex: action.index };
    case 'SET_QUOTA_BANNER':
      return { ...state, quotaExceededBanner: action.message };
    case 'SET_ERROR':
      return { ...state, errorBanner: action.message, isExtracting: false };
    case 'HYDRATE_SESSION':
      return { ...state, ...action.partial };
    case 'RESET_ALL':
      sessionStorage.removeItem(STORAGE_KEYS.UPLOAD_STATE);
      sessionStorage.removeItem(STORAGE_KEYS.EXTRACTED_PLAYLIST);
      return {
        ...initialState,
        ytCookie: state.ytCookie,
      };
    default:
      return state;
  }
}

function getTrackKey(track: SpotifyTrack): string {
  return `${track.index}:${track.spotify_uri || track.spotify_id || track.title}`;
}

export function useMigrationFlow() {
  const [state, dispatch] = useReducer(reducer, initialState);
  const pauseRequestedRef = useRef(false);

  useEffect(() => {
    const storedCookie = sessionStorage.getItem(STORAGE_KEYS.YTMUSIC_COOKIE) || '';
    const hydrated: Partial<MigrationState> = {
      ytCookie: storedCookie,
    };

    const cachedPlaylistRaw = sessionStorage.getItem(STORAGE_KEYS.EXTRACTED_PLAYLIST);
    const cachedUploadRaw = sessionStorage.getItem(STORAGE_KEYS.UPLOAD_STATE);

    if (cachedPlaylistRaw) {
      try {
        const parsedPlaylist = JSON.parse(cachedPlaylistRaw);
        if (parsedPlaylist?.metadata && Array.isArray(parsedPlaylist?.tracks)) {
          hydrated.metadata = parsedPlaylist.metadata;
          hydrated.tracks = parsedPlaylist.tracks;
          hydrated.playlistUrl = parsedPlaylist.playlistUrl || '';
          hydrated.ytPlaylistTitle = parsedPlaylist.metadata.name;
          hydrated.step = 'preview';
        }
      } catch {
        // Ignorar caché inválida
      }
    }

    if (cachedUploadRaw) {
      try {
        const parsedUpload = JSON.parse(cachedUploadRaw) as UploadStateSession;
        if (parsedUpload?.source_playlist_id) {
          hydrated.uploadState = parsedUpload;
          hydrated.ytPlaylistTitle = parsedUpload.yt_playlist_title;
          hydrated.ytPrivacy = parsedUpload.yt_privacy || 'PRIVATE';
        }
      } catch {
        // Ignorar estado corrupto
      }
    }

    dispatch({ type: 'HYDRATE_SESSION', partial: hydrated });
  }, []);

  const extractSpotifyPlaylist = useCallback(async () => {
    const validation = parseSpotifyPlaylistUrl(state.playlistUrl);
    if (!validation.valid || !validation.playlistId) {
      dispatch({
        type: 'SET_ERROR',
        message: validation.error || 'Enlace de playlist no válido.',
      });
      return;
    }

    const playlistId = validation.playlistId;
    dispatch({ type: 'START_EXTRACTION' });

    try {
      const allTracks: SpotifyTrack[] = [];
      let offset = 0;
      const limit = 100;
      let meta: PlaylistMetadata | null = null;

      while (true) {
        const page = await fetchSpotifyPlaylistPage({
          playlistId,
          offset,
          limit,
        });

        if (!meta) {
          meta = {
            playlist_id: page.playlist_id,
            name: page.name,
            description: page.description,
            owner: page.owner,
            cover_url: page.cover_url,
            total_tracks: page.total,
          };
          dispatch({ type: 'SET_METADATA', metadata: meta });
        }

        const normalizedPageTracks = (page.tracks || []).map((t, i) => ({
          ...t,
          index: allTracks.length + i,
        }));
        allTracks.push(...normalizedPageTracks);

        dispatch({
          type: 'APPEND_TRACKS',
          tracks: normalizedPageTracks,
          loaded: allTracks.length,
          total: page.total || allTracks.length,
          playlistName: page.name,
        });

        if (!page.has_next || page.next_offset === null || normalizedPageTracks.length === 0) {
          break;
        }
        offset = page.next_offset;
      }

      if (!meta || allTracks.length === 0) {
        throw new Error(
          'No se encontraron canciones disponibles en esta playlist. Verifica que sea una playlist pública.'
        );
      }

      meta.total_tracks = allTracks.length;
      dispatch({ type: 'SET_METADATA', metadata: meta });

      sessionStorage.setItem(
        STORAGE_KEYS.EXTRACTED_PLAYLIST,
        JSON.stringify({
          playlistUrl: state.playlistUrl.trim(),
          metadata: meta,
          tracks: allTracks,
        })
      );

      const existingStateRaw = sessionStorage.getItem(STORAGE_KEYS.UPLOAD_STATE);
      let upState: UploadStateSession | null = null;
      if (existingStateRaw) {
        try {
          const parsed = JSON.parse(existingStateRaw) as UploadStateSession;
          if (parsed.source_playlist_id === meta.playlist_id) {
            upState = parsed;
          }
        } catch {
          upState = null;
        }
      }

      if (!upState) {
        const nowIso = new Date().toISOString();
        const records: Record<number, TrackMigrationRecord> = {};
        allTracks.forEach((t) => {
          records[t.index] = {
            index: t.index,
            trackKey: getTrackKey(t),
            status: 'pending',
          };
        });
        upState = {
          source_playlist_id: meta.playlist_id,
          source_playlist_url: state.playlistUrl.trim(),
          source_playlist_name: meta.name,
          yt_playlist_id: null,
          yt_playlist_title: meta.name,
          yt_privacy: 'PRIVATE',
          created_at: nowIso,
          updated_at: nowIso,
          total_tracks_in_source: allTracks.length,
          processed_indices: [],
          processed_track_keys: [],
          added_video_ids: [],
          track_records: records,
          estimated_quota_used: 0,
        };
      }

      dispatch({ type: 'SET_UPLOAD_STATE', uploadState: upState });
      dispatch({ type: 'FINISH_EXTRACTION' });
    } catch (err) {
      const msg =
        err instanceof Error
          ? err.message
          : 'No pudimos leer esa playlist. Asegúrate de que sea pública.';
      dispatch({ type: 'SET_ERROR', message: msg });
    }
  }, [state.playlistUrl]);

  const startOrResumeMigration = useCallback(async () => {
    if (!state.ytCookie.trim() || !state.ytCookie.includes('__Secure-3PAPISID')) {
      dispatch({
        type: 'SET_ERROR',
        message:
          'Necesitas pegar tu credencial de sesión de YouTube Music para continuar. Haz clic en "¿Cómo conecto mi cuenta?" para ver los pasos.',
      });
      return;
    }
    if (!state.uploadState || state.tracks.length === 0) {
      dispatch({
        type: 'SET_ERROR',
        message: 'Primero elige una playlist de Spotify.',
      });
      return;
    }

    pauseRequestedRef.current = false;
    dispatch({ type: 'START_MIGRATION' });

    const currentState: UploadStateSession = JSON.parse(JSON.stringify(state.uploadState));
    currentState.yt_playlist_title =
      state.ytPlaylistTitle.trim() || currentState.source_playlist_name;
    currentState.yt_privacy = state.ytPrivacy;

    try {
      if (!currentState.yt_playlist_id) {
        const created = await createYTMusicPlaylist({
          cookie: state.ytCookie,
          title: currentState.yt_playlist_title,
          description: `Transferida desde Spotify (${currentState.source_playlist_name})`,
          privacyStatus: currentState.yt_privacy,
        });
        currentState.yt_playlist_id = created.playlist_id;
        currentState.estimated_quota_used += created.quota_cost || 50;
        currentState.updated_at = new Date().toISOString();
        dispatch({ type: 'SET_UPLOAD_STATE', uploadState: { ...currentState } });
      }

      const processedSet = new Set(currentState.processed_indices);
      let pendingTracks = state.tracks.filter((t) => !processedSet.has(t.index));

      if (state.respectQuotaLimit) {
        pendingTracks = pendingTracks.slice(0, 190);
      }

      // Procesar en lotes de BATCH_SIZE (15 canciones por inserción) para reducir
      // un 95% las llamadas autenticadas a YouTube Music y evitar caducidad HTTP 401
      for (let i = 0; i < pendingTracks.length; i += BATCH_SIZE) {
        if (pauseRequestedRef.current) {
          dispatch({ type: 'PAUSE_MIGRATION' });
          return;
        }

        const chunk = pendingTracks.slice(i, i + BATCH_SIZE);
        const matchedChunk: {
          track: SpotifyTrack;
          videoId: string;
          matchedTitle: string;
          matchedArtist: string;
          confidence: number;
          isLowConf: boolean;
        }[] = [];

        // 1. Buscar cada canción del lote usando el catálogo público (sin consumir la cookie)
        for (const track of chunk) {
          if (pauseRequestedRef.current) {
            break;
          }

          dispatch({ type: 'SET_CURRENT_TRACK', index: track.index });
          currentState.track_records[track.index] = {
            index: track.index,
            trackKey: getTrackKey(track),
            status: 'searching',
          };
          dispatch({ type: 'SET_UPLOAD_STATE', uploadState: { ...currentState } });

          const searchRes = await searchYTMusicTrack({ track });

          if (!searchRes.found || !searchRes.match) {
            currentState.track_records[track.index] = {
              index: track.index,
              trackKey: getTrackKey(track),
              status: 'failed',
              errorReason: 'No disponible en YouTube Music',
            };
            currentState.processed_indices.push(track.index);
            currentState.processed_track_keys.push(getTrackKey(track));
            currentState.updated_at = new Date().toISOString();
            dispatch({ type: 'SET_UPLOAD_STATE', uploadState: { ...currentState } });
          } else {
            matchedChunk.push({
              track,
              videoId: searchRes.match.videoId,
              matchedTitle: searchRes.match.title,
              matchedArtist: searchRes.match.artist,
              confidence: searchRes.confidence,
              isLowConf: Boolean(searchRes.low_confidence || searchRes.confidence < 0.55),
            });
          }

          await new Promise((resolve) => setTimeout(resolve, 250));
        }

        // 2. Añadir todas las canciones encontradas del lote en UNA SOLA llamada autenticada
        if (matchedChunk.length > 0) {
          await addTracksBatchToYTMusicPlaylist({
            cookie: state.ytCookie,
            playlistId: currentState.yt_playlist_id!,
            videoIds: matchedChunk.map((m) => m.videoId),
          });

          for (const item of matchedChunk) {
            currentState.track_records[item.track.index] = {
              index: item.track.index,
              trackKey: getTrackKey(item.track),
              status: item.isLowConf ? 'low_confidence' : 'added',
              videoId: item.videoId,
              matchedTitle: item.matchedTitle,
              matchedArtist: item.matchedArtist,
              confidence: item.confidence,
            };
            currentState.processed_indices.push(item.track.index);
            currentState.processed_track_keys.push(getTrackKey(item.track));
            currentState.added_video_ids.push(item.videoId);
            currentState.estimated_quota_used += 50;
          }
          currentState.updated_at = new Date().toISOString();
          dispatch({ type: 'SET_UPLOAD_STATE', uploadState: { ...currentState } });
        }

        if (pauseRequestedRef.current) {
          dispatch({ type: 'PAUSE_MIGRATION' });
          return;
        }

        await new Promise((resolve) => setTimeout(resolve, Math.max(500, state.delayMs)));
      }

      const allDone = currentState.processed_indices.length >= state.tracks.length;
      dispatch({ type: 'FINISH_MIGRATION', toSummary: allDone });
      if (!allDone && state.respectQuotaLimit) {
        dispatch({
          type: 'SET_QUOTA_BANNER',
          message:
            '¡Has completado la tanda recomendada de hoy (190 canciones)! Guarda tu archivo de progreso para continuar mañana desde donde te quedaste.',
        });
      }
    } catch (err) {
      if (err instanceof SessionExpiredError) {
        dispatch({
          type: 'SET_COOKIE_EXPIRED',
          message: err.message,
        });
        return;
      }
      if (err instanceof QuotaExceededError) {
        dispatch({ type: 'PAUSE_MIGRATION' });
        dispatch({
          type: 'SET_QUOTA_BANNER',
          message:
            'Se alcanzó el límite diario permitido por YouTube. Tu avance se ha pausado de forma segura; descarga tu progreso para continuar mañana.',
        });
        return;
      }
      const msg = err instanceof Error ? err.message : 'Ocurrió un problema durante la transferencia';
      dispatch({ type: 'PAUSE_MIGRATION' });
      dispatch({ type: 'SET_ERROR', message: msg });
    }
  }, [
    state.ytCookie,
    state.uploadState,
    state.tracks,
    state.ytPlaylistTitle,
    state.ytPrivacy,
    state.respectQuotaLimit,
    state.delayMs,
  ]);

  const requestPause = useCallback(() => {
    pauseRequestedRef.current = true;
    dispatch({ type: 'PAUSE_MIGRATION' });
  }, []);

  const exportUploadStateJson = useCallback(() => {
    if (!state.uploadState) return;
    const payload = {
      uploadState: state.uploadState,
      metadata: state.metadata,
      tracks: state.tracks,
      playlistUrl: state.playlistUrl,
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], {
      type: 'application/json',
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    const safeName = (state.uploadState.source_playlist_name || 'playlist')
      .replace(/[^a-zA-Z0-9_-]+/g, '_')
      .slice(0, 40);
    a.download = `progreso_${safeName}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }, [state.uploadState, state.metadata, state.tracks, state.playlistUrl]);

  const importUploadStateJson = useCallback((jsonText: string) => {
    try {
      const parsed = JSON.parse(jsonText);
      if (parsed?.uploadState && Array.isArray(parsed?.tracks) && parsed?.metadata) {
        sessionStorage.setItem(
          STORAGE_KEYS.EXTRACTED_PLAYLIST,
          JSON.stringify({
            playlistUrl: parsed.playlistUrl || parsed.uploadState.source_playlist_url || '',
            metadata: parsed.metadata,
            tracks: parsed.tracks,
          })
        );
        dispatch({
          type: 'HYDRATE_SESSION',
          partial: {
            metadata: parsed.metadata,
            tracks: parsed.tracks,
            playlistUrl: parsed.playlistUrl || parsed.uploadState.source_playlist_url || '',
            ytPlaylistTitle: parsed.uploadState.yt_playlist_title || parsed.metadata.name,
            ytPrivacy: parsed.uploadState.yt_privacy || 'PRIVATE',
            step: 'ytconfig',
          },
        });
        dispatch({ type: 'SET_UPLOAD_STATE', uploadState: parsed.uploadState });
        return;
      }

      if (parsed?.source_playlist_id && Array.isArray(parsed?.processed_indices)) {
        dispatch({ type: 'SET_UPLOAD_STATE', uploadState: parsed as UploadStateSession });
        return;
      }

      throw new Error('El archivo seleccionado no es un archivo de progreso válido.');
    } catch (err) {
      const msg =
        err instanceof Error ? err.message : 'No se pudo leer el archivo de progreso seleccionado.';
      dispatch({ type: 'SET_ERROR', message: msg });
    }
  }, []);

  return {
    state,
    dispatch,
    extractSpotifyPlaylist,
    startOrResumeMigration,
    requestPause,
    exportUploadStateJson,
    importUploadStateJson,
  };
}
