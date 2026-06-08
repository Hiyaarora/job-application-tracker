from jobagent import evals


def test_normalize_company():
    assert evals.norm_company("Akamai Technologies, Inc.") == "akamai"
    assert evals.norm_company("Deutsche Bank") == "deutsche bank"
    assert evals.norm_company(None) == ""


def test_company_match():
    assert evals.company_match("Deutsche Bank", "deutsche bank") is True
    assert evals.company_match("Akamai Technologies", "Akamai") is True
    assert evals.company_match("GitLab", "Postman") is False


def test_role_match_fuzzy():
    assert evals.role_match("Software Engineer II", "software engineer ii") is True
    assert evals.role_match("Process Reengineer, NCT", "Process Reengineer NCT") is True
    assert evals.role_match("QA Engineer", "Data Analyst") is False
    assert evals.role_match(None, None) is True
    assert evals.role_match("QA Engineer", None) is False


def test_status_match_exact():
    assert evals.status_match("Rejected", "Rejected") is True
    assert evals.status_match("Rejected", "Applied") is False


def test_prf_basic():
    p, r, f1 = evals.prf([True, True, False, False], [True, False, False, True])
    assert round(p, 2) == 0.5 and round(r, 2) == 0.5 and round(f1, 2) == 0.5


def test_confusion_matrix():
    cm = evals.confusion_matrix(
        ["Applied", "Rejected", "Rejected"],
        ["Applied", "Applied", "Rejected"],
        labels=["Applied", "Rejected"],
    )
    assert cm["Rejected"]["Applied"] == 1
    assert cm["Rejected"]["Rejected"] == 1
    assert cm["Applied"]["Applied"] == 1


def test_load_dataset_parses_and_skips_bad_lines(tmp_path):
    p = tmp_path / "ds.jsonl"
    p.write_text(
        '{"id": "a", "email": {"subject": "hi"}, "expected": {"is_job_application": true}}\n'
        'not-json\n'
        '\n'
        '{"id": "b", "email": {"subject": "yo"}, "expected": {"is_job_application": false}}\n'
    )
    cases = evals.load_dataset(p)
    assert [c["id"] for c in cases] == ["a", "b"]


def test_get_extraction_records_then_reads_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(evals, "CACHE_DIR", tmp_path)
    calls = []

    def fake_extractor(email):
        calls.append(email["subject"])
        return {"is_job_application": True, "company": "Acme", "role": "QA",
                "status": "Applied", "confidence": 0.9}

    case = {"id": "x1", "email": {"subject": "hi"}}
    r1 = evals.get_extraction(case, live=True, extractor=fake_extractor)
    assert r1["company"] == "Acme" and calls == ["hi"]
    r2 = evals.get_extraction(case, live=False, extractor=fake_extractor)
    assert r2 == r1 and calls == ["hi"]


def test_get_extraction_missing_cache_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(evals, "CACHE_DIR", tmp_path)
    case = {"id": "missing", "email": {"subject": "hi"}}
    assert evals.get_extraction(case, live=False, extractor=lambda e: {}) is None


def test_score_extraction_survives_live_quota_error(tmp_path, monkeypatch):
    # A quota/transient error during --live must NOT crash: stop hitting the API,
    # score whatever is already cached, and skip the rest.
    monkeypatch.setattr(evals, "CACHE_DIR", tmp_path)
    cached = {"id": "done", "email": {"subject": "thanks for applying"},
              "expected": {"is_job_application": True, "company": "Acme", "role": "QA", "status": "Applied"}}
    evals.get_extraction(cached, live=True,
                         extractor=lambda e: {"is_job_application": True, "company": "Acme",
                                              "role": "QA", "status": "Applied", "confidence": 0.9})
    pending = {"id": "pending", "email": {"subject": "thanks for applying"},
               "expected": {"is_job_application": True, "company": "Beta", "role": "X", "status": "Applied"}}

    def boom(email):
        raise Exception("429 You exceeded your current quota")

    res = evals._score_extraction([cached, pending], live=True, extractor=boom)
    assert res["scored"] == 1          # the cached one was scored
    assert res["skipped"] == 1         # the pending one skipped, no crash


def test_run_evals_scores_filters_and_extraction(tmp_path, monkeypatch):
    monkeypatch.setattr(evals, "CACHE_DIR", tmp_path / "cache")
    ds = tmp_path / "ds.jsonl"
    ds.write_text(
        '{"id":"rej","category":"rejection",'
        '"email":{"sender":"db@x.com","subject":"your application update","body":"thank you for your interest. unfortunately we are not progressing with your application"},'
        '"expected":{"is_job_application":true,"company":"Deutsche Bank","role":"PR NCT","status":"Rejected"},'
        '"filters":{"is_noise":false,"is_job_candidate":true,"priority":1}}\n'
        '{"id":"otp","category":"noise",'
        '"email":{"sender":"x@x.com","subject":"Your verification code","body":"otp"},'
        '"expected":{"is_job_application":false,"company":null,"role":null,"status":"Applied"},'
        '"filters":{"is_noise":true,"is_job_candidate":false,"priority":0}}\n'
    )

    def fake_extractor(email):
        return {"is_job_application": True, "company": "Deutsche Bank",
                "role": "PR NCT", "status": "Rejected", "confidence": 0.95}

    result = evals.run_evals(dataset_path=ds, live=True, extractor=fake_extractor)
    assert result["filters"]["passed"] == result["filters"]["total"]
    assert result["extraction"]["status_accuracy"] == 1.0
    assert result["extraction"]["scored"] == 1
    assert "EXTRACTION" in result["report"]
