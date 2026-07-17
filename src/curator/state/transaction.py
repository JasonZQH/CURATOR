"""Provide atomic transaction boundaries for Curator state mutations."""

from contextlib import contextmanager
import sqlite3
from collections.abc import Iterator

from curator.state.db import CuratorConnection


@contextmanager
def transaction(connection: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run a mutation group atomically with nested SAVEPOINT support."""
    if isinstance(connection, CuratorConnection):
        connection.begin_transaction()
        try:
            yield connection
        except BaseException:
            connection.rollback_transaction()
            raise
        else:
            connection.commit_transaction()
        return

    connection.execute("BEGIN IMMEDIATE")
    try:
        yield connection
    except BaseException:
        connection.rollback()
        raise
    else:
        connection.commit()
