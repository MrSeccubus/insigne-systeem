import pytest


@pytest.fixture(autouse=True)
def _reset_dev_global(client):
    import templates as t
    original = t.templates.env.globals["dev"]
    yield
    t.templates.env.globals["dev"] = original


def test_dev_banner_hidden_by_default(client):
    r = client.get("/", follow_redirects=True)
    assert "dev-banner" not in r.text


def test_dev_banner_shown_when_dev_enabled(client):
    import templates as t
    t.templates.env.globals["dev"] = True
    r = client.get("/", follow_redirects=True)
    assert "dev-banner" in r.text
