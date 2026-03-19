"""Local sqlite storage for OHLCV data."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3


@dataclass(slots=True)
class OhlcvStore:
    """Baseline sqlite store used by the polling layer."""

    db_path: Path

    def initialize(self) -> Path:
        """Create the OHLCV table if it does not already exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS ohlcv (
                    pair TEXT NOT NULL,
                    ts TEXT NOT NULL,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume REAL
                )
                """
            )
        return self.db_path

    def database_exists(self) -> bool:
        """Return whether the sqlite file has already been created."""
        return self.db_path.exists()

