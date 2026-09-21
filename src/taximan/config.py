"""Configuration from environment. Never hard code credentials."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    host: str = os.getenv("MYSQL_HOST", "127.0.0.1")
    port: int = int(os.getenv("MYSQL_PORT", "3307"))
    database: str = os.getenv("MYSQL_DATABASE", "taximan")
    user: str = os.getenv("MYSQL_USER", "taximan")
    password: str = os.getenv("MYSQL_PASSWORD", "taximan")
    pool_size: int = int(os.getenv("MYSQL_POOL_SIZE", "8"))

    def connect_kwargs(self) -> dict:
        return {
            "host": self.host,
            "port": self.port,
            "database": self.database,
            "user": self.user,
            "password": self.password,
            "autocommit": False,
            "allow_local_infile": True,
            "time_zone": "+00:00",
        }


settings = Settings()
MIGRATIONS_DIR = PROJECT_ROOT / "db" / "migrations"
ANALYTICS_DIR = PROJECT_ROOT / "db" / "analytics"
DATA_DIR = PROJECT_ROOT / "data"
