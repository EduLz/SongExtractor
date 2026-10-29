# SongExtractor — Pasa tus playlists públicas de Spotify a YouTube Music

Aplicación web (**Frontend React + Vite + TypeScript** y **Backend Serverless Python/FastAPI sin estado**) para transferir playlists públicas de **Spotify** a **YouTube Music** sin necesidad de tener cuenta de Spotify Premium ni configurar credenciales de desarrollador.

🔗 ** Producción en vivo:** [https://song-extractor.vercel.app](https://song-extractor.vercel.app)

---

> [!WARNING]
> **Aviso de Uso y Responsabilidad**
>
> Este proyecto utiliza `spotifyscraper==3.9.2` para leer los metadatos públicos del reproductor web de Spotify y `ytmusicapi` para interactuar con YouTube Music. **SongExtractor se distribuye exclusivamente con fines personales y educativos** bajo la Licencia MIT. El usuario final asume toda la responsabilidad derivada de su uso.

---

## Características Principales

- **Sin cuenta ni credenciales de Spotify**: Funciona pegando directamente el enlace de cualquier playlist pública de Spotify (`https://open.spotify.com/playlist/...`).
- **100 % sin estado (Privacidad Total)**: No utiliza bases de datos ni guarda cookies, sesiones ni listas en el servidor. Todo el avance vive en tu navegador (`sessionStorage`) y puedes descargarlo en un archivo `.json` si deseas continuar otro día.
- **Soporte para playlists grandes (+300 o +4.000 canciones)**:
  - Extracción paginada en bloques de 100 canciones.
  - Búsqueda de catálogo desacoplada de la sesión del usuario e inserción por lotes (*batching*) para evitar caducidad prematura de sesión (`HTTP 401`).
  - Pausa diaria automática recomendada cada **190 canciones** para respetar la cuota diaria de la API de YouTube (10.000 unidades/día), con exportación y reanudación en un clic.
- **Resumen final interactivo**: Vista detallada al finalizar con filtros por canciones añadidas, versiones similares y canciones no disponibles, con enlaces directos a YouTube Music.

---

## Cómo usar la aplicación

1. **Elige tu playlist de Spotify**: Abre cualquier playlist pública en Spotify, pulsa **Compartir → Copiar enlace de la playlist** y pégalo en el Paso 1.
2. **Revisa las canciones**: Visualiza todas las pistas detectadas y filtra por título o artista si lo deseas.
3. **Conecta tu cuenta de YouTube Music**:
   - Abre una **ventana de incógnito** nueva e inicia sesión en [music.youtube.com](https://music.youtube.com).
   - Pulsa `F12` → pestaña **Red (Network)** → filtra por `browse` y haz clic en *Biblioteca*.
   - Abre la petición `browse` y copia el valor de **`Cookie`** dentro de *Request Headers*.
   - Pégalo en el Paso 3 y comienza la transferencia.
   - *(Si deseas cambiar a otra cuenta de Google, cierra primero la ventana de incógnito anterior y abre una nueva desde cero).*

---

## Estructura del Repositorio

```text
SongExtractor/
├── api/                          # Backend Serverless Python / FastAPI (Sin Estado)
│   ├── spotify/
│   │   └── playlist.py           # GET /api/spotify/playlist/{playlist_id} (paginación con spotifyscraper)
│   ├── ytmusic/
│   │   ├── search.py             # POST /api/ytmusic/search (búsqueda en catálogo público)
│   │   └── add.py                # POST /api/ytmusic/add (creación de playlist e inserción por lotes)
│   ├── _shared.py                # Validación de URLs, cliente YTMusic en memoria y sanitización
│   └── index.py                  # Entrada FastAPI unificada para desarrollo local
├── frontend/                     # Interfaz Web (React 18 + TypeScript + Vite)
│   ├── src/
│   │   ├── components/           # StepIndicator, CookieHelpModal, SkeletonLoader
│   │   ├── hooks/                # useMigrationFlow (estado, lotes, cambio de cuenta y exportación)
│   │   ├── lib/                  # api.ts, types.ts
│   │   ├── pages/                # MigrationWizard (asistente en 5 pasos)
│   │   └── styles.css            # Sistema de diseño oscuro con animaciones aceleradas por GPU
│   ├── package.json
│   └── vite.config.ts
├── requirements.txt              # Dependencias del backend Python para Vercel y entorno local
├── vercel.json                   # Configuración de rutas y compilación para Vercel
├── LICENSE                       # Licencia MIT
└── README.md
```

---

## Desarrollo Local

```bash
# 1. Instalar dependencias de Python e iniciar el backend en http://localhost:8000
pip install -r requirements.txt
uvicorn api.index:app --reload --port 8000

# 2. En otra terminal, iniciar el frontend en http://localhost:5173
cd frontend
npm install
npm run dev
```

---

## Licencia

Distribuido bajo la **Licencia MIT**. Consulta el archivo [LICENSE](LICENSE) para más información.
