"""
Unit tests for load_cookies() in wp_access.py — cookie sanitisation logic.
"""

import json
import pytest
from pathlib import Path

from wp_access import load_cookies


def write_cookies(tmp_path, cookies) -> Path:
    p = tmp_path / "wp_cookies.json"
    p.write_text(json.dumps(cookies))
    return p


def load(tmp_path, cookies):
    return load_cookies(write_cookies(tmp_path, cookies))


class TestLoadCookiesFileHandling:
    def test_missing_file_exits_with_error(self, tmp_path):
        with pytest.raises(SystemExit):
            load_cookies(tmp_path / "does_not_exist.json")

    def test_returns_list(self, tmp_path):
        result = load(tmp_path, [{"name": "a", "value": "b"}])
        assert isinstance(result, list)

    def test_all_cookies_returned(self, tmp_path):
        cookies = [{"name": str(i), "value": str(i)} for i in range(5)]
        result = load(tmp_path, cookies)
        assert len(result) == 5


class TestSameSiteNormalisation:
    def test_valid_strict_preserved(self, tmp_path):
        result = load(tmp_path, [{"name": "x", "value": "y", "sameSite": "Strict"}])
        assert result[0]["sameSite"] == "Strict"

    def test_valid_lax_preserved(self, tmp_path):
        result = load(tmp_path, [{"name": "x", "value": "y", "sameSite": "Lax"}])
        assert result[0]["sameSite"] == "Lax"

    def test_valid_none_preserved(self, tmp_path):
        result = load(tmp_path, [{"name": "x", "value": "y", "sameSite": "None"}])
        assert result[0]["sameSite"] == "None"

    def test_invalid_same_site_replaced_with_lax(self, tmp_path):
        result = load(tmp_path, [{"name": "x", "value": "y", "sameSite": "unspecified"}])
        assert result[0]["sameSite"] == "Lax"

    def test_missing_same_site_defaults_to_lax(self, tmp_path):
        result = load(tmp_path, [{"name": "x", "value": "y"}])
        assert result[0]["sameSite"] == "Lax"

    def test_empty_string_same_site_replaced_with_lax(self, tmp_path):
        result = load(tmp_path, [{"name": "x", "value": "y", "sameSite": ""}])
        assert result[0]["sameSite"] == "Lax"


class TestDefaultFields:
    def test_secure_defaults_to_false(self, tmp_path):
        result = load(tmp_path, [{"name": "x", "value": "y"}])
        assert result[0]["secure"] is False

    def test_secure_true_preserved(self, tmp_path):
        result = load(tmp_path, [{"name": "x", "value": "y", "secure": True}])
        assert result[0]["secure"] is True

    def test_http_only_defaults_to_false(self, tmp_path):
        result = load(tmp_path, [{"name": "x", "value": "y"}])
        assert result[0]["httpOnly"] is False

    def test_http_only_true_preserved(self, tmp_path):
        result = load(tmp_path, [{"name": "x", "value": "y", "httpOnly": True}])
        assert result[0]["httpOnly"] is True


class TestFieldRemoval:
    def test_host_only_removed(self, tmp_path):
        result = load(tmp_path, [{"name": "x", "value": "y", "hostOnly": True}])
        assert "hostOnly" not in result[0]

    def test_session_removed(self, tmp_path):
        result = load(tmp_path, [{"name": "x", "value": "y", "session": False}])
        assert "session" not in result[0]

    def test_store_id_removed(self, tmp_path):
        result = load(tmp_path, [{"name": "x", "value": "y", "storeId": "0"}])
        assert "storeId" not in result[0]

    def test_id_field_removed(self, tmp_path):
        result = load(tmp_path, [{"name": "x", "value": "y", "id": 42}])
        assert "id" not in result[0]

    def test_name_and_value_not_removed(self, tmp_path):
        result = load(tmp_path, [{"name": "myname", "value": "myvalue"}])
        assert result[0]["name"]  == "myname"
        assert result[0]["value"] == "myvalue"

    def test_all_removable_fields_stripped_at_once(self, tmp_path):
        cookie = {
            "name": "x", "value": "y",
            "hostOnly": True, "session": True, "storeId": "0", "id": 1,
        }
        result = load(tmp_path, [cookie])
        for field in ("hostOnly", "session", "storeId", "id"):
            assert field not in result[0]


# ── Edge / chaos / adversarial ────────────────────────────────────────────────

class TestLoadCookiesEdgeCases:
    def test_empty_cookie_list_returns_empty_list(self, tmp_path):
        """An empty [] JSON file is valid and should return []."""
        result = load(tmp_path, [])
        assert result == []

    def test_numeric_same_site_replaced_with_lax(self, tmp_path):
        """Non-string sameSite (e.g. an integer) is invalid → 'Lax'."""
        result = load(tmp_path, [{"name": "x", "value": "y", "sameSite": 42}])
        assert result[0]["sameSite"] == "Lax"

    def test_case_sensitive_same_site_strict_vs_lowercase(self, tmp_path):
        """'strict' (lowercase) is not a valid sameSite value → 'Lax'."""
        result = load(tmp_path, [{"name": "x", "value": "y", "sameSite": "strict"}])
        assert result[0]["sameSite"] == "Lax"

    def test_multiple_cookies_all_sanitised(self, tmp_path):
        """All cookies in the list receive the sanitisation treatment."""
        cookies = [
            {"name": str(i), "value": str(i), "sameSite": "bad", "hostOnly": True}
            for i in range(3)
        ]
        result = load(tmp_path, cookies)
        for c in result:
            assert c["sameSite"] == "Lax"
            assert "hostOnly" not in c

    def test_unknown_fields_are_preserved(self, tmp_path):
        """Fields not in the remove-list should pass through unchanged."""
        result = load(tmp_path, [{"name": "x", "value": "y", "domain": ".wp.com"}])
        assert result[0]["domain"] == ".wp.com"
