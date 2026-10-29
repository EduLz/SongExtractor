# SongExtractor — Migración "Local-First" de Playlists de Spotify a YouTube Music (Sin Spotify Premium)

Aplicación web completa (**Frontend React + Vite + TypeScript** y **Backend Serverless Python/FastAPI sin estado**) y utilidades CLI para transferir playlists públicas de **Spotify** a **YouTube Music** sin necesidad de contar con una suscripción de Spotify Premium ni configurar credenciales de desarrollador de Spotify.

---

> [!WARNING]
> **Aviso de Cumplimiento, Términos de Servicio y Responsabilidad**
>
> Este proyecto utiliza un cliente no oficial (`spotifyscraper==3.9.2`) que consulta el endpoint interno del reproductor web de Spotify para leer los metadatos públicos de las playlists. El uso de clientes no oficiales o automatizados puede contravenir los [Términos de Servicio de Spotify](https://www.spotify.com/legal/end-user-agreement/) y de YouTube.
>
> **SongExtractor se desarrolla y distribuye exclusivamente con fines personales y educativos** bajo la Licencia MIT. No implementa técnicas agresivas de extracción (sin paralelismo masivo ni evasión de límites). El usuario final asume toda la responsabilidad derivada del uso de esta herramienta.

---

## Tabla de Contenidos

1. [Arquitectura "Local-First" (Sin Credenciales de Spotify)](#1-arquitectura-local-first-sin-credenciales-de-spotify)
2. [Requisitos y Configuración del Usuario](#2-requisitos-y-configuración-del-usuario)
   - [2.1. Spotify (Cuenta Gratuita o Solo Enlace Público)](#21-spotify-cuenta-gratuita-o-solo-enlace-público)
   - [2.2. YouTube Music Premium (Autenticación por Navegador)](#22-youtube-music-premium-autenticación-por-navegador)
3. [Limitación de Cuota Diaria de YouTube y Reanudación Multi-Sesión](#3-limitación-de-cuota-diaria-de-youtube-y-reanudación-multi-sesión)
4. [Diseño de Interfaz y Skills de Emil Kowalski](#4-diseño-de-interfaz-y-skills-de-emil-kowalski)
5. [Estrategia de Despliegue en Vercel y Servicios Gratuitos](#5-estrategia-de-despliegue-en-vercel-y-servicios-gratuitos)
6. [Estructura del Proyecto](#6-estructura-del-proyecto)
7. [Ejecución Local (Web y CLI)](#7-ejecución-local-web-y-cli)
8. [Licencia](#8-licencia)

---

## 1. Arquitectura "Local-First" (Sin Credenciales de Spotify)

El sistema opera con **cero persistencia en el servidor** (sin bases de datos, sin almacenamiento en disco de sesiones y sin variables secretas en el backend):

1. **Entrada Directa de URL**: El usuario pega el enlace de cualquier playlist pública de Spotify (`https://open.spotify.com/playlist/{id}`) directamente en el frontend.
2. **Lectura Paginada Sin Estado (`/api/spotify/playlist/{playlist_id}?offset=0&limit=100`)**:
   - El frontend solicita las canciones en bloques de 100 pistas al backend.
   - El backend valida que el enlace corresponda estrictamente a una playlist de Spotify (rechazando enlaces de álbumes, artistas o pistas individuales) y utiliza `spotifyscraper==3.9.2` para leer la página solicitada en ~1.5 segundos, respetando holgadamente el límite de 10 segundos por invocación de Vercel Hobby.
3. **Búsqueda e Inserción Efímera en YouTube Music (`/api/ytmusic/search` y `/api/ytmusic/add`)**:
   - El usuario pega su cookie temporal de sesión de YouTube Music en el navegador.
   - En cada canción, el frontend envía la cookie al proxy serverless; el backend inicializa `ytmusicapi` **100% en memoria RAM**, ejecuta la operación y descarta la cookie inmediatamente al terminar la petición.
4. **Progreso en el Navegador (`sessionStorage`) + Exportación/Importación Local**:
   - El estado de avance (`upload_state`) se actualiza tras cada canción en el `sessionStorage` del navegador.
   - Si el usuario desea cerrar el navegador y continuar al día siguiente, puede pulsar **"Guardar progreso"** para descargar un archivo `.json` en su propio disco y volver a cargarlo con **"Cargar progreso guardado"** sin que ningún dato pase por el servidor.

---

## 2. Requisitos y Configuración del Usuario

### 2.1. Spotify (Cuenta Gratuita o Solo Enlace Público)

- **No se requiere Spotify Premium** ni registro de aplicaciones de desarrollador.
- Tu cuenta de Spotify puede ser totalmente gratuita (o incluso no necesitas iniciar sesión): basta con abrir cualquier playlist pública en Spotify y seleccionar **Compartir → Copiar enlace de la playlist**.

### 2.2. YouTube Music Premium (Autenticación por Navegador)

El usuario dispone de una cuenta con **YouTube Music Premium** y se autentica mediante la cookie de sesión de su navegador (`browser.json` o cabecera `Cookie`):

1. Abre una **ventana de incógnito / privada** en tu navegador e inicia sesión en [https://music.youtube.com](https://music.youtube.com).
2. Pulsa `F12` para abrir las **Herramientas de Desarrollador** y selecciona la pestaña **Network (Red)**.
3. Escribe `browse` en el filtro y haz clic en cualquier sección de YouTube Music (*Biblioteca* o *Explorar*).
4. Haz clic en una petición `browse` (`POST`, estado `200`), baja a **Request Headers** y copia el valor completo de la cabecera **`Cookie`** (debe contener `__Secure-3PAPISID`).
5. Pega ese valor en el Paso 3 de la aplicación web (o guárdalo en `browser.json` para el script CLI).
6. **Seguridad**: Cuando termines la migración, cierra sesión en la ventana de incógnito para revocar inmediatamente la validez de la cookie.

---

## 3. Limitación de Cuota Diaria de YouTube y Reanudación Multi-Sesión

> [!IMPORTANT]
> **YouTube Music Premium NO aumenta la cuota diaria de la API de YouTube (10.000 unidades/día).**

- Crear una playlist consume **50 unidades** y añadir cada canción consume **50 unidades**.
- Para una playlist grande de **4.000 canciones**, el coste total estimado es de **200.050 unidades**, lo que equivale a unas **190 canciones por día** (~21 sesiones diarias con la cuota gratuita estándar).
- **Cómo gestionarlo en SongExtractor**:
  1. Activa la casilla **"Pausa diaria automática (190 canciones)"** incluida por defecto en la interfaz.
  2. Como el progreso reside en el `sessionStorage` de tu navegador y se borra si cierras la pestaña, antes de cerrar el navegador haz clic en **"Guardar progreso"** para descargar tu archivo `.json` local.
  3. Al día siguiente, abre la aplicación, haz clic en **"Cargar progreso guardado"** arriba a la derecha, selecciona tu archivo `.json` y pulsa **"Continuar"** para seguir exactamente desde la canción en que te quedaste sin duplicar la playlist.
  4. Si deseas solicitar un aumento de cuota a Google, puedes consultar la [Calculadora de Cuotas de YouTube](https://developers.google.com/youtube/v3/determine_quota_cost) y el [Formulario de Aumento de Cuota de YouTube API](https://support.google.com/youtube/contact/yt_api_form).

---

## 4. Diseño de Interfaz y Skills de Emil Kowalski

El frontend se ha construido aplicando las skills de **Emil Kowalski** y **Vercel Labs**, priorizando una interfaz limpia, legible y libre de jerga técnica para el usuario final:

```bash
npx skills@latest add emilkowalski/skills
npx skills@latest add vercel-labs/agent-skills
```

| Before | After | Why |
| :--- | :--- | :--- |
| `transition: all 300ms` | `transition: transform 140ms var(--ease-out), background-color 180ms ease` | Especificar propiedades exactas evita recalcular layout y mantiene 60fps en GPU |
| `transform: scale(0)` en modales y tarjetas | `transform: scale(0.95); opacity: 0` con `@starting-style` | Nada en el mundo físico aparece desde escala cero; `0.95` aporta naturalidad |
| `ease-in` en elementos de UI | `--ease-out: cubic-bezier(0.23, 1, 0.32, 1)` y `--ease-drawer: cubic-bezier(0.32, 0.72, 0, 1)` | `ease-in` retrasa el inicio del movimiento; `ease-out` da respuesta instantánea |
| Botones sin respuesta al clic | `transform: scale(0.97)` en `:active` | Feedback táctil inmediato que confirma la acción del usuario |
| Animar `width` en barras de progreso | `transform: scaleX(...)` con `transform-origin: left center` | `scaleX` corre en el compositor GPU sin disparar *layout* ni *paint* |
| `:hover` en pantallas táctiles | Gate `@media (hover: hover) and (pointer: fine)` + `prefers-reduced-motion` | Evita hovers falsos en móviles y respeta preferencias de accesibilidad |

---

## 5. Estrategia de Despliegue en Vercel y Servicios Gratuitos

El proyecto no requiere configurar variables de entorno secretas en el servidor.

| Paso | Quién lo hace | Qué hace |
| :--- | :--- | :--- |
| **1** | **Usuario** | Crea una cuenta gratuita en Vercel (Plan Hobby, sin tarjeta de crédito). |
| **2** | **Agente** | Instala las skills (`npx skills@latest add vercel-labs/agent-skills`), construye el proyecto y despliega con `VERCEL_TOKEN` o mediante el flujo sin autenticación (`npx vercel@latest deploy --temporary -y`). |
| **3** | **Usuario** | Si se usó el flujo sin autenticación (*claimable*), hace clic en el enlace para reclamar el proyecto en su cuenta de Vercel. |
| **4** | **Usuario** | Abre la URL desplegada, pega el enlace de su playlist pública de Spotify y la cookie de YouTube Music para iniciar la transferencia. |

### Límites del Plan Gratuito de Vercel (Hobby)
- **Tiempo máximo por invocación serverless**: **10 segundos** (cada llamada a `/api/spotify/playlist/{id}?offset=...&limit=100` tarda ~1.5 s al estar paginada de 100 en 100).
- **Transferencia**: 100 GB/mes.
- **Invocaciones**: Hasta 100.000–1.000.000 invocaciones serverless/mes según el plan Hobby vigente.

---

## 6. Estructura del Proyecto

```text
SongExtractor/
├── frontend/                     # Aplicación Web React + Vite + TypeScript (UI simplificada)
│   ├── src/
│   │   ├── components/           # StepIndicator, CookieHelpModal, SkeletonLoader
│   │   ├── pages/                # MigrationWizard (flujo amigable en 5 pasos)
│   │   ├── hooks/                # useMigrationFlow (paginación, sessionStorage y export/import)
│   │   └── lib/                  # api.ts, types.ts
│   ├── package.json
│   └── vite.config.ts
├── api/                          # Funciones Serverless Python / FastAPI (Sin Estado)
│   ├── spotify/
│   │   └── playlist.py           # GET /api/spotify/playlist/{playlist_id}?offset=0&limit=100 (spotifyscraper)
│   ├── ytmusic/
│   │   ├── search.py             # POST /api/ytmusic/search (búsqueda en memoria con ytmusicapi)
│   │   └── add.py                # POST /api/ytmusic/add (creación de playlist e inserción)
│   ├── _shared.py                # Validación de URLs, scraper paginado y sanitización de errores
│   ├── index.py                  # App FastAPI unificada para desarrollo local
│   └── requirements.txt          # Incluye spotifyscraper==3.9.2, fastapi, uvicorn, ytmusicapi, httpx
├── fetch_spotify_playlist.py     # Script CLI 1: Descarga playlist pública de Spotify sin OAuth
├── upload_ytmusic.py             # Script CLI 2: Sube playlist_data.json a YouTube Music
├── vercel.json                   # Configuración de rutas y build para Vercel
├── requirements.txt              # Dependencias de Python (con spotifyscraper==3.9.2 fijado)
├── .env.example                  # Configuración opcional no sensible (LOG_LEVEL)
├── upload_state.example.json     # Ejemplo de estructura del archivo de estado
└── README.md
```

---

## 7. Ejecución Local (Web y CLI)

### Modo Web Local

```bash
# 1. Instalar dependencias de Python e iniciar el backend FastAPI en el puerto 8000
pip install -r requirements.txt
uvicorn api.index:app --reload --port 8000

# 2. En otra terminal, iniciar el frontend en el puerto 5173
cd frontend
npm install
npm run dev
```

### Modo Línea de Comandos (CLI)

```bash
# Paso 1: Descargar una playlist pública de Spotify (sin cuenta ni credenciales)
python fetch_spotify_playlist.py "https://open.spotify.com/playlist/4HU33McSZ93lPnmTy0LyhK"

# Paso 2: Subir las canciones a YouTube Music respetando el límite diario
python upload_ytmusic.py --respect-quota-limit
```

---

## 8. Licencia

Distribuido bajo la **Licencia MIT**. Consulta el archivo [LICENSE](file:///c:/Users/edulz/Documents/SongExtractor/LICENSE) para más información.
