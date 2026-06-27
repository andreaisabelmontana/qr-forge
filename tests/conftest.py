"""Test fixtures: a TestClient backed by a throwaway SQLite database."""

from __future__ import annotations

import importlib
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # Point the app at a temp DB before it (re)imports / inits.
    monkeypatch.setenv("QRFORGE_DB", str(tmp_path / "test.db"))

    import app.db as db
    import app.api as api

    importlib.reload(db)
    importlib.reload(api)
    db.init_db()

    with TestClient(api.app) as c:
        yield c
