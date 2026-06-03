from jobagent import config


def test_scopes_only_what_we_use():
    assert config.SCOPES == [
        "openid",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/spreadsheets",
    ]


def test_statuses_defined():
    assert config.STATUSES == [
        "Applied", "In Review", "Interview Scheduled", "Rejected", "Offer",
    ]


def test_app_dir_under_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    import importlib
    importlib.reload(config)
    assert str(config.APP_DIR).startswith(str(tmp_path))
