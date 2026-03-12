"""
Unit tests for _parse_cookie_expiry() in app.py.
Pure function — no DB or HTTP involved.
"""

import json
import re

import pytest

from app import _parse_cookie_expiry


def _cookies(expiration_date):
    """Helper: single-cookie JSON string with the given expirationDate."""
    return json.dumps([{"name": "x", "value": "y", "expirationDate": expiration_date}])


class TestParseCookieExpiry:
    # ── Inputs that should return None ────────────────────────────────────────

    def test_empty_string_returns_none(self):
        assert _parse_cookie_expiry("") is None

    def test_whitespace_only_returns_none(self):
        assert _parse_cookie_expiry("   ") is None

    def test_invalid_json_returns_none(self):
        assert _parse_cookie_expiry("not json at all") is None

    def test_json_object_not_list_returns_none(self):
        assert _parse_cookie_expiry('{"name": "x"}') is None

    def test_empty_list_returns_none(self):
        assert _parse_cookie_expiry("[]") is None

    def test_cookie_without_expiration_date_key_returns_none(self):
        cookies = json.dumps([{"name": "session", "value": "abc"}])
        assert _parse_cookie_expiry(cookies) is None

    def test_null_expiration_date_returns_none(self):
        assert _parse_cookie_expiry(_cookies(None)) is None

    def test_string_expiration_date_returns_none(self):
        assert _parse_cookie_expiry(_cookies("not-a-number")) is None

    def test_list_expiration_date_returns_none(self):
        assert _parse_cookie_expiry(_cookies([1, 2, 3])) is None

    # ── Valid inputs ───────────────────────────────────────────────────────────

    def test_integer_timestamp_converts_correctly(self):
        # 1735689600 == 2025-01-01 00:00:00 UTC
        assert _parse_cookie_expiry(_cookies(1735689600)) == "2025-01-01 00:00:00"

    def test_float_timestamp_truncates_to_second(self):
        assert _parse_cookie_expiry(_cookies(1735689600.999)) == "2025-01-01 00:00:00"

    def test_epoch_zero_converts_to_unix_epoch(self):
        assert _parse_cookie_expiry(_cookies(0)) == "1970-01-01 00:00:00"

    def test_result_is_always_utc(self):
        # Verify format is YYYY-MM-DD HH:MM:SS (no timezone suffix)
        result = _parse_cookie_expiry(_cookies(1735689600))
        assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", result)

    # ── First-cookie-only behaviour ────────────────────────────────────────────

    def test_uses_first_cookie_only(self):
        cookies = json.dumps([
            {"name": "first",  "expirationDate": 1735689600},   # 2025-01-01
            {"name": "second", "expirationDate": 9_999_999_999}, # far future
        ])
        assert _parse_cookie_expiry(cookies) == "2025-01-01 00:00:00"

    def test_second_cookie_expiry_is_ignored(self):
        cookies = json.dumps([
            {"name": "first",  "expirationDate": 9_999_999_999},
            {"name": "second", "expirationDate": 0},
        ])
        result = _parse_cookie_expiry(cookies)
        assert result != "1970-01-01 00:00:00"  # would be wrong if it read second cookie

    def test_first_cookie_missing_expiry_returns_none_even_if_others_have_it(self):
        cookies = json.dumps([
            {"name": "first",  "value": "no expiry"},
            {"name": "second", "expirationDate": 1735689600},
        ])
        assert _parse_cookie_expiry(cookies) is None


# ── Edge / chaos / adversarial ─────────────────────────────────────────────────

class TestParseCookieExpiryEdgeCases:
    def test_boolean_false_expiration_returns_none(self):
        """JSON `false` must not be treated as timestamp 0."""
        assert _parse_cookie_expiry(_cookies(False)) is None

    def test_boolean_true_expiration_returns_none(self):
        """JSON `true` must not be treated as timestamp 1."""
        assert _parse_cookie_expiry(_cookies(True)) is None

    def test_negative_timestamp_returns_past_date(self):
        """Negative timestamps are valid pre-epoch dates."""
        result = _parse_cookie_expiry(_cookies(-1))
        assert result == "1969-12-31 23:59:59"

    def test_first_cookie_not_a_dict_returns_none(self):
        """Non-dict element at position 0 should not crash — return None."""
        assert _parse_cookie_expiry(json.dumps([42])) is None

    def test_dict_as_expiration_date_returns_none(self):
        """A nested object as expirationDate must return None, not crash."""
        assert _parse_cookie_expiry(_cookies({})) is None

    def test_very_large_timestamp_does_not_raise(self):
        """Year ~2286 timestamp should produce a valid date string."""
        result = _parse_cookie_expiry(_cookies(9_000_000_000))
        assert result is not None
        assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", result)

    def test_json_number_with_exponent_notation(self):
        """1e9 is valid JSON and a valid float timestamp."""
        result = _parse_cookie_expiry(json.dumps([{"expirationDate": 1e9}]))
        assert result is not None

    def test_none_raw_input_returns_none(self):
        """Passing Python None (not a string) must not crash."""
        assert _parse_cookie_expiry(None) is None

    def test_deeply_nested_first_cookie_returns_none(self):
        """Cookies that are a list of lists must not crash."""
        assert _parse_cookie_expiry(json.dumps([[{"expirationDate": 1}]])) is None
