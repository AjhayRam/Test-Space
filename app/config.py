import os
from dataclasses import dataclass, field


def _env_bool(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str = field(
        default_factory=lambda: os.getenv(
            "DATABASE_URL", "postgresql+psycopg://ledger:ledger@localhost:5433/ledger"
        )
    )
    # Create tables (and immutability triggers) on startup. Handy for local runs;
    # a real deployment would use migrations instead.
    auto_create_tables: bool = field(default_factory=lambda: _env_bool("AUTO_CREATE_TABLES", "true"))
    default_page_size: int = 20
    max_page_size: int = 100


settings = Settings()
