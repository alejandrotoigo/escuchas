# Deploy En Railway

Esta app ahora puede correr en Railway de dos formas:

- modo simple: un unico servicio web que tambien ejecuta jobs
- modo recomendado: un servicio web y un servicio worker separados

## Requisitos de arquitectura

- PostgreSQL provisionado en Railway o externo
- un volumen persistente compartido para `storage/`
- FFmpeg dentro de la imagen

### Recomendado para produccion

- 1 servicio `web`
- 1 servicio `worker`
- la web con `JOB_RUNNER_ENABLED=false`
- el worker con `JOB_RUNNER_ENABLED=true`

La app ya esta preparada para esto:

- usa `DATABASE_URL` desde variables de entorno
- normaliza URLs de PostgreSQL para SQLAlchemy + psycopg
- corre migraciones automaticamente al iniciar
- sirve un frontend simple en `/`
- puede proteger la UI con login por sesion
- reanuda jobs pendientes al reiniciar si `JOB_RUNNER_ENABLED=true`
- el worker dedicado hace polling de jobs `queued`

## Archivos usados por Railway

- `Dockerfile`
- `.dockerignore`
- `.env.example`
- `railway.json`

## Variables recomendadas

```env
PROJECT_NAME=Escuchas
DATABASE_URL=postgresql://...
POSTGRES_ADMIN_DATABASE=postgres
STORAGE_DIR=/data/storage
JOB_RUNNER_ENABLED=true
JOB_RUNNER_POLL_SECONDS=5
UI_AUTH_ENABLED=true
UI_USERNAME=admin
UI_PASSWORD=cambiar-esto
SESSION_SECRET=cambiar-esto-por-un-valor-largo
SESSION_HTTPS_ONLY=true
```

## Variables exactas sugeridas para produccion

### Obligatoria

- `DATABASE_URL`

La crea Railway si agregas PostgreSQL al proyecto.

### Recomendadas

```env
PROJECT_NAME=Escuchas
POSTGRES_ADMIN_DATABASE=postgres
STORAGE_DIR=/data/storage
JOB_RUNNER_POLL_SECONDS=5
UI_AUTH_ENABLED=true
UI_USERNAME=admin
UI_PASSWORD=cambiar-esto
SESSION_SECRET=cambiar-esto-por-un-valor-largo
SESSION_HTTPS_ONLY=true
```

### Politica sugerida

- un servicio web con `JOB_RUNNER_ENABLED=false`
- un servicio worker con `JOB_RUNNER_ENABLED=true`
- volumen persistente montado en `/data` para ambos servicios
- healthcheck sobre `/health` en la web

Notas:

- `DATABASE_URL` puede venir del plugin de PostgreSQL de Railway. La app la convierte internamente a `postgresql+psycopg://...`.
- `STORAGE_DIR` debe apuntar a un volumen persistente montado por Railway.
- `UI_AUTH_ENABLED=true` protege `/` y `/ui/*` con login por cookie de sesion.
- la API JSON sigue publica; si queres cerrarla tambien, ponela detras de la capa de acceso de Railway o de un proxy.

## Pasos de despliegue

### 1. Crear el proyecto

Crear un proyecto nuevo en Railway y conectar este repo.

### 2. Crear el servicio web

- usar este repo
- build: `Dockerfile`
- start command web:

```bash
uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

- variables exactas del servicio web:

```env
PROJECT_NAME=Escuchas
DATABASE_URL=${{Postgres.DATABASE_URL}}
POSTGRES_ADMIN_DATABASE=postgres
STORAGE_DIR=/data/storage
JOB_RUNNER_ENABLED=false
JOB_RUNNER_POLL_SECONDS=5
UI_AUTH_ENABLED=true
UI_USERNAME=admin
UI_PASSWORD=cambiar-esto
SESSION_SECRET=cambiar-esto-por-un-valor-largo
SESSION_HTTPS_ONLY=true
```

### 3. Provisionar PostgreSQL

Agregar un servicio PostgreSQL en Railway y exponer su `DATABASE_URL` al servicio web.

### 4. Crear volumen persistente

Montar un volumen y compartirlo entre web y worker usando una ruta, por ejemplo:

- `/data`

Despues configurar:

```env
STORAGE_DIR=/data/storage
```

### 5. Crear el servicio worker

Duplicar el servicio web o crear un segundo servicio desde el mismo repo y usar este start command:

```bash
python -m app.worker
```

Variables exactas del worker:

```env
PROJECT_NAME=Escuchas Worker
DATABASE_URL=${{Postgres.DATABASE_URL}}
POSTGRES_ADMIN_DATABASE=postgres
STORAGE_DIR=/data/storage
JOB_RUNNER_ENABLED=true
JOB_RUNNER_POLL_SECONDS=5
UI_AUTH_ENABLED=false
SESSION_HTTPS_ONLY=true
```

### 6. Escala recomendada

- web: 1 replica
- worker: 1 replica

Aunque el backend usa un advisory lock de PostgreSQL para evitar dobles ejecuciones del mismo job, el modelo operativo recomendado sigue siendo una sola replica worker activa.

### 7. Deploy

Railway va a construir la imagen usando el `Dockerfile` para ambos servicios.

## Verificaciones despues del deploy

### Health

Abrir:

- `/health`

Esperado:

- `status = ok`
- `ffmpeg_available = true`

### Frontend

Abrir:

- `/`

La pagina principal permite:

1. crear una campana
2. subir varios spots
3. crear el stream
4. arrancar un job con `run_forever=true`
5. ver el listado de jobs
6. pausarlos
7. ver detecciones recientes y abrir la evidencia de audio
8. entrar con login por sesion si `UI_AUTH_ENABLED=true`

### Storage

Verificar que el volumen recibe archivos en:

- `ads`
- `normalized`
- `monitoring`
- `evidence`

## Consideraciones sobre jobs

- si Railway reinicia el servicio, la app intenta reanudar jobs pendientes al arrancar
- si pausas un job desde la UI, no se reanuda automaticamente
- el worker dedicado tambien toma jobs nuevos encolados mientras esta corriendo
- si Railway escala mas de una replica, el advisory lock de PostgreSQL ayuda a no duplicar un mismo job, pero el despliegue recomendado sigue siendo una sola replica worker

## Limites actuales

- la autenticacion agregada es minima y solo cubre la UI server-rendered
- el frontend es simple y server-rendered
- el procesamiento sigue usando storage local persistente, no object storage
- la API JSON sigue sin auth propia
