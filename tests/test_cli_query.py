from jobagent import cli, config


def test_application_query_default():
    assert cli.application_query() == config.APPLICATION_QUERY


def test_application_query_scoped_to_company():
    q = cli.application_query("Deutsche Bank")
    assert q.startswith("(") and config.APPLICATION_QUERY in q
    assert '"Deutsche Bank"' in q          # company name AND-ed onto the query
