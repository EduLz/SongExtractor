import React, { useEffect } from 'react';

interface CookieHelpModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const CookieHelpModal: React.FC<CookieHelpModalProps> = ({ isOpen, onClose }) => {
  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div className="modal-backdrop" onClick={onClose} role="dialog" aria-modal="true">
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div>
            <span className="badge badge-amber">Guía rápida en 1 minuto</span>
            <h3>Cómo conectar tu cuenta de YouTube Music</h3>
          </div>
          <button type="button" className="btn-icon" onClick={onClose} aria-label="Cerrar guía">
            ✕
          </button>
        </div>

        <div className="modal-body">
          <p className="modal-intro">
            Para crear la playlist en tu cuenta de YouTube Music sin guardar tus datos en ningún
            servidor, sigue estos sencillos pasos desde tu ordenador:
          </p>

          <ol className="step-list">
            <li>
              Abre una <strong>ventana de incógnito</strong> en tu navegador e inicia sesión en{' '}
              <a href="https://music.youtube.com" target="_blank" rel="noreferrer">
                music.youtube.com
              </a>
              .
            </li>
            <li>
              Pulsa la tecla <kbd>F12</kbd> y entra en la pestaña <strong>Red</strong> (o{' '}
              <strong>Network</strong>).
            </li>
            <li>
              Escribe <code>browse</code> en el buscador de esa pestaña y haz clic en{' '}
              <em>Biblioteca</em> dentro de YouTube Music.
            </li>
            <li>
              Haz clic en el primer resultado llamado <code>browse</code>, baja hasta la sección{' '}
              <strong>Request Headers</strong> y copia todo el texto que aparece junto a{' '}
              <strong>Cookie</strong>.
            </li>
            <li>Pega ese texto en el recuadro de esta página y pulsa comenzar.</li>
          </ol>

          <div className="alert-box alert-warning">
            <strong>Importante si usas varias cuentas:</strong> Si quieres pasar una playlist a otra
            cuenta distinta, <strong>cierra todas las ventanas de incógnito abiertas</strong> y abre
            una nueva desde cero. Si inicias sesión con dos cuentas en la misma ventana, Google
            guarda las playlists en la primera cuenta que abriste.
          </div>
        </div>

        <div className="modal-footer">
          <button type="button" className="btn btn-primary" onClick={onClose}>
            Entendido
          </button>
        </div>
      </div>
    </div>
  );
};
