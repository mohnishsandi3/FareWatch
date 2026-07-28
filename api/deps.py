"""FastAPI dependencies — a pooled Postgres connection per request.

Reuses the shared connection pool. The pool opens lazily on first use, so simply
importing this module never touches the database (keeps unit tests pure).
"""
from __future__ import annotations

from typing import Iterator

import psycopg

from shared import db


def get_conn() -> Iterator[psycopg.Connection]:
    """Yield a pooled connection; returned to the pool when the request ends.

    Read endpoints don't write, so we roll back at the end to be explicit that
    nothing is committed implicitly. The two write endpoints (create/deactivate
    watch) commit themselves before returning.
    """
    with db.get_conn() as conn:
        try:
            yield conn
        finally:
            conn.rollback()
