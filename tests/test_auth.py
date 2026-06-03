from jobagent import auth, config


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "KEY_FILE", tmp_path / "key")
    monkeypatch.setattr(config, "TOKEN_FILE", tmp_path / "token.enc")


def test_token_encrypt_decrypt_roundtrip(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    payload = {"token": "abc", "refresh_token": "xyz"}
    auth._save_encrypted(payload)
    loaded = auth._load_encrypted()
    assert loaded == payload


def test_key_file_permissions_are_private(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    auth._save_encrypted({"a": 1})
    mode = (tmp_path / "key").stat().st_mode & 0o777
    assert mode == 0o600


def test_load_returns_none_when_no_token(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    assert auth._load_encrypted() is None
