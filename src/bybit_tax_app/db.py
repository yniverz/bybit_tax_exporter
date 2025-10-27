from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from .models import Base


# Project paths
ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
DB_PATH = DATA_DIR / "app.db"

# Ensure data directory exists
DATA_DIR.mkdir(parents=True, exist_ok=True)

# SQLite engine configured for durability over speed
DATABASE_URL = f"sqlite+pysqlite:///{DB_PATH}"
engine = create_engine(
    DATABASE_URL,
    # Keep SQLite strict about thread ownership (each thread gets its own connection)
    connect_args={
        "check_same_thread": True,
        # Increase lock wait to reduce OperationalError: database is locked
        "timeout": 30,
    },
    # Avoid reusing DBAPI connections across threads
    poolclass=NullPool,
    future=True,
)


def _configure_sqlite_durability() -> None:
    """Apply SQLite PRAGMAs emphasizing durability.

    Notes:
    - journal_mode=DELETE + synchronous=FULL provides strong durability guarantees.
    - fullfsync=ON (macOS) asks OS to flush buffers physically.
    - busy_timeout is also set via connect_args, but we keep the PRAGMA for completeness.
    """

    def _on_connect(dbapi_connection, connection_record):  # pragma: no cover - connection hook
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=DELETE")
            cursor.execute("PRAGMA synchronous=FULL")
            cursor.execute("PRAGMA fullfsync=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

    event.listen(engine, "connect", _on_connect)


_configure_sqlite_durability()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)


def init_db() -> None:
    """Create all tables if they do not exist."""
    # Perform lightweight migration if HistoricalFiatPrice still has 'date' column
    _maybe_migrate_hfp_date_to_timestamp()
    Base.metadata.create_all(bind=engine)
    # Add new columns as needed
    _maybe_add_is_manual_to_spot()


@contextmanager
def get_session():
    """Context manager yielding a SQLAlchemy session and ensuring proper cleanup."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _maybe_migrate_hfp_date_to_timestamp() -> None:
    """Migrate historical_fiat_prices.date (DATE) -> timestamp (DATETIME) if needed.

    This handles the schema change by:
    - Detecting legacy schema with 'date' column and no 'timestamp'
    - Renaming the old table to historical_fiat_prices_old
    - Creating the new table via SQLAlchemy metadata
    - Copying rows with timestamp set to midnight UTC of the legacy date
    - Dropping the old table

    Safe to run multiple times; no-op if already migrated.
    """
    with engine.begin() as conn:
        # Check if table exists
        res = conn.execute(text("""
            SELECT name FROM sqlite_master WHERE type='table' AND name='historical_fiat_prices'
        """)).fetchone()
        if not res:
            return
        # Inspect columns
        cols = conn.execute(text("PRAGMA table_info('historical_fiat_prices')")).fetchall()
        col_names = {row[1] for row in cols} if cols else set()
        if "timestamp" in col_names:
            return  # already migrated
        if "date" not in col_names:
            return  # unexpected schema; skip

        # Rename old table
        conn.execute(text("ALTER TABLE historical_fiat_prices RENAME TO historical_fiat_prices_old"))

    # Create new table structure
    Base.metadata.create_all(bind=engine)

    # Copy data from old to new
    with engine.begin() as conn:
        # Insert while converting DATE text to ISO timestamp at UTC midnight
        # SQLite stores DATE as TEXT in 'YYYY-MM-DD'. Use datetime() to normalize.
        conn.execute(text(
            """
            INSERT OR IGNORE INTO historical_fiat_prices (coin, fiat, price, timestamp)
            SELECT coin, fiat, price, datetime(date || 'T00:00:00Z')
            FROM historical_fiat_prices_old
            """
        ))
        # Drop old table
        conn.execute(text("DROP TABLE IF EXISTS historical_fiat_prices_old"))


def _maybe_add_is_manual_to_spot() -> None:
    """Add is_manual column to spot_executions if missing.

    SQLite ALTER TABLE is limited but supports adding a column. We add as INTEGER NOT NULL DEFAULT 0.
    Safe to run multiple times; no-op if column exists.
    """
    with engine.begin() as conn:
        res = conn.execute(text("""
            SELECT name FROM sqlite_master WHERE type='table' AND name='spot_executions'
        """)).fetchone()
        if not res:
            return
        cols = conn.execute(text("PRAGMA table_info('spot_executions')")).fetchall()
        col_names = {row[1] for row in cols} if cols else set()
        if "is_manual" in col_names:
            return
        # Add the column with default 0 (False)
        conn.execute(text("ALTER TABLE spot_executions ADD COLUMN is_manual INTEGER NOT NULL DEFAULT 0"))


