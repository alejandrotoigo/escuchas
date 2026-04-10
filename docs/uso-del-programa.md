# Uso Del Programa

## Objetivo

Este programa permite:

1. cargar spots publicitarios en audio o video
2. registrar transmisiones a monitorear
3. analizar un stream en vivo
4. detectar si un spot cargado aparece dentro del stream
5. guardar evidencia y registrar detecciones

## Requisitos Previos

Antes de usar el sistema, tenes que tener instalado:

1. Python 3.11+
2. FFmpeg en el `PATH`
3. dependencias del proyecto instaladas con:

```powershell
pip install -r requirements.txt
```

## Paso 1: Levantar La API

Abrir PowerShell en la carpeta del proyecto y ejecutar:

```powershell
cd C:\xampp\htdocs\escuchas
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload
```

La API queda disponible en:

- `http://127.0.0.1:8000`
- `http://127.0.0.1:8000/docs`

## Paso 2: Verificar Que La API Este Viva

En el navegador abrir:

- `http://127.0.0.1:8000/docs`

Luego probar:

- `GET /health`

Si responde con `status = ok`, la API esta funcionando.

## Paso 3: Crear Una Campana

En Swagger usar:

- `POST /campaigns`

Body de ejemplo:

```json
{
  "name": "Campana Abril",
  "brand": "Mi Marca",
  "notes": "Prueba de monitoreo"
}
```

Guardar el `id` de la campana.

## Paso 4: Cargar Un Spot

En Swagger usar:

- `POST /ads/upload`

Completar:

1. `campaign_id`: id de la campana
2. `title`: nombre del spot
3. `file`: archivo de audio o video

Luego revisar:

- `GET /ads`

El spot debe quedar con:

- `processing_status = "ready"`

Si el spot no queda en `ready`, no se puede usar en el monitoreo.

## Paso 5: Registrar Un Stream

En Swagger usar:

- `POST /streams`

Body de ejemplo:

```json
{
  "name": "TN Prueba",
  "source_url": "https://www.youtube.com/watch?v=cb12KmMMDJA",
  "description": "Canal de prueba",
  "is_active": true
}
```

Luego revisar:

- `GET /streams`

Tomar nota del `id` del stream.

## Paso 6: Iniciar Un Monitoreo Corto

Para probar que todo funciona, conviene arrancar con un job corto.

En Swagger usar:

- `POST /monitor/jobs`

Body de ejemplo:

```json
{
  "stream_id": 1,
  "window_seconds": 45,
  "window_step_seconds": 15,
  "iterations": 4,
  "similarity_threshold": 0.03,
  "cooldown_seconds": 60,
  "keep_evidence": true
}
```

La respuesta va a devolver:

- `job_id`
- `status`
- datos del stream

Guardar el `job_id`.

## Paso 7: Consultar El Estado Del Job

En Swagger usar:

- `GET /monitor/jobs/{job_id}`

Pegar el `job_id` recibido antes.

Campos importantes:

1. `status`
2. `completed_iterations`
3. `progress_percent`
4. `results`
5. `error`

Estados esperables:

- `queued`
- `running`
- `completed`
- `failed`
- `cancelled`

## Paso 8: Lanzar Un Monitoreo Largo

Cuando la prueba corta funcione, usar un job largo.

En Swagger usar:

- `POST /monitor/jobs`

Body sugerido para aproximadamente 40 minutos:

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

Interpretacion:

1. `window_seconds = 45`
   El sistema analiza una ventana de 45 segundos.

2. `window_step_seconds = 15`
   Cada 15 segundos corre una nueva comparacion.
   Esto genera ventanas solapadas y reduce el riesgo de perder un spot que caiga entre cortes.

3. `iterations = 158`
   Aproxima unos 40 minutos de monitoreo.

## Paso 9: Ver Resultados

Cuando el job termina, revisar:

1. `GET /monitor/jobs/{job_id}`
2. `GET /detections`
3. carpeta de evidencia

Ubicacion de evidencias:

- `C:\xampp\htdocs\escuchas\storage\evidence`

Si hubo detecciones, tambien se pueden revisar en:

- `GET /detections`

Campos importantes en cada deteccion:

1. `confidence`
2. `detected_at`
3. `offset_seconds`
4. `evidence_path`

## Paso 10: Cancelar Un Job

Si hace falta cortar un monitoreo en curso, usar:

- `POST /monitor/jobs/{job_id}/cancel`

## Como Interpretar Los Resultados

### Caso 1: No Hay Detecciones

Si el job termina con:

- `total_detections_created = 0`
- `matches = []`
- carpeta `storage/evidence` vacia

entonces el sistema no encontro el spot en las ventanas analizadas.

### Caso 2: Hay Detecciones

Si aparecen archivos en `storage/evidence` o registros en `GET /detections`, entonces:

1. el sistema encontro una coincidencia
2. guardo una evidencia de audio
3. registro la deteccion en base de datos

En ese caso conviene escuchar la evidencia y confirmar si el spot realmente salio al aire.

### Caso 3: El Job Falla

Si el job queda con:

- `status = failed`

entonces revisar:

1. el campo `error` en `GET /monitor/jobs/{job_id}`
2. la consola donde corre `uvicorn`

## Flujo Recomendado De Uso

El orden correcto para usar el programa es:

1. levantar la API
2. crear campana
3. subir spot
4. revisar que el spot quede en `ready`
5. registrar stream
6. lanzar job corto
7. confirmar que el job termina bien
8. lanzar job largo
9. revisar detecciones y evidencias

## Endpoints Mas Importantes

- `GET /health`
- `POST /campaigns`
- `GET /campaigns`
- `POST /ads/upload`
- `GET /ads`
- `POST /streams`
- `GET /streams`
- `POST /monitor/jobs`
- `GET /monitor/jobs`
- `GET /monitor/jobs/{job_id}`
- `POST /monitor/jobs/{job_id}/cancel`
- `GET /detections`

## Notas Practicas

1. Para monitoreos largos, usar siempre `POST /monitor/jobs` y no `POST /monitor/run`.
2. `POST /monitor/run` queda solo para pruebas cortas o debugging.
3. Si el navegador se cierra, el job en background sigue existiendo mientras la API siga viva.
4. Si se reinicia `uvicorn`, los jobs en memoria se pierden.
5. Si queres repetir una prueba desde cero, conviene limpiar detecciones y evidencias previas.
