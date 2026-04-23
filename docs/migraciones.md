# Migraciones

Esta guia explica como usar las migraciones del proyecto con Alembic.

## Resumen

- La aplicacion usa PostgreSQL en `localhost:5432`.
- La URL por defecto es `postgresql+psycopg://postgres:postgres@localhost:5432/escuchas`.
- Al iniciar la API, el backend crea la base `escuchas` si no existe y luego ejecuta `alembic upgrade head`.
- Las migraciones viven en `migrations/versions`.

## Estructura

- `alembic.ini`: configuracion principal de Alembic.
- `migrations/env.py`: integra Alembic con los modelos de SQLModel.
- `migrations/versions`: historial versionado de cambios de esquema.

## Flujo normal de uso

### 1. Levantar todo por primera vez

Instalar dependencias:

```powershell
pip install -r requirements.txt
```

Levantar la API:

```powershell
uvicorn app.main:app --reload
```

Cuando la app arranca:

1. verifica la conexion configurada
2. crea la base `escuchas` si todavia no existe
3. corre todas las migraciones pendientes hasta `head`

## Comandos utiles

### Ver la version actual aplicada

```powershell
alembic current
```

### Ver historial de migraciones

```powershell
alembic history
```

### Aplicar todas las migraciones pendientes

```powershell
alembic upgrade head
```

### Volver una migracion para atras

```powershell
alembic downgrade -1
```

### Volver a una revision puntual

```powershell
alembic downgrade 20260422_0001
```

## Crear una migracion nueva

Tenes dos formas.

### Opcion 1. Escribirla a mano

Crear una nueva revision vacia:

```powershell
alembic revision -m "agrega columna campaign_code"
```

Eso crea un archivo nuevo dentro de `migrations/versions`.

Despues completas manualmente las funciones `upgrade()` y `downgrade()`.

Este enfoque se parece al estilo Flyway: cada cambio queda en un script versionado y controlado.

### Opcion 2. Autogenerarla desde los modelos

Primero cambias los modelos en `app/models.py`.

Despues generas el diff:

```powershell
alembic revision --autogenerate -m "agrega columna campaign_code"
```

Importante:

- revisar siempre el archivo generado antes de aplicarlo
- no asumir que el autogenerado es perfecto
- si hay renombres de columnas o tablas, ajustar la migracion manualmente

## Aplicar una migracion nueva

Una vez creada la revision:

```powershell
alembic upgrade head
```

## Ejemplo de flujo completo

### 1. Cambiar un modelo

Ejemplo: agregar una columna nueva en una entidad.

### 2. Generar la migracion

```powershell
alembic revision --autogenerate -m "agrega campo x"
```

### 3. Revisar el archivo en `migrations/versions`

Confirmar:

- operaciones correctas en `upgrade()`
- rollback correcto en `downgrade()`

### 4. Aplicar la migracion

```powershell
alembic upgrade head
```

### 5. Probar la app

Levantar la API y verificar que sigue arrancando bien.

## Consultar la version aplicada en PostgreSQL

La version actual queda registrada en la tabla:

- `public.alembic_version`

Consulta de ejemplo:

```sql
SELECT version_num FROM public.alembic_version;
```

## Buenas practicas

- crear una migracion por cambio de esquema coherente
- usar mensajes cortos y claros en cada revision
- revisar a mano las migraciones autogeneradas
- no editar una migracion ya aplicada en otros entornos
- si ya fue aplicada, crear una revision nueva que corrija el cambio

## Problemas comunes

### La app no crea la base

Verificar:

- que PostgreSQL este corriendo en `localhost:5432`
- que exista el usuario `postgres` con password `postgres`
- que la URL en `DATABASE_URL` sea correcta

### Alembic no detecta cambios

Verificar:

- que el modelo nuevo este importado por `app.models`
- que `migrations/env.py` siga apuntando a `SQLModel.metadata`

### La migracion falla a mitad de camino

Revisar:

- el SQL generado
- restricciones o datos incompatibles
- si hace falta dividir el cambio en dos migraciones

## Variables de entorno

Por defecto se usa:

```env
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/escuchas
POSTGRES_ADMIN_DATABASE=postgres
```

Si cambias estas variables, tanto la app como Alembic van a usar esos valores.
