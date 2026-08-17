"""Verify an upgraded ledger ends up shaped exactly like a fresh one.

`phase0_schema_sql()` is `executescript`ed on every open and is all
`create table if not exists`, so a **new table** reaches an existing ledger for free — but
a **new column** on an existing table does not. It only arrives through a numbered entry in
`VERSIONED_MIGRATIONS`. Adding the column to the schema SQL alone is therefore invisible in
CI, which always starts from an empty database, and shows up as a broken read on the
machine of every user who has been here since the previous release.

This test is the thing that catches that: it upgrades a ledger created by the released
v0.1.2 and compares its shape, column by column, against a ledger created from scratch.
"""

import sqlite3
from pathlib import Path

from curator.state.db import connect_database, initialize_database

FIXTURE = Path(__file__).parent / "fixtures" / "ledger-schema-v0.1.2.sql"


def _table_shapes(connection: sqlite3.Connection) -> dict[str, list[tuple]]:
    """Return every table's column shape, keyed by table name."""
    tables = [
        row["name"]
        for row in connection.execute(
            "select name from sqlite_master where type = 'table' "
            "and name not like 'sqlite_%' order by name"
        )
    ]
    return {
        table: [
            (row["name"], row["type"], row["notnull"], row["dflt_value"], row["pk"])
            for row in connection.execute(f"pragma table_info({table})")
        ]
        for table in tables
    }


def _released_ledger(path: Path) -> sqlite3.Connection:
    """Build a ledger with the schema the released v0.1.2 actually created."""
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = connect_database(path)
    connection.executescript(FIXTURE.read_text())
    connection.commit()
    return connection


def test_upgrading_a_released_ledger_matches_a_fresh_one(tmp_path):
    """Verify every column of an upgraded v0.1.2 ledger matches a fresh install.

    A failure here means a column was added to the schema SQL without a matching
    pragma-guarded entry in VERSIONED_MIGRATIONS — existing users would keep the old
    shape until a read raised on their machine.
    """
    upgraded = _released_ledger(tmp_path / "upgraded" / "curator.sqlite")
    initialize_database(upgraded)

    fresh = connect_database(tmp_path / "fresh" / "curator.sqlite")
    initialize_database(fresh)

    upgraded_shapes = _table_shapes(upgraded)
    fresh_shapes = _table_shapes(fresh)
    upgraded.close()
    fresh.close()

    assert set(upgraded_shapes) == set(fresh_shapes), "table set drifted between install paths"
    for table in sorted(fresh_shapes):
        assert upgraded_shapes[table] == fresh_shapes[table], (
            f"{table} has a different shape after an upgrade than on a fresh install — "
            "a column was very likely added to phase0_schema_sql without a migration"
        )


def test_the_fixture_still_describes_a_ledger_older_than_head(tmp_path):
    """Verify the fixture is a real earlier schema, not a copy of the current one.

    If someone regenerates the fixture from HEAD to make the test above pass, the guard
    stops guarding. Once HEAD adds its first column migration this asserts the fixture is
    genuinely behind; until then it only asserts the fixture loads and is non-trivial.
    """
    from curator.state.db import VERSIONED_MIGRATIONS

    released = _released_ledger(tmp_path / "released" / "curator.sqlite")
    applied = {row["version"] for row in released.execute("select version from schema_version")}
    shapes = _table_shapes(released)
    released.close()

    assert len(shapes) >= 30, "the fixture should carry the full v0.1.2 table set"
    assert applied == {1, 2}, "v0.1.2 shipped exactly two applied migrations"
    if len(VERSIONED_MIGRATIONS) > 2:
        assert applied < {version for version, _ in VERSIONED_MIGRATIONS}, (
            "HEAD has migrations the fixture has not applied — regenerate the fixture only "
            "from a released tag, never from HEAD"
        )
