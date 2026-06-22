from polily.doctor.model import CheckResult, Severity, severity_exit_code, worst_severity


def test_severity_exit_code_mapping():
    assert severity_exit_code([Severity.OK, Severity.INFO, Severity.SKIPPED]) == 0
    assert severity_exit_code([Severity.OK, Severity.WARN]) == 1
    assert severity_exit_code([Severity.WARN, Severity.CRITICAL]) == 3
    assert severity_exit_code([]) == 0


def test_worst_severity():
    assert worst_severity([
        CheckResult(id="a", title="A", severity=Severity.OK, group="g"),
        CheckResult(id="b", title="B", severity=Severity.WARN, group="g"),
    ]) == Severity.WARN


def test_checkresult_json_roundtrips():
    r = CheckResult(id="x.y", title="T", severity=Severity.CRITICAL,
                    detail="d", value={"n": 1}, fix_hint="do x", group="g")
    dumped = r.model_dump(mode="json")
    assert dumped["severity"] == "critical"
    assert dumped["value"] == {"n": 1}
