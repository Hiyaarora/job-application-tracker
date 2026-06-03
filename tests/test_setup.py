from jobagent import setup


def test_ensure_env_file_copies_example(tmp_path):
    example = tmp_path / ".env.example"
    example.write_text("GEMINI_API_KEY=\nSPREADSHEET_ID=\n")
    env = tmp_path / ".env"
    created = setup.ensure_env_file(env, example)
    assert created is True
    assert env.read_text() == example.read_text()


def test_ensure_env_file_no_overwrite(tmp_path):
    example = tmp_path / ".env.example"
    example.write_text("GEMINI_API_KEY=\n")
    env = tmp_path / ".env"
    env.write_text("GEMINI_API_KEY=existing\n")
    created = setup.ensure_env_file(env, example)
    assert created is False
    assert env.read_text() == "GEMINI_API_KEY=existing\n"


def test_set_env_var_updates_existing(tmp_path):
    env = tmp_path / ".env"
    env.write_text("GEMINI_API_KEY=\nSPREADSHEET_ID=abc\n")
    setup.set_env_var(env, "GEMINI_API_KEY", "newkey")
    text = env.read_text()
    assert "GEMINI_API_KEY=newkey" in text
    assert "SPREADSHEET_ID=abc" in text  # other lines preserved


def test_set_env_var_appends_when_missing(tmp_path):
    env = tmp_path / ".env"
    env.write_text("SPREADSHEET_ID=abc\n")
    setup.set_env_var(env, "GEMINI_API_KEY", "newkey")
    text = env.read_text()
    assert "GEMINI_API_KEY=newkey" in text
    assert "SPREADSHEET_ID=abc" in text


def test_set_env_var_preserves_comments(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# a comment\nGEMINI_API_KEY=old\n")
    setup.set_env_var(env, "GEMINI_API_KEY", "new")
    text = env.read_text()
    assert text.startswith("# a comment")
    assert "GEMINI_API_KEY=new" in text
