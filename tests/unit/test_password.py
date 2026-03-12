"""
Unit tests for hash_password() and verify_password() in db.py.
These are pure functions with no I/O or external dependencies.
"""

import re

import pytest

from db import hash_password, verify_password


class TestHashPassword:
    def test_returns_two_nonempty_strings(self):
        hashed, salt = hash_password("secret")
        assert hashed and salt

    def test_both_values_are_hex_strings(self):
        hashed, salt = hash_password("secret")
        assert re.fullmatch(r"[0-9a-f]+", hashed), f"hashed is not hex: {hashed!r}"
        assert re.fullmatch(r"[0-9a-f]+", salt),   f"salt is not hex: {salt!r}"

    def test_hash_length_is_consistent_regardless_of_input_length(self):
        h_short, _ = hash_password("x")
        h_long,  _ = hash_password("x" * 10_000)
        assert len(h_short) == len(h_long)

    def test_same_password_same_salt_produces_same_hash(self):
        h1, _ = hash_password("pw", "fixed")
        h2, _ = hash_password("pw", "fixed")
        assert h1 == h2

    def test_same_password_different_salts_produce_different_hashes(self):
        h1, _ = hash_password("pw", "salt_a")
        h2, _ = hash_password("pw", "salt_b")
        assert h1 != h2

    def test_different_passwords_same_salt_produce_different_hashes(self):
        h1, _ = hash_password("pw_one", "same")
        h2, _ = hash_password("pw_two", "same")
        assert h1 != h2

    def test_provided_salt_is_returned_unchanged(self):
        _, returned = hash_password("pw", "my_exact_salt")
        assert returned == "my_exact_salt"

    def test_random_salt_is_generated_when_not_provided(self):
        _, s1 = hash_password("pw")
        _, s2 = hash_password("pw")
        assert s1 != s2  # collision probability is negligible

    def test_empty_password_is_hashable(self):
        hashed, salt = hash_password("")
        assert hashed and salt

    def test_unicode_password_is_hashable(self):
        hashed, salt = hash_password("pässwörð‽")
        assert hashed and salt

    def test_password_with_spaces_is_hashable(self):
        hashed, salt = hash_password("  spaces  ")
        assert hashed and salt


class TestVerifyPassword:
    def test_correct_password_returns_true(self):
        hashed, salt = hash_password("correct")
        assert verify_password("correct", hashed, salt) is True

    def test_wrong_password_returns_false(self):
        hashed, salt = hash_password("correct")
        assert verify_password("notcorrect", hashed, salt) is False

    def test_empty_string_matches_empty_hash(self):
        hashed, salt = hash_password("")
        assert verify_password("", hashed, salt) is True

    def test_empty_string_does_not_match_nonempty_hash(self):
        hashed, salt = hash_password("secret")
        assert verify_password("", hashed, salt) is False

    def test_nonempty_does_not_match_empty_hash(self):
        hashed, salt = hash_password("")
        assert verify_password("something", hashed, salt) is False

    def test_wrong_salt_returns_false(self):
        hashed, _ = hash_password("pw", "correct_salt")
        assert verify_password("pw", hashed, "wrong_salt") is False

    def test_case_sensitive_password(self):
        hashed, salt = hash_password("Secret")
        assert verify_password("Secret", hashed, salt) is True
        assert verify_password("secret", hashed, salt) is False

    def test_unicode_password_round_trips(self):
        hashed, salt = hash_password("pässwörð‽")
        assert verify_password("pässwörð‽", hashed, salt) is True
        assert verify_password("password",  hashed, salt) is False

    def test_password_with_spaces_round_trips(self):
        hashed, salt = hash_password("pass word")
        assert verify_password("pass word", hashed, salt) is True
        assert verify_password("password",  hashed, salt) is False


# ── Edge / chaos / adversarial ────────────────────────────────────────────────

class TestHashPasswordEdgeCases:
    def test_empty_string_salt_is_used_as_is(self):
        """salt='' is a valid (if weak) salt — must be deterministic."""
        h1, s1 = hash_password("pw", "")
        h2, s2 = hash_password("pw", "")
        assert h1 == h2
        assert s1 == s2 == ""

    def test_hash_differs_from_both_plaintext_and_salt(self):
        """Hashed output must not equal the plaintext or salt."""
        hashed, salt = hash_password("secret", "mysalt")
        assert hashed != "secret"
        assert hashed != "mysalt"

    def test_near_match_hash_returns_false(self):
        """One-character flip in the stored hash must not verify."""
        hashed, salt = hash_password("correct")
        last = hashed[-1]
        tampered = hashed[:-1] + ("0" if last != "0" else "1")
        assert verify_password("correct", tampered, salt) is False

    def test_very_long_password_is_hashable(self):
        pw = "x" * 100_000
        hashed, salt = hash_password(pw)
        assert verify_password(pw, hashed, salt) is True
        assert verify_password("x", hashed, salt) is False

    def test_password_with_null_bytes_is_hashable(self):
        """encode() at UTF-8 will embed null bytes; must not crash."""
        hashed, salt = hash_password("pw\x00null")
        assert verify_password("pw\x00null", hashed, salt) is True
        assert verify_password("pw", hashed, salt) is False
