from datetime import datetime, timedelta, timezone


# Buenos Aires opera en UTC-03:00, y usar un offset fijo evita depender
# del paquete tzdata en Windows.
APP_TIMEZONE = timezone(timedelta(hours=-3), name="America/Buenos_Aires")


def now_local() -> datetime:
    """
    Devuelve la fecha y hora actual en la zona horaria del proyecto.
    """
    return datetime.now(APP_TIMEZONE)


def ensure_local_datetime(value: datetime) -> datetime:
    """
    Normaliza fechas leidas desde SQLite.

    SQLite puede devolver datetimes sin tzinfo aunque se hayan creado con offset.
    En ese caso asumimos que ya representan la hora local del proyecto.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=APP_TIMEZONE)
    return value.astimezone(APP_TIMEZONE)
