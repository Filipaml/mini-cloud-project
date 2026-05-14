import logging
import os
import time

from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import declarative_base, sessionmaker

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://user:password@cloud-db:5432/cloud_db",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)
Base = declarative_base()


def get_db(): # Dependency do FastAPI: abre sessão, fecha no fim
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db(retries: int = 15, delay: float = 2.0) -> None:
    """
    Espera o postgres ficar pronto e cria as tabelas.
    Chamado no lifespan do FastAPI — não no import — para que o crash
    não aconteça antes do logger sequer estar configurado.
    """
    # importar para registar o model na Base.metadata
    from models import File  # noqa: F401

    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            Base.metadata.create_all(bind=engine)
            logger.info("Database tables ready (attempt %d)", attempt)
            return
        except OperationalError as e:
            last_err = e
            logger.warning(
                "DB not ready yet (attempt %d/%d): %s", attempt, retries, e.__class__.__name__
            )
            time.sleep(delay)
    raise RuntimeError(f"Could not connect to DB after {retries} attempts: {last_err}")