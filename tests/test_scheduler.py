from jobagent import scheduler


def test_plist_content_has_schedule_and_command():
    xml = scheduler.plist_content(
        label="com.test.jobagent",
        python="/venv/bin/python",
        main_py="/proj/main.py",
        project_dir="/proj",
        log_path="/logs/daily.log",
        hour=9, minute=30,
    )
    assert "com.test.jobagent" in xml
    assert "/venv/bin/python" in xml
    assert "/proj/main.py" in xml
    assert "<string>update</string>" in xml
    assert "<key>Hour</key>" in xml and "<integer>9</integer>" in xml
    assert "<key>Minute</key>" in xml and "<integer>30</integer>" in xml
    assert "/proj" in xml          # WorkingDirectory so .env loads
    assert "/logs/daily.log" in xml


def test_parse_time_valid():
    assert scheduler.parse_time("09:30") == (9, 30)
    assert scheduler.parse_time("23:05") == (23, 5)


def test_parse_time_invalid():
    import pytest
    for bad in ("9am", "25:00", "10:75", "abc"):
        with pytest.raises(ValueError):
            scheduler.parse_time(bad)
