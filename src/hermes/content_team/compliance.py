"""发布合规检查单（IT-2 合规红线）。

针对酒类内容的平台红线与广告法敏感点，提供基于关键词的自动检查：

- ``BLOCK`` 红线：命中即默认禁止发布（可人工确认后强制发布）
- ``WARN`` 警示：命中仅提示，不阻塞发布

规则来源：广告法（绝对化用语、医疗功效）、未成年人保护、酒类广告规范
（不得诱导无节制饮酒/酒后驾驶）、平台导流规则。
"""
from __future__ import annotations

from dataclasses import dataclass, field

SEVERITY_BLOCK = "BLOCK"
SEVERITY_WARN = "WARN"


@dataclass(frozen=True)
class ComplianceRule:
    """一条合规规则。"""

    rule_id: str
    name: str
    severity: str
    keywords: tuple[str, ...]
    message: str


@dataclass(frozen=True)
class ComplianceHit:
    """一次规则命中。"""

    rule_id: str
    rule_name: str
    severity: str
    keyword: str
    source: str
    position: int


@dataclass(frozen=True)
class ComplianceReport:
    """一次合规检查的报告。"""

    title: str
    body: str
    blocking: list[ComplianceHit] = field(default_factory=list)
    warnings: list[ComplianceHit] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """是否通过检查（无红线命中）。"""
        return not self.blocking

    @property
    def all_hits(self) -> list[ComplianceHit]:
        return self.blocking + self.warnings

    def summary(self) -> str:
        """一行摘要，用于错误信息与日志。"""
        if self.passed:
            return "合规检查通过"
        red = [f"{h.keyword}({h.rule_name})" for h in self.blocking]
        return "命中合规红线: " + "、".join(red)


RULES: tuple[ComplianceRule, ...] = (
    ComplianceRule(
        rule_id="minors",
        name="未成年人保护",
        severity=SEVERITY_BLOCK,
        keywords=("未成年人", "未成年", "儿童", "小朋友", "小孩", "学生", "青少年"),
        message="酒类内容不得面向或诱导未成年人",
    ),
    ComplianceRule(
        rule_id="medical_claims",
        name="医疗保健功效",
        severity=SEVERITY_BLOCK,
        keywords=(
            "治病",
            "保健",
            "养生",
            "治疗",
            "疗效",
            "治愈",
            "抗衰老",
            "美容养颜",
            "缓解",
            "预防",
        ),
        message="酒类内容不得宣称医疗或保健功效",
    ),
    ComplianceRule(
        rule_id="excessive_drinking",
        name="无节制饮酒",
        severity=SEVERITY_BLOCK,
        keywords=("劝酒", "拼酒", "灌酒", "千杯不醉", "一饮而尽", "酒量比拼", "喝倒"),
        message="不得诱导、怂恿无节制饮酒",
    ),
    ComplianceRule(
        rule_id="drunk_driving",
        name="酒后驾驶",
        severity=SEVERITY_BLOCK,
        keywords=("酒驾", "酒后驾驶", "喝完酒开车", "边喝边开", "醉驾"),
        message="不得出现酒后驾驶相关表述",
    ),
    ComplianceRule(
        rule_id="absolute_claims",
        name="绝对化用语",
        severity=SEVERITY_BLOCK,
        keywords=(
            "国家级",
            "最佳",
            "最好",
            "最优",
            "顶级",
            "极致",
            "独一无二",
            "绝无仅有",
            "第一品牌",
            "全网第一",
        ),
        message="广告法禁止绝对化用语",
    ),
    ComplianceRule(
        rule_id="diversion",
        name="站外导流",
        severity=SEVERITY_WARN,
        keywords=("加微信", "加我微信", "微信号", "扫码", "加群", "二维码", "私信我"),
        message="平台可能限制站外导流，发布前请确认",
    ),
    ComplianceRule(
        rule_id="bare_most",
        name="「最」字用语",
        severity=SEVERITY_WARN,
        keywords=("最",),
        message="「最」可能触发绝对化用语审查，请确认是否为主观表达",
    ),
)


def _scan(text: str, source: str) -> list[ComplianceHit]:
    hits: list[ComplianceHit] = []
    for rule in RULES:
        for kw in rule.keywords:
            start = 0
            while True:
                idx = text.find(kw, start)
                if idx == -1:
                    break
                hits.append(
                    ComplianceHit(
                        rule_id=rule.rule_id,
                        rule_name=rule.name,
                        severity=rule.severity,
                        keyword=kw,
                        source=source,
                        position=idx,
                    )
                )
                start = idx + len(kw)
    return hits


def check_compliance(title: str, body: str) -> ComplianceReport:
    """对标题与正文执行合规检查，返回报告。"""
    title_hits = _scan(title, "title")
    body_hits = _scan(body, "body")
    all_hits = title_hits + body_hits
    return ComplianceReport(
        title=title,
        body=body,
        blocking=[h for h in all_hits if h.severity == SEVERITY_BLOCK],
        warnings=[h for h in all_hits if h.severity == SEVERITY_WARN],
    )


class ComplianceBlockedError(Exception):
    """发布被合规红线拦截。"""

    def __init__(self, report: ComplianceReport) -> None:
        self.report = report
        super().__init__(report.summary())
