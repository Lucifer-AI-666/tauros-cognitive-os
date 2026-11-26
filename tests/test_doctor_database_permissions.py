"""Regression checks for database readiness reported by tauros doctor."""

import os

from tauros.bootstrap import doctor_checks
from tauros.settings import Settings


def _db_check(tmp_path, database_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = Settings(
        _env_file=None,
        database_path=database_path,
        provider="disabled-for-test",
        api_token="test-StrongToken-Alpha1234567890!",
        security_mode="locked",
    )
    return next(item for item in doctor_checks(settings) if item["check"] == "database_parent_writable")


def test_doctor_reports_missing_database_parent(tmp_path, monkeypatch):
    db = tmp_path / "missing" / "tauros.db"
    assert _db_check(tmp_path, db, monkeypatch)["ok"] is False


def test_doctor_accepts_writable_existing_parent(tmp_path, monkeypatch):
    directory = tmp_path / "data"
    directory.mkdir()
    assert _db_check(tmp_path, directory / "tauros.db", monkeypatch)["ok"] is True


def test_doctor_rejects_denied_parent_permissions(tmp_path, monkeypatch):
    directory = tmp_path / "data"
    directory.mkdir()
    actual_access = os.access

    def controlled_access(path, mode):
        if os.fspath(path) == os.fspath(directory) and mode & os.W_OK:
            return False
        return actual_access(path, mode)

    monkeypatch.setattr("tauros.bootstrap.os.access", controlled_access)
    assert _db_check(tmp_path, directory / "tauros.db", monkeypatch)["ok"] is False
