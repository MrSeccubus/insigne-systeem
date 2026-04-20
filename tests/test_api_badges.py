class TestListBadges:
    def test_returns_200(self, client, db):
        r = client.get("/api/badges")
        assert r.status_code == 200

    def test_returns_category_dict(self, client, db):
        data = client.get("/api/badges").json()
        assert isinstance(data, dict)
        assert len(data) > 0

    def test_each_badge_has_required_fields(self, client, db):
        data = client.get("/api/badges").json()
        for badges in data.values():
            for badge in badges:
                assert "slug" in badge
                assert "title" in badge
                assert "category" in badge
                assert "images" in badge


class TestGetBadge:
    def test_returns_badge_detail(self, client, db):
        r = client.get("/api/badges/sport_spel")
        assert r.status_code == 200
        data = r.json()
        assert data["slug"] == "sport_spel"
        assert "title" in data
        assert "levels" in data
        assert "introduction" in data
        assert "afterword" in data

    def test_levels_have_steps(self, client, db):
        data = client.get("/api/badges/sport_spel").json()
        assert len(data["levels"]) > 0
        for level in data["levels"]:
            assert "name" in level
            assert "steps" in level

    def test_unknown_slug_returns_404(self, client, db):
        r = client.get("/api/badges/this-badge-does-not-exist")
        assert r.status_code == 404
