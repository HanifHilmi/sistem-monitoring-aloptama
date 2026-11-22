"""The migration runner's plan (NFR-OPS-002): a rollback runs on a database one release ahead, nothing else does."""

from __future__ import annotations

from pathlib import Path

import pytest

from simola.migrations.runner import Migration, MigrationError, discover, plan

FILES = discover()


def _applied(migrations: list[Migration]) -> dict[str, str]:
    return {m.version: m.checksum for m in migrations}


def _future(version: str = "9999_future") -> Migration:
    return Migration(version, Path(f"{version}.sql"), "SELECT 1;", "f" * 64)


def test_the_release_files_are_in_order_and_include_the_contract_step() -> None:
    versions = [m.version for m in FILES]
    assert versions == sorted(versions)
    assert "0013_drop_old_component_details" in versions


def test_a_new_database_gets_every_file_and_an_up_to_date_one_nothing() -> None:
    assert plan({}, FILES) == (FILES, [])
    assert plan(_applied(FILES), FILES) == ([], [])
    assert plan(_applied(FILES[:-1]), FILES) == ([FILES[-1]], [])


def test_a_rollback_runs_on_the_newer_database_and_applies_nothing() -> None:
    # the release before this one, on a database this release has migrated
    older = FILES[:-1]
    assert plan(_applied(FILES), older) == ([], [FILES[-1].version])
    # several newer migrations (two releases back) are accepted as well; NFR-OPS-002 promises only one
    assert plan(_applied([*FILES, _future()]), older) == ([], [FILES[-1].version, "9999_future"])


def test_an_unknown_version_among_the_release_files_stops_the_run() -> None:
    # the database has a file this release does not have, sorting among its own: another branch or a removed file
    missing = FILES[4]
    release = [m for m in FILES if m is not missing]
    with pytest.raises(MigrationError, match=rf"unknown to this release: \['{missing.version}'\]"):
        plan(_applied(FILES), release)


def test_a_file_still_to_apply_while_the_database_is_ahead_stops_the_run() -> None:
    gap = FILES[4]
    applied = _applied([*(m for m in FILES if m is not gap), _future()])
    with pytest.raises(MigrationError, match=rf"ahead of this release.*'{gap.version}'.*not applied"):
        plan(applied, FILES)


def test_a_changed_file_stops_the_run_even_on_a_newer_database() -> None:
    applied = _applied([*FILES, _future()])
    applied[FILES[0].version] = "0" * 64
    with pytest.raises(MigrationError, match=f"checksum mismatch for applied migration {FILES[0].version}"):
        plan(applied, FILES[:-1])


def test_no_files_at_all_never_counts_as_a_rollback() -> None:
    with pytest.raises(MigrationError, match="unknown to this release"):
        plan(_applied(FILES), [])
