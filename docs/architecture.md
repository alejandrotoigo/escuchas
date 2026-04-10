# Arquitectura MVP

## Objetivo

Detectar si un spot publicitario cargado previamente aparece dentro de una transmision en vivo y registrar cuantas veces aparece.

## Pipeline

### 1. Ingestion de pauta

- El usuario crea una campana.
- El usuario sube un spot en audio o video.
- El backend guarda el archivo original.
- Si hay `ffmpeg`, convierte el material a WAV mono 16kHz.
- Se calcula una firma base del spot y se almacena.

### 2. Registro de streams

- El usuario registra una o mas fuentes en vivo.
- Cada fuente queda lista para ser tomada por un worker de monitoreo.

### 3. Monitoreo continuo

Etapa siguiente al MVP actual:

- Un worker abre el stream.
- Corta ventanas de audio de 5 a 15 segundos.
- Normaliza cada ventana.
- Calcula su firma.
- Compara contra la biblioteca de spots.
- Si hay coincidencia, guarda una deteccion.

### 4. Reporteria

- Detecciones por spot
- Detecciones por stream
- Conteo por franja horaria
- Evidencia de audio por coincidencia

## Estrategia de deteccion recomendada

### Fase 1

- Matching de huellas para spots exactos o casi exactos.
- Rapida implementacion.
- Baja complejidad operativa.

### Fase 2

- Transcripcion del spot y del stream usando Whisper.
- Matching semantico o por texto para detectar variantes locutadas.

### Fase 3

- Modelos tolerantes a ruido, recortes, overlays y compresion.
- Reglas anti-duplicado para no contar dos veces el mismo pase.

## Componentes del repo

- `app/main.py`: API principal.
- `app/models.py`: entidades de dominio.
- `app/services/media.py`: extraccion, normalizacion y fingerprint.
- `app/services/monitoring.py`: matcher inicial para futuras ventanas de stream.

## Limitaciones actuales

- Todavia no hay worker de escucha continua.
- La huella implementada es una base inicial, no un algoritmo estilo Shazam.
- El procesamiento de video depende de `ffmpeg`.
- En este entorno no se detecto un interprete Python operativo para ejecutar la app.

## Proximo incremento

1. Crear un worker `monitor.py`.
2. Conectar `ffmpeg` a una URL de stream para extraer audio en vivo.
3. Procesar ventanas temporales y compararlas con la biblioteca de spots.
4. Crear detecciones y conteo consolidado.
