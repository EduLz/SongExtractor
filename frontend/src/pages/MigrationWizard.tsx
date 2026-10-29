import React, { useMemo, useRef, useState } from 'react';
import { CookieHelpModal } from '../components/CookieHelpModal';
import { SkeletonLoader } from '../components/SkeletonLoader';
import { StepIndicator } from '../components/StepIndicator';
import { useMigrationFlow } from '../hooks/useMigrationFlow';
import { FlowStep, TrackMigrationRecord } from '../lib/types';

function formatDuration(ms: number): string {
  if (!ms || ms <= 0) return '0:00';
  const totalSec = Math.floor(ms / 1000);
  const mins = Math.floor(totalSec / 60);
  const secs = totalSec % 60;
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}

export const MigrationWizard: React.FC = () => {
  const {
    state,
    dispatch,
    extractSpotifyPlaylist,
    startOrResumeMigration,
    requestPause,
    exportUploadStateJson,
    importUploadStateJson,
  } = useMigrationFlow();

  const [isCookieModalOpen, setIsCookieModalOpen] = useState(false);
  const [searchFilter, setSearchFilter] = useState('');
  const [summaryStatusFilter, setSummaryStatusFilter] = useState<
    'all' | 'added' | 'low_confidence' | 'failed' | 'pending'
  >('all');
  const [summarySearch, setSummarySearch] = useState('');
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const stats = useMemo(() => {
    const records: Record<number, TrackMigrationRecord> = state.uploadState?.track_records || {};
    let added = 0;
    let lowConf = 0;
    let failed = 0;
    Object.values(records).forEach((r) => {
      if (r.status === 'added') added += 1;
      else if (r.status === 'low_confidence') {
        added += 1;
        lowConf += 1;
      } else if (r.status === 'failed') failed += 1;
    });
    const processed = added + failed;
    const total = state.tracks.length;
    const pct = total > 0 ? Math.min(100, Math.round((processed / total) * 100)) : 0;
    return { added, lowConf, failed, processed, total, pct };
  }, [state.uploadState, state.tracks.length]);

  const canNavigateTo = (targetStep: FlowStep): boolean => {
    if (state.isExtracting) return false;
    if (targetStep === 'connect') return !state.isMigrating;
    if (targetStep === 'preview') return Boolean(state.metadata && state.tracks.length > 0);
    if (targetStep === 'ytconfig') return Boolean(state.metadata && state.tracks.length > 0);
    if (targetStep === 'migrate')
      return Boolean(state.metadata && state.tracks.length > 0 && state.uploadState);
    if (targetStep === 'summary')
      return Boolean(state.uploadState && state.uploadState.processed_indices.length > 0);
    return false;
  };

  const handleStateFileImport = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === 'string') {
        importUploadStateJson(reader.result);
      }
    };
    reader.readAsText(file);
    e.target.value = '';
  };

  const downloadUnmatchedLog = () => {
    if (!state.uploadState) return;
    const lines: string[] = [
      ` Canciones pendientes de revisión - ${state.uploadState.source_playlist_name}`,
      ` Fecha: ${new Date().toLocaleDateString('es-ES')}`,
      '------------------------------------------------------------',
      '',
    ];
    state.tracks.forEach((t) => {
      const rec = state.uploadState?.track_records[t.index];
      if (!rec) return;
      if (rec.status === 'failed') {
        lines.push(`• No encontrada: "${t.title}" — ${t.artist} (${t.album || 'Sin álbum'})`);
      } else if (rec.status === 'low_confidence') {
        lines.push(
          `• Versión similar añadida: "${t.title}" (${t.artist}) → Se añadió "${rec.matchedTitle}" (${rec.matchedArtist})`
        );
      }
    });
    if (lines.length <= 4) {
      lines.push('¡Todas las canciones se encontraron y añadieron exactamente!');
    }
    const blob = new Blob([lines.join('\n')], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `canciones_por_revisar.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const filteredPreviewTracks = useMemo(() => {
    const q = searchFilter.trim().toLowerCase();
    if (!q) return state.tracks;
    return state.tracks.filter(
      (t) =>
        t.title.toLowerCase().includes(q) ||
        t.artist.toLowerCase().includes(q) ||
        t.album.toLowerCase().includes(q)
    );
  }, [state.tracks, searchFilter]);

  const filteredSummaryTracks = useMemo(() => {
    const records: Record<number, TrackMigrationRecord> = state.uploadState?.track_records || {};
    const q = summarySearch.trim().toLowerCase();

    return state.tracks.filter((t) => {
      const rec = records[t.index];
      const status = rec?.status || 'pending';

      if (summaryStatusFilter === 'added' && status !== 'added' && status !== 'low_confidence') {
        return false;
      }
      if (summaryStatusFilter === 'low_confidence' && status !== 'low_confidence') {
        return false;
      }
      if (summaryStatusFilter === 'failed' && status !== 'failed') {
        return false;
      }
      if (
        summaryStatusFilter === 'pending' &&
        status !== 'pending' &&
        status !== 'searching'
      ) {
        return false;
      }

      if (!q) return true;
      return (
        t.title.toLowerCase().includes(q) ||
        t.artist.toLowerCase().includes(q) ||
        (rec?.matchedTitle && rec.matchedTitle.toLowerCase().includes(q)) ||
        (rec?.matchedArtist && rec.matchedArtist.toLowerCase().includes(q))
      );
    });
  }, [state.tracks, state.uploadState, summaryStatusFilter, summarySearch]);

  const hasValidCookie = state.ytCookie.includes('__Secure-3PAPISID');
  const isLargePlaylist = state.tracks.length > 190;

  return (
    <div className="app-shell">
      <input
        ref={fileInputRef}
        type="file"
        accept=".json"
        style={{ display: 'none' }}
        onChange={handleStateFileImport}
      />

      <header className="topbar">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true">
            <span className="dot-spotify" />
            <span className="brand-arrow">→</span>
            <span className="dot-yt" />
          </div>
          <div>
            <h1 className="brand-title">SongExtractor</h1>
            <p className="brand-subtitle">
              Pasa tus playlists públicas de Spotify a YouTube Music fácilmente
            </p>
          </div>
        </div>

        <div className="topbar-badges">
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => fileInputRef.current?.click()}
          >
            Cargar progreso guardado
          </button>
        </div>
      </header>

      <StepIndicator
        currentStep={state.step}
        onSelectStep={(s) => dispatch({ type: 'SET_STEP', step: s })}
        canNavigateTo={canNavigateTo}
      />

      {state.errorBanner && (
        <div className="banner banner-error" role="alert">
          <div>
            <strong>Aviso:</strong> {state.errorBanner}
          </div>
          <button
            type="button"
            className="btn-icon"
            onClick={() => dispatch({ type: 'SET_ERROR', message: null })}
            aria-label="Cerrar aviso"
          >
            ✕
          </button>
        </div>
      )}

      {state.quotaExceededBanner && (
        <div className="banner banner-warning" role="status">
          <div>
            <strong>Pausa diaria recomendada:</strong> {state.quotaExceededBanner}
          </div>
          <div className="banner-actions">
            <button type="button" className="btn btn-secondary" onClick={exportUploadStateJson}>
              Guardar mi progreso
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => dispatch({ type: 'SET_STEP', step: 'summary' })}
            >
              Ver Resumen
            </button>
          </div>
        </div>
      )}

      <main className="stage-container">
        {state.isExtracting ? (
          <section className="panel-card panel-enter">
            <SkeletonLoader
              loaded={state.extractionProgress.loaded}
              total={state.extractionProgress.total}
              playlistName={state.extractionProgress.playlistName}
            />
          </section>
        ) : null}

        {/* PASO 1: ELEGIR PLAYLIST DE SPOTIFY */}
        {!state.isExtracting && state.step === 'connect' && (
          <section className="panel-card panel-enter">
            <div className="panel-header">
              <span className="step-kicker">Paso 1 de 5</span>
              <h2>¿Qué playlist quieres pasar a YouTube Music?</h2>
              <p className="panel-desc">
                Abre Spotify, entra en cualquier playlist pública, pulsa{' '}
                <strong>Compartir → Copiar enlace de la playlist</strong> y pégalo aquí abajo. No
                necesitas iniciar sesión en Spotify ni tener cuenta Premium.
              </p>
            </div>

            <div className="form-stack">
              <label className="field-label" htmlFor="spotify-url-input">
                Enlace de la playlist de Spotify
              </label>
              <div className="input-row">
                <input
                  id="spotify-url-input"
                  type="url"
                  className="text-input"
                  placeholder="https://open.spotify.com/playlist/..."
                  value={state.playlistUrl}
                  onChange={(e) => dispatch({ type: 'SET_URL', url: e.target.value })}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') extractSpotifyPlaylist();
                  }}
                />
                <button
                  type="button"
                  className="btn btn-primary btn-lg"
                  disabled={!state.playlistUrl.trim()}
                  onClick={extractSpotifyPlaylist}
                >
                  <span className="btn-content">Buscar Canciones →</span>
                </button>
              </div>
            </div>

            <div className="feature-grid">
              <div className="feature-item">
                <h4>Sin cuenta de Spotify</h4>
                <p>
                  Funciona con cualquier lista pública de Spotify sin necesidad de conectar tu
                  cuenta ni tener Spotify Premium.
                </p>
              </div>
              <div className="feature-item">
                <h4>Listas de cualquier tamaño</h4>
                <p>
                  ¿Tienes más de 1.000 o 4.000 canciones? Puedes guardar tu avance en cualquier
                  momento y continuar otro día.
                </p>
              </div>
              <div className="feature-item">
                <h4>Privacidad total</h4>
                <p>
                  Tus listas y tu sesión se procesan al vuelo desde tu navegador; no guardamos nada
                  en ningún servidor.
                </p>
              </div>
            </div>
          </section>
        )}

        {/* PASO 2: VER CANCIONES */}
        {!state.isExtracting && state.step === 'preview' && state.metadata && (
          <section className="panel-card panel-enter">
            <div className="playlist-hero">
              {state.metadata.cover_url ? (
                <img
                  src={state.metadata.cover_url}
                  alt={state.metadata.name}
                  className="playlist-cover"
                />
              ) : (
                <div className="playlist-cover playlist-cover-placeholder">♪</div>
              )}
              <div className="playlist-hero-info">
                <div className="hero-badges">
                  <span className="badge badge-green">Lista encontrada</span>
                  <span className="badge badge-neutral">
                    {state.tracks.length.toLocaleString()} canciones
                  </span>
                </div>
                <h2>{state.metadata.name}</h2>
                <p className="playlist-owner">
                  Creada por <strong>{state.metadata.owner}</strong>
                </p>
              </div>
              <div className="hero-actions">
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => dispatch({ type: 'RESET_ALL' })}
                >
                  Elegir otra lista
                </button>
                <button
                  type="button"
                  className="btn btn-primary btn-lg"
                  onClick={() => dispatch({ type: 'SET_STEP', step: 'ytconfig' })}
                >
                  Continuar a YouTube Music →
                </button>
              </div>
            </div>

            {isLargePlaylist && (
              <div className="quota-card quota-exceeds">
                <div className="quota-card-header">
                  <div>
                    <h4>Tu playlist es grande ({state.tracks.length.toLocaleString()} canciones)</h4>
                    <p>
                      YouTube permite añadir alrededor de <strong>190 canciones por día</strong>.
                    </p>
                  </div>
                  <span className="quota-pill">
                    Se completará en ~{Math.ceil(state.tracks.length / 190)} sesiones
                  </span>
                </div>
                <p className="quota-warning-text">
                  No te preocupes: transferiremos las primeras 190 canciones hoy y podrás descargar
                  un pequeño archivo de progreso para continuar mañana exactamente desde la canción
                  191 sin duplicar la lista.
                </p>
              </div>
            )}

            <div className="table-toolbar">
              <input
                type="search"
                className="text-input search-input"
                placeholder="Buscar una canción o artista en la lista..."
                value={searchFilter}
                onChange={(e) => setSearchFilter(e.target.value)}
              />
              <span className="table-count">
                Mostrando {filteredPreviewTracks.length.toLocaleString()} de{' '}
                {state.tracks.length.toLocaleString()} canciones
              </span>
            </div>

            <div className="track-list-viewport">
              {filteredPreviewTracks.map((track, idx) => (
                <div
                  key={track.spotify_uri + '-' + track.index}
                  className={`track-row ${idx < 12 ? 'track-row-enter' : ''}`}
                  style={idx < 12 ? { animationDelay: `${idx * 30}ms` } : undefined}
                >
                  <span className="track-num">{track.index + 1}</span>
                  <div className="track-main">
                    <span className="track-title">{track.title}</span>
                    <span className="track-artist">
                      {track.artist} {track.album ? `· ${track.album}` : ''}
                    </span>
                  </div>
                  <span className="track-duration">{formatDuration(track.duration_ms)}</span>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* PASO 3: CONFIGURAR YOUTUBE MUSIC */}
        {!state.isExtracting && state.step === 'ytconfig' && (
          <section className="panel-card panel-enter">
            <div className="panel-header">
              <span className="step-kicker">Paso 3 de 5</span>
              <div className="header-with-action">
                <h2>Preparar tu nueva playlist en YouTube Music</h2>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setIsCookieModalOpen(true)}
                >
                  ¿Cómo conecto mi cuenta? (Paso a paso)
                </button>
              </div>
              <p className="panel-desc">
                Elige el nombre que tendrá tu lista en YouTube Music y pega tu credencial temporal
                de navegador siguiendo la guía paso a paso.
              </p>
            </div>

            <div className="form-stack">
              <div className="grid-two">
                <div>
                  <label className="field-label" htmlFor="yt-title-input">
                    Nombre de la playlist en YouTube Music
                  </label>
                  <input
                    id="yt-title-input"
                    type="text"
                    className="text-input"
                    value={state.ytPlaylistTitle}
                    onChange={(e) => dispatch({ type: 'SET_YT_TITLE', title: e.target.value })}
                  />
                </div>
                <div>
                  <label className="field-label" htmlFor="yt-privacy-select">
                     ¿Quién puede verla?
                  </label>
                  <select
                    id="yt-privacy-select"
                    className="text-input"
                    value={state.ytPrivacy}
                    onChange={(e) =>
                      dispatch({
                        type: 'SET_YT_PRIVACY',
                        privacy: e.target.value as 'PRIVATE' | 'PUBLIC' | 'UNLISTED',
                      })
                    }
                  >
                    <option value="PRIVATE">Solo yo (Privada)</option>
                    <option value="UNLISTED">Cualquiera con el enlace (Oculta)</option>
                    <option value="PUBLIC">Todo el mundo (Pública)</option>
                  </select>
                </div>
              </div>

              <div className="cookie-field-header">
                <label className="field-label" htmlFor="yt-cookie-textarea">
                  Credencial de sesión de YouTube Music (Cookie)
                </label>
                <span className={`badge ${hasValidCookie ? 'badge-green' : 'badge-amber'}`}>
                  {hasValidCookie ? '✓ Lista para conectar' : 'Pendiente de pegar'}
                </span>
              </div>
              <textarea
                id="yt-cookie-textarea"
                rows={4}
                className="text-input code-textarea"
                placeholder="Pega aquí el texto Cookie copiado desde music.youtube.com (pulsa el botón de arriba si necesitas ver cómo obtenerlo)"
                value={state.ytCookie}
                onChange={(e) => dispatch({ type: 'SET_YT_COOKIE', cookie: e.target.value })}
              />

              <div className="options-box">
                <label className="checkbox-row">
                  <input
                    type="checkbox"
                    checked={state.respectQuotaLimit}
                    onChange={(e) =>
                      dispatch({ type: 'SET_RESPECT_QUOTA', value: e.target.checked })
                    }
                  />
                  <span>
                    <strong>Pausa diaria automática (recomendado):</strong> detener cada 190
                    canciones para respetar el límite diario de YouTube.
                  </span>
                </label>
              </div>

              {stats.processed > 0 && (
                <div className="resume-bar">
                  <div>
                    <strong>Progreso guardado detectado:</strong> Ya llevas{' '}
                    <span>
                      {stats.processed.toLocaleString()} de {stats.total.toLocaleString()} canciones
                      listas
                    </span>
                  </div>
                  <div className="resume-actions">
                    <button
                      type="button"
                      className="btn btn-secondary"
                      onClick={exportUploadStateJson}
                    >
                      Descargar copia de progreso
                    </button>
                  </div>
                </div>
              )}

              <div className="footer-actions">
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => dispatch({ type: 'SET_STEP', step: 'preview' })}
                >
                  ← Volver a las canciones
                </button>
                <button
                  type="button"
                  className="btn btn-primary btn-lg"
                  disabled={!hasValidCookie}
                  onClick={startOrResumeMigration}
                >
                  {stats.processed > 0
                    ? `Continuar transferencia (${(
                        stats.total - stats.processed
                      ).toLocaleString()} restantes)`
                    : 'Comenzar transferencia →'}
                </button>
              </div>
            </div>
          </section>
        )}

        {/* PASO 4: TRANSFERENCIA EN VIVO */}
        {!state.isExtracting && state.step === 'migrate' && (
          <section className="panel-card panel-enter">
            <div className="migration-header">
              <div>
                <span className="step-kicker">
                  Paso 4 de 5 · {state.isMigrating ? 'Transfiriendo canciones...' : 'En pausa'}
                </span>
                <h2>{state.uploadState?.yt_playlist_title || 'Tu Playlist'}</h2>
                {state.uploadState?.yt_playlist_id && (
                  <p className="yt-playlist-link-row">
                    <a
                      href={`https://music.youtube.com/playlist?list=${state.uploadState.yt_playlist_id}`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Ver mi playlist en YouTube Music ↗
                    </a>
                  </p>
                )}
              </div>

              <div className="migration-controls">
                {state.isMigrating ? (
                  <button type="button" className="btn btn-amber btn-lg" onClick={requestPause}>
                    ⏸ Pausar
                  </button>
                ) : (
                  <button
                    type="button"
                    className="btn btn-primary btn-lg"
                    onClick={startOrResumeMigration}
                    disabled={stats.processed >= stats.total}
                  >
                    ▶ Continuar
                  </button>
                )}
                <button type="button" className="btn btn-secondary" onClick={exportUploadStateJson}>
                  Guardar progreso
                </button>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => dispatch({ type: 'SET_STEP', step: 'summary' })}
                >
                  Ver resumen →
                </button>
              </div>
            </div>

            <div className="progress-card">
              {state.needsCookieRefresh && (
                <div className="alert-box alert-warning" style={{ marginBottom: '16px' }}>
                  <div className="cookie-field-header" style={{ marginBottom: '8px' }}>
                    <strong>Renovar Cookie de YouTube Music para continuar desde la canción {stats.processed + 1}:</strong>
                    <button
                      type="button"
                      className="btn btn-secondary"
                      onClick={() => setIsCookieModalOpen(true)}
                    >
                      Ver pasos (F12 → browse)
                    </button>
                  </div>
                  <textarea
                    rows={3}
                    className="text-input code-textarea"
                    placeholder="Pega aquí la Cookie actualizada desde tu pestaña de YouTube Music y pulsa ▶ Continuar arriba"
                    value={state.ytCookie}
                    onChange={(e) => dispatch({ type: 'SET_YT_COOKIE', cookie: e.target.value })}
                  />
                </div>
              )}

              <div className="progress-stats-row">
                <span>
                  Avance: <strong>{stats.processed.toLocaleString()}</strong> de{' '}
                  <strong>{stats.total.toLocaleString()}</strong> canciones ({stats.pct}%)
                </span>
                <span>
                  {state.isMigrating
                    ? 'No cierres esta pestaña mientras avanza'
                    : 'En pausa — puedes guardar tu progreso'}
                </span>
              </div>
              <div className="progress-bar-track progress-bar-lg">
                <div
                  className="progress-bar-fill"
                  style={{ transform: `scaleX(${Math.max(0.01, stats.pct / 100)})` }}
                />
              </div>

              <div className="kpi-grid">
                <div className="kpi-box kpi-green">
                  <span className="kpi-value">{stats.added.toLocaleString()}</span>
                  <span className="kpi-label">Añadidas</span>
                </div>
                <div className="kpi-box kpi-amber">
                  <span className="kpi-value">{stats.lowConf.toLocaleString()}</span>
                  <span className="kpi-label">Versión similar</span>
                </div>
                <div className="kpi-box kpi-red">
                  <span className="kpi-value">{stats.failed.toLocaleString()}</span>
                  <span className="kpi-label">No disponibles</span>
                </div>
                <div className="kpi-box kpi-neutral">
                  <span className="kpi-value">
                    {Math.max(0, stats.total - stats.processed).toLocaleString()}
                  </span>
                  <span className="kpi-label">Por transferir</span>
                </div>
              </div>
            </div>

            <div className="track-list-viewport">
              {state.tracks.map((track) => {
                const rec = state.uploadState?.track_records[track.index];
                const status = rec?.status || 'pending';
                const isCurrent = state.currentTrackIndex === track.index;

                return (
                  <div
                    key={track.spotify_uri + '-' + track.index}
                    className={`track-row status-${status} ${isCurrent ? 'is-current-row' : ''}`}
                  >
                    <span className="track-num">{track.index + 1}</span>
                    <div className="track-main">
                      <span className="track-title">{track.title}</span>
                      <span className="track-artist">
                        {track.artist}
                        {rec?.matchedTitle && rec.matchedTitle !== track.title
                          ? ` → Añadida como "${rec.matchedTitle}"`
                          : ''}
                      </span>
                    </div>

                    <span className={`status-pill pill-${status}`}>
                      {status === 'pending' && 'En espera'}
                      {status === 'searching' && 'Buscando...'}
                      {status === 'added' && '✓ Añadida'}
                      {status === 'low_confidence' && '✓ Añadida (similar)'}
                      {status === 'failed' && 'No encontrada'}
                    </span>
                  </div>
                );
              })}
            </div>
          </section>
        )}

        {/* PASO 5: RESUMEN FINAL */}
        {!state.isExtracting && state.step === 'summary' && (
          <section className="panel-card panel-enter">
            <div className="summary-hero">
              <span className="badge badge-green">Paso 5 de 5</span>
              <h2>
                {stats.processed >= stats.total
                  ? '¡Tu playlist ya está en YouTube Music!'
                  : 'Avance guardado correctamente'}
              </h2>
              <p className="panel-desc">
                Se han añadido <strong>{stats.added.toLocaleString()}</strong> canciones de la lista{' '}
                <strong>{state.uploadState?.source_playlist_name}</strong>.
                {stats.processed < stats.total
                  ? ' Si vas a cerrar el navegador y continuar otro día, descarga tu archivo de progreso con el botón de abajo.'
                  : ' Recuerda cerrar sesión en la ventana de incógnito que usaste para conectar YouTube Music.'}
              </p>

              <div className="summary-cta-row">
                {state.uploadState?.yt_playlist_id && (
                  <a
                    href={`https://music.youtube.com/playlist?list=${state.uploadState.yt_playlist_id}`}
                    target="_blank"
                    rel="noreferrer"
                    className="btn btn-primary btn-lg"
                  >
                    Abrir mi Playlist en YouTube Music ↗
                  </a>
                )}
                {stats.processed < stats.total && (
                  <button
                    type="button"
                    className="btn btn-secondary btn-lg"
                    onClick={exportUploadStateJson}
                  >
                    Guardar progreso para mañana
                  </button>
                )}
                {(stats.failed > 0 || stats.lowConf > 0) && (
                  <button
                    type="button"
                    className="btn btn-secondary btn-lg"
                    onClick={downloadUnmatchedLog}
                  >
                    Descargar lista de canciones no encontradas
                  </button>
                )}
              </div>
            </div>

            <div className="kpi-grid">
              <button
                type="button"
                className={`kpi-box kpi-interactive kpi-green ${
                  summaryStatusFilter === 'added' ? 'is-selected' : ''
                }`}
                onClick={() =>
                  setSummaryStatusFilter((prev) => (prev === 'added' ? 'all' : 'added'))
                }
              >
                <span className="kpi-value">{stats.added.toLocaleString()}</span>
                <span className="kpi-label">Canciones añadidas</span>
              </button>
              <button
                type="button"
                className={`kpi-box kpi-interactive kpi-amber ${
                  summaryStatusFilter === 'low_confidence' ? 'is-selected' : ''
                }`}
                onClick={() =>
                  setSummaryStatusFilter((prev) =>
                    prev === 'low_confidence' ? 'all' : 'low_confidence'
                  )
                }
              >
                <span className="kpi-value">{stats.lowConf.toLocaleString()}</span>
                <span className="kpi-label">Versiones similares</span>
              </button>
              <button
                type="button"
                className={`kpi-box kpi-interactive kpi-red ${
                  summaryStatusFilter === 'failed' ? 'is-selected' : ''
                }`}
                onClick={() =>
                  setSummaryStatusFilter((prev) => (prev === 'failed' ? 'all' : 'failed'))
                }
              >
                <span className="kpi-value">{stats.failed.toLocaleString()}</span>
                <span className="kpi-label">No disponibles</span>
              </button>
              <button
                type="button"
                className={`kpi-box kpi-interactive kpi-neutral ${
                  summaryStatusFilter === 'pending' ? 'is-selected' : ''
                }`}
                onClick={() =>
                  setSummaryStatusFilter((prev) => (prev === 'pending' ? 'all' : 'pending'))
                }
              >
                <span className="kpi-value">
                  {Math.max(0, stats.total - stats.processed).toLocaleString()}
                </span>
                <span className="kpi-label">Pendientes</span>
              </button>
            </div>

            <div className="summary-details-section">
              <div className="summary-details-header">
                <div>
                  <h3>Detalle de canciones</h3>
                  <p className="summary-details-sub">
                    Revisa qué canciones se añadieron a tu playlist, cuáles usan una versión similar
                    y cuáles no estuvieron disponibles.
                  </p>
                </div>
              </div>

              <div className="summary-filter-bar">
                <div className="filter-pills" role="tablist" aria-label="Filtrar por resultado">
                  <button
                    type="button"
                    role="tab"
                    aria-selected={summaryStatusFilter === 'all'}
                    className={`filter-pill ${summaryStatusFilter === 'all' ? 'is-active' : ''}`}
                    onClick={() => setSummaryStatusFilter('all')}
                  >
                    Todas ({stats.total.toLocaleString()})
                  </button>
                  <button
                    type="button"
                    role="tab"
                    aria-selected={summaryStatusFilter === 'added'}
                    className={`filter-pill ${summaryStatusFilter === 'added' ? 'is-active' : ''}`}
                    onClick={() => setSummaryStatusFilter('added')}
                  >
                    Añadidas ({stats.added.toLocaleString()})
                  </button>
                  {stats.lowConf > 0 && (
                    <button
                      type="button"
                      role="tab"
                      aria-selected={summaryStatusFilter === 'low_confidence'}
                      className={`filter-pill ${
                        summaryStatusFilter === 'low_confidence' ? 'is-active' : ''
                      }`}
                      onClick={() => setSummaryStatusFilter('low_confidence')}
                    >
                      Versión similar ({stats.lowConf.toLocaleString()})
                    </button>
                  )}
                  {stats.failed > 0 && (
                    <button
                      type="button"
                      role="tab"
                      aria-selected={summaryStatusFilter === 'failed'}
                      className={`filter-pill ${
                        summaryStatusFilter === 'failed' ? 'is-active' : ''
                      }`}
                      onClick={() => setSummaryStatusFilter('failed')}
                    >
                      No disponibles ({stats.failed.toLocaleString()})
                    </button>
                  )}
                  {stats.total - stats.processed > 0 && (
                    <button
                      type="button"
                      role="tab"
                      aria-selected={summaryStatusFilter === 'pending'}
                      className={`filter-pill ${
                        summaryStatusFilter === 'pending' ? 'is-active' : ''
                      }`}
                      onClick={() => setSummaryStatusFilter('pending')}
                    >
                      Pendientes ({Math.max(0, stats.total - stats.processed).toLocaleString()})
                    </button>
                  )}
                </div>

                <input
                  type="search"
                  className="text-input search-input"
                  placeholder="Buscar canción o artista en el resultado..."
                  value={summarySearch}
                  onChange={(e) => setSummarySearch(e.target.value)}
                />
              </div>

              <div className="track-list-viewport">
                {filteredSummaryTracks.length === 0 ? (
                  <div className="empty-filter-state">
                    No hay canciones en esta categoría con el filtro actual.
                  </div>
                ) : (
                  filteredSummaryTracks.map((track) => {
                    const rec = state.uploadState?.track_records[track.index];
                    const status = rec?.status || 'pending';
                    const ytSearchUrl = `https://music.youtube.com/search?q=${encodeURIComponent(
                      `${track.title} ${track.artist}`
                    )}`;
                    const ytWatchUrl = rec?.videoId
                      ? `https://music.youtube.com/watch?v=${rec.videoId}`
                      : null;

                    return (
                      <div
                        key={track.spotify_uri + '-' + track.index}
                        className={`track-row status-${status}`}
                      >
                        <span className="track-num">{track.index + 1}</span>
                        <div className="track-main">
                          <span className="track-title">
                            {track.title}{' '}
                            <span className="track-artist-inline">— {track.artist}</span>
                          </span>
                          <span className="track-artist">
                            {(status === 'added' || status === 'low_confidence') &&
                              rec?.matchedTitle && (
                                <>
                                  Guardada en YouTube Music como{' '}
                                  <strong>{rec.matchedTitle}</strong>
                                  {rec.matchedArtist ? ` · ${rec.matchedArtist}` : ''}
                                </>
                              )}
                            {status === 'failed' &&
                              'No se encontró coincidencia disponible en YouTube Music'}
                            {(status === 'pending' || status === 'searching') &&
                              'En espera para la siguiente sesión'}
                          </span>
                        </div>

                        <div className="track-row-actions">
                          {ytWatchUrl && (
                            <a
                              href={ytWatchUrl}
                              target="_blank"
                              rel="noreferrer"
                              className="track-action-link"
                            >
                              Escuchar ↗
                            </a>
                          )}
                          {status === 'failed' && (
                            <a
                              href={ytSearchUrl}
                              target="_blank"
                              rel="noreferrer"
                              className="track-action-link"
                            >
                              Buscar ↗
                            </a>
                          )}
                          <span className={`status-pill pill-${status}`}>
                            {status === 'added' && '✓ Añadida'}
                            {status === 'low_confidence' && '✓ Versión similar'}
                            {status === 'failed' && 'No añadida'}
                            {(status === 'pending' || status === 'searching') && 'Pendiente'}
                          </span>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            </div>

            <div className="footer-actions">
              {stats.processed < stats.total && (
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={() => dispatch({ type: 'SET_STEP', step: 'migrate' })}
                >
                  ← Volver a la transferencia
                </button>
              )}
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => dispatch({ type: 'RESET_ALL' })}
              >
                Pasar otra playlist
              </button>
            </div>
          </section>
        )}
      </main>

      <CookieHelpModal isOpen={isCookieModalOpen} onClose={() => setIsCookieModalOpen(false)} />
    </div>
  );
};
