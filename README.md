# Escuchas

MVP para monitorear transmisiones en vivo y detectar la aparicion de spots publicitarios cargados en audio o video.

## Alcance del MVP

- Carga de spots en formatos de audio o video.
- Extraccion y normalizacion del audio del spot.
- Generacion de una firma base del spot para comparaciones futuras.
- Registro de streams a monitorear.
- Monitoreo en ventanas solapadas con opcion de correr jobs en background.

## Stack

- FastAPI
- SQLModel + SQLite
- Librosa para analisis de audio
- FFmpeg para extraer audio desde archivos de video

## Requisitos

- Python 3.11+
- FFmpeg en el `PATH` si queres aceptar videos o normalizar algunos formatos de audio
- `yt-dlp` para resolver enlaces reales de YouTube antes de monitorearlos

## Instalacion

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Ejecutar

La API queda disponible en:

- `http://127.0.0.1:8000`
- Swagger: `http://127.0.0.1:8000/docs`

## Flujo principal

1. Crear una campana.
2. Cargar un spot en audio o video.
3. El backend extrae audio, lo normaliza a WAV mono 16kHz y calcula una firma preliminar.
4. Registrar uno o mas streams en vivo.
5. Ejecutar un monitoreo manual sobre un stream registrado.
6. Revisar coincidencias y detecciones persistidas.

## Endpoints principales

- `GET /health`
- `POST /campaigns`
- `GET /campaigns`
- `POST /ads/upload`
- `GET /ads`
- `POST /streams`
- `GET /streams`
- `POST /monitor/run`
- `POST /monitor/jobs`
- `GET /monitor/jobs`
- `GET /monitor/jobs/{job_id}`
- `POST /monitor/jobs/{job_id}/cancel`
- `GET /detections`

## Probar monitoreo en background

1. Crear una campana y subir al menos un spot con `processing_status = ready`.
2. Registrar un stream en `POST /streams`.
   El `source_url` puede ser una URL de stream, una URL de YouTube o tambien una ruta local a un archivo reproducible por FFmpeg, por ejemplo `C:\audio\programa.mp3`.
3. Ejecutar `POST /monitor/jobs` con un body como este:

```json
{
  "stream_id": 1,
  "window_seconds": 45,
  "window_step_seconds": 15,
  "iterations": 10,
  "similarity_threshold": 0.03,
  "cooldown_seconds": 60,
  "keep_evidence": true
}
```

4. Guardar el `job_id` de la respuesta.
5. Consultar `GET /monitor/jobs/{job_id}` para ver avance, resultados parciales y errores.
6. Revisar `GET /detections`.

Para monitorear 40 minutos de corrido, una opcion simple es:

```json
{
  "stream_id": 1,
  "window_seconds": 45,
  "window_step_seconds": 15,
  "iterations": 158,
  "similarity_threshold": 0.03,
  "cooldown_seconds": 60,
  "keep_evidence": true
}
```

Eso analiza una ventana de 45 segundos cada 15 segundos sobre el vivo.
La duracion total aproximada es `45 + (158 - 1) * 15 = 2400` segundos, es decir 40 minutos.

## YouTube

El endpoint `POST /monitor/run` ahora puede recibir un stream cuyo `source_url` sea un enlace real de YouTube. Internamente se usa `yt-dlp` para resolver la URL multimedia y luego `ffmpeg` captura la ventana de audio.

Si acabas de actualizar el proyecto, instala la nueva dependencia:

```bash
pip install -r requirements.txt
```

## Siguiente paso tecnico

El backend ya permite hacer monitoreo en background con progreso y ventanas solapadas. El siguiente paso es sumar un servicio continuo mas persistente que:

- abra el stream
- sobreviva reinicios del servidor
- compare contra la biblioteca de spots con un matcher mas robusto
- cree eventos de deteccion y conteo
