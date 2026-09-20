import pytest

from tauros.security import assert_strong_token, generate_api_token, is_weak_token


def test_generated_token_is_strong():
    token = generate_api_token()
    assert not is_weak_token(token)
    assert_strong_token(token)


def test_weak_and_repetitive_tokens_rejected():
    assert is_weak_token("")
    assert is_weak_token("short")
    assert is_weak_token("change-me-now")
    assert is_weak_token("a" * 30)
    with pytest.raises(Exception):
        assert_strong_token("a" * 32)
