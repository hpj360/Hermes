"""合规检查单单元测试（IT-2 合规红线）。"""
from __future__ import annotations

from hermes.content_team.compliance import (
    SEVERITY_BLOCK,
    SEVERITY_WARN,
    ComplianceBlockedError,
    check_compliance,
)


def test_clean_content_passes():
    report = check_compliance("居家调酒指南", "今晚用金酒调一杯金汤力")
    assert report.passed is True
    assert report.blocking == []
    assert report.warnings == []


def test_minors_blocks():
    report = check_compliance("未成年人勿饮酒", "未成年人请在家长陪同下阅读")
    assert report.passed is False
    rule_ids = {h.rule_id for h in report.blocking}
    assert "minors" in rule_ids
    assert report.summary().startswith("命中合规红线")


def test_medical_claims_blocks_in_body():
    report = check_compliance("红酒推荐", "每晚一杯，保健效果显著")
    assert report.passed is False
    assert {"medical_claims"} == {h.rule_id for h in report.blocking}
    assert all(h.source == "body" for h in report.blocking)


def test_absolute_claims_blocks_in_title():
    report = check_compliance("全网第一的威士忌", "普通正文")
    assert report.passed is False
    assert "absolute_claims" in {h.rule_id for h in report.blocking}
    assert report.blocking[0].source == "title"


def test_warnings_do_not_block():
    report = check_compliance("扫码加群领优惠", "性价比最高")
    assert report.passed is True
    assert len(report.blocking) == 0
    assert any(h.rule_id == "diversion" for h in report.warnings)
    assert any(h.rule_id == "bare_most" for h in report.warnings)


def test_position_and_keyword_recorded():
    report = check_compliance("禁止劝酒，理性饮酒", "正文")
    hits = [h for h in report.blocking if h.rule_id == "excessive_drinking"]
    assert hits
    assert hits[0].keyword == "劝酒"
    assert hits[0].source == "title"
    assert hits[0].position == report.title.find("劝酒")


def test_compliance_blocked_error_holds_report():
    report = check_compliance("酒驾害人", "正文")
    err = ComplianceBlockedError(report)
    assert err.report is report
    assert "合规红线" in str(err)
    assert "酒驾" in str(err)


def test_all_block_rules_exposed():
    from hermes.content_team.compliance import RULES

    severities = {r.severity for r in RULES}
    assert SEVERITY_BLOCK in severities
    assert SEVERITY_WARN in severities
    assert all(r.keywords for r in RULES)


def test_empty_body_ok():
    report = check_compliance("金汤力三步调法", "")
    assert report.passed is True
