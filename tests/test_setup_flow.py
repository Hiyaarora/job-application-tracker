from jobagent import setup


def test_run_setup_flow_creates_env_and_opens_pages(tmp_path):
    # Pretend the user already downloaded their OAuth secrets.
    (tmp_path / "client_secret.json").write_text("{}")
    (tmp_path / ".env.example").write_text("GEMINI_API_KEY=\nSPREADSHEET_ID=\n")

    opened = []
    # Enter (x5 page steps), then 'n' to skip Gemini, 'n' to skip login.
    answers = iter(["", "", "", "", "", "n", "n"])

    setup.run_setup(
        tmp_path,
        opener=lambda url: opened.append(url),
        prompt=lambda _msg: next(answers),
        out=lambda *_a, **_k: None,
    )

    assert (tmp_path / ".env").exists()              # .env created from template
    assert setup.URL_NEW_PROJECT in opened           # project page opened
    assert setup.URL_ENABLE_GMAIL in opened          # gmail enable opened
    assert setup.URL_ENABLE_SHEETS in opened         # sheets enable opened
    assert setup.URL_CONSENT in opened               # consent screen opened
    assert setup.URL_CREDENTIALS in opened           # credentials opened
