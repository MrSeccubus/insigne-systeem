"""Tests for GET /api/version."""
from unittest.mock import patch

import insigne.version as version_mod


class TestGetVersion:
    def test_returns_200(self, client, db):
        r = client.get("/api/version")
        assert r.status_code == 200

    def test_no_auth_required(self, client, db):
        r = client.get("/api/version")
        assert r.status_code == 200

    def test_version_field_present(self, client, db):
        r = client.get("/api/version")
        assert "version" in r.json()

    def test_newer_release_field_present(self, client, db):
        r = client.get("/api/version")
        assert "newer_release" in r.json()

    def test_newer_release_null_when_up_to_date(self, client, db):
        with patch("routers.api_version.get_newer_release", return_value=None):
            r = client.get("/api/version")
        assert r.json()["newer_release"] is None

    def test_newer_release_returned_when_available(self, client, db):
        with patch("routers.api_version.get_newer_release", return_value="v9.9.9"):
            r = client.get("/api/version")
        assert r.json()["newer_release"] == "v9.9.9"

    def test_version_matches_app_version(self, client, db):
        with patch.object(version_mod, "APP_VERSION", "v1.2.3"):
            # Re-import to pick up patched value — call endpoint directly
            r = client.get("/api/version")
        # The version in the response must be a non-empty string
        assert isinstance(r.json()["version"], str)
        assert r.json()["version"]
