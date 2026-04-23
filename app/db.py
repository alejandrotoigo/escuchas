from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url
from sqlmodel import Session, create_engine

from app.config import settings


def _engine_connect_args() -> dict:
    if settings.database_url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


engine = create_engine(settings.database_url, echo=False, connect_args=_engine_connect_args(), pool_pre_ping=True)


def _database_connect_kwargs(database_url) -> dict:
    return {
        key: value
        for key, value in {
            "host": database_url.host,
            "port": database_url.port,
            "user": database_url.username,
            "password": database_url.password,
            "dbname": database_url.database,
        }.items()
        if value is not None
    }


def ensure_database_exists() -> None:
    database_url = make_url(settings.database_url)
    if database_url.get_backend_name() != "postgresql":
        return

    target_database = database_url.database
    target_connect_kwargs = _database_connect_kwargs(database_url)
    try:
        with psycopg.connect(**target_connect_kwargs):
            return
    except psycopg.OperationalError as exc:
        if "does not exist" not in str(exc).lower():
            raise

    admin_url = database_url.set(database=settings.postgres_admin_database)
    with psycopg.connect(autocommit=True, **_database_connect_kwargs(admin_url)) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target_database,))
            if cursor.fetchone() is None:
                cursor.execute(f'CREATE DATABASE "{target_database}"')


def _alembic_config() -> Config:
    project_root = Path(__file__).resolve().parent.parent
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "migrations"))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    return config


def create_db_and_tables() -> None:
    ensure_database_exists()
    command.upgrade(_alembic_config(), "head")


def get_session():
    with Session(engine) as session:
        yield session
