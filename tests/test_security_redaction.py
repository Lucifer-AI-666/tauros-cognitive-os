from tauros.security import redact_obj, redact_text


def test_redact_kv_and_bearer():
    text = "Authorization: Bearer abcdef123456 and TAUROS_API_TOKEN=super-secret-token-value"
    red = redact_text(text)
    assert "abcdef123456" not in red
    assert "super-secret-token-value" not in red
    assert "[REDACTED]" in red


def test_redact_nested_dict_and_list():
    obj = {
        "api_token": "xyz",
        "nested": {"password": "p", "ok": "visible"},
        "list": [{"secret": "hide"}, "Authorization: Bearer abc.def.ghi"],
    }
    out = redact_obj(obj)
    assert out["api_token"] == "[REDACTED]"
    assert out["nested"]["password"] == "[REDACTED]"
    assert out["nested"]["ok"] == "visible"
    assert out["list"][0]["secret"] == "[REDACTED]"
    assert "abc.def.ghi" not in out["list"][1]


def test_redact_provider_keys():
    text = "sk-abcdefghijklmnopqrst sk-ant-abcdefghijklmnopqrst ghp_abcdefghijklmnopqrstuv"
    red = redact_text(text)
    assert "sk-abcdefghijklmnopqrst" not in red
    assert "ghp_abcdefghijklmnopqrstuv" not in red
