import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


# ── config._load() ────────────────────────────────────────────────────────────

class TestConfigLoad:
    def _minimal_yml(self):
        return (
            "database:\n"
            "  url: 'sqlite:///:memory:'\n"
            "jwt:\n"
            "  secret_key: test-secret\n"
        )

    def test_raises_when_config_file_missing(self, tmp_path):
        from insigne.config import _load
        missing = str(tmp_path / "nonexistent.yml")
        with patch.dict(os.environ, {"INSIGNE_CONFIG": missing}):
            with pytest.raises(RuntimeError, match="Config file not found"):
                _load()

    def test_loads_relative_path_resolved_against_cwd(self, tmp_path):
        from insigne.config import _load
        cfg_file = tmp_path / "test_config.yml"
        cfg_file.write_text(self._minimal_yml())
        # Use a relative filename; patch cwd so it resolves to tmp_path
        with patch.dict(os.environ, {"INSIGNE_CONFIG": "test_config.yml"}), \
             patch("insigne.config.Path.cwd", return_value=tmp_path):
            cfg = _load()
        assert cfg.database_url == "sqlite:///:memory:"

    def test_loads_absolute_path(self, tmp_path):
        from insigne.config import _load
        cfg_file = tmp_path / "abs_config.yml"
        cfg_file.write_text(self._minimal_yml())
        with patch.dict(os.environ, {"INSIGNE_CONFIG": str(cfg_file)}):
            cfg = _load()
        assert cfg.jwt_secret_key == "test-secret"


# ── database.get_db() ─────────────────────────────────────────────────────────

class TestGetDb:
    def test_get_db_yields_session_and_closes(self):
        from insigne.database import get_db
        gen = get_db()
        session = next(gen)
        assert session is not None
        # exhaust the generator (triggers the finally/close)
        with pytest.raises(StopIteration):
            next(gen)


# ── email._env() with custom templates_dir ───────────────────────────────────

class TestEnvCustomTemplatesDir:
    def test_custom_templates_dir_is_used_as_first_loader(self, tmp_path):
        import insigne.email as email_mod
        with patch.object(email_mod.config.email, "templates_dir", str(tmp_path)):
            env = email_mod._env()
        # ChoiceLoader wraps multiple loaders; custom dir should be first
        loaders = env.loader.loaders
        from jinja2 import FileSystemLoader
        assert isinstance(loaders[0], FileSystemLoader)
        assert str(tmp_path) in loaders[0].searchpath
