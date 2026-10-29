import React from 'react';

interface SkeletonLoaderProps {
  loaded: number;
  total: number;
  playlistName?: string;
}

export const SkeletonLoader: React.FC<SkeletonLoaderProps> = ({
  loaded,
  total,
  playlistName,
}) => {
  const pct = total > 0 ? Math.min(100, Math.round((loaded / total) * 100)) : 20;

  return (
    <div className="skeleton-container" aria-busy="true" aria-live="polite">
      <div className="skeleton-header">
        <div className="skeleton-cover shimmer" />
        <div className="skeleton-meta">
          <div className="skeleton-line skeleton-title shimmer" />
          <div className="skeleton-line skeleton-subtitle shimmer" />
          <div className="extraction-progress-label">
            {playlistName ? `Leyendo "${playlistName}": ` : 'Descargando canciones: '}
            <strong>
              {loaded.toLocaleString()}
              {total > 0 ? ` de ${total.toLocaleString()}` : ''} canciones
            </strong>{' '}
            ({pct}%)
          </div>
          <div className="progress-bar-track">
            <div
              className="progress-bar-fill"
              style={{ transform: `scaleX(${Math.max(0.04, pct / 100)})` }}
            />
          </div>
        </div>
      </div>

      <div className="skeleton-list">
        {[0, 1, 2, 3, 4].map((idx) => (
          <div
            key={idx}
            className="skeleton-row shimmer"
            style={{ animationDelay: `${idx * 45}ms` }}
          />
        ))}
      </div>
    </div>
  );
};
