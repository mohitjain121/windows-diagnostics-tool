from pcdiag.rules import Confidence, Evidence, Finding, Severity
from pcdiag.score import health_score


def _finding(sev, conf):
    return Finding(id="x", title="t", category="c", severity=sev,
                   confidence=conf, evidence=[], recommendation="r")


def test_health_score_full_when_no_findings():
    assert health_score([]) == 100


def test_health_score_deducts_severity_times_confidence():
    findings = [_finding(Severity.CRITICAL, Confidence.HIGH)]  # 40 * 1.0
    assert health_score(findings) == 60


def test_health_score_floors_at_zero():
    findings = [_finding(Severity.CRITICAL, Confidence.HIGH)] * 5
    assert health_score(findings) == 0
