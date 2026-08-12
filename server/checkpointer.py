"""Lakebase-backed LangGraph checkpointer.

Persists the analytics agent's conversation state and step-by-step checkpoints in
Lakebase (Databricks Postgres). Each pooled connection mints a fresh Lakebase OAuth
token as its password on connect, so long-lived pools never fail on token expiry.
"""

import os

from langgraph.checkpoint.postgres import PostgresSaver
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from server.database import get_database_token

_checkpointer: PostgresSaver | None = None

# PostgresSaver requires connections that autocommit and return dict rows.
_SAVER_CONNECT_KWARGS = {
    "autocommit": True,
    "prepare_threshold": 0,
    "row_factory": dict_row,
}


class _LakebaseConnection(Connection):
    """psycopg connection that injects a fresh Lakebase OAuth token as its password.

    The token is only injected when connecting to Lakebase. A ``DATABASE_URL``
    override (local Postgres/sqlite) is left untouched.
    """

    @classmethod
    def connect(cls, conninfo: str = "", **kwargs):
        if "DATABASE_URL" not in os.environ:
            kwargs["password"] = get_database_token()
        return super().connect(conninfo, **kwargs)


def _connection_settings() -> tuple[str, dict]:
    override_url = os.environ.get("DATABASE_URL")
    if override_url:
        return override_url, dict(_SAVER_CONNECT_KWARGS)

    return "", {
        **_SAVER_CONNECT_KWARGS,
        "host": os.environ["PGHOST"],
        "port": int(os.environ.get("PGPORT", "5432")),
        "dbname": os.environ.get("PGDATABASE", "databricks_postgres"),
        "user": os.environ.get("PGUSER"),
        "sslmode": os.environ.get("PGSSLMODE", "require"),
    }


def get_checkpointer() -> PostgresSaver:
    """Return a process-wide PostgresSaver, creating the checkpoint tables once."""
    global _checkpointer

    if _checkpointer is None:
        conninfo, connect_kwargs = _connection_settings()
        pool = ConnectionPool(
            conninfo=conninfo,
            connection_class=_LakebaseConnection,
            kwargs=connect_kwargs,
            min_size=1,
            max_size=4,
            # Recycle below the ~50 minute token lifetime so every physical
            # connection reconnects with a freshly minted token.
            max_lifetime=1800,
            open=False,
        )
        pool.open()
        checkpointer = PostgresSaver(pool)
        checkpointer.setup()
        _checkpointer = checkpointer

    return _checkpointer
