"""创作 SOP 化（IT-2）：选题→草稿生成 + 发布前规格校验。

两条能力：

1. **Builder**：基于选题库的标题方向/内容方向/关键词，按酒类内容 SOP 模板
   生成候选标题与正文草稿（不入库，仅供编辑后使用）。
2. **Checker**：对内容执行发布前全量校验——平台限制（标题/正文长度）、
   合规红线、SOP 结构（开头/主体/结尾/标签）、关键词覆盖。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from hermes.content_team.compliance import ComplianceReport, check_compliance
from hermes.content_team.models.content import Content
from hermes.content_team.models.platform import Platform
from hermes.content_team.models.topic import Topic

# ---------------------------------------------------------------------------
# 平台标题/正文长度限制（与适配器保持一致）
# ---------------------------------------------------------------------------

PLATFORM_TITLE_LIMIT: dict[Platform, int] = {
    Platform.WECHAT_OFFICIAL: 64,
    Platform.WECHAT_VIDEO: 64,
    Platform.DOUYIN: 55,
    Platform.XIAOHONGSHU: 20,
    Platform.BILIBILI: 80,
}

PLATFORM_BODY_LIMIT: dict[Platform, int] = {
    Platform.WECHAT_OFFICIAL: 20000,
    Platform.WECHAT_VIDEO: 20000,
    Platform.DOUYIN: 5000,
    Platform.XIAOHONGSHU: 1000,
    Platform.BILIBILI: 2000,
}


# ---------------------------------------------------------------------------
# Builder：选题 → 草稿
# ---------------------------------------------------------------------------


def _split_lines(text: str) -> list[str]:
    """按行切分，过滤空行。"""
    return [line.strip() for line in text.splitlines() if line.strip()]


def _hashtag_variants(keywords: list[str]) -> list[str]:
    """为关键词生成标签候选：原词 + 去空格版。"""
    tags: list[str] = []
    for kw in keywords:
        tags.append(kw)
        compact = kw.replace(" ", "")
        if compact != kw:
            tags.append(compact)
    return tags


# ---------------------------------------------------------------------------
# 标题机制库（SOP Builder v2 · 内化自热门内容方法论）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TitleMechanism:
    """一个经过验证的标题机制模板。

    占位符：``{base}`` = 选题标题，``{kw}`` = 首个关键词。
    """

    mech_id: str
    name: str
    template: str
    note: str


TITLE_MECHANISMS: tuple[TitleMechanism, ...] = (
    TitleMechanism(
        "list",
        "清单型",
        "{base}｜{kw}的4个要点",
        "清单结构收藏率高",
    ),
    TitleMechanism(
        "scene",
        "场景代入型",
        "下班后的微醺时刻｜{base}",
        "绑定使用场景提升代入感",
    ),
    TitleMechanism(
        "counterintuitive",
        "反常识型",
        "调了30杯才敢推荐的{base}",
        "亲测背书，降低 AI 感",
    ),
    TitleMechanism(
        "identity",
        "身份认同型",
        "第一次买{kw}的人看过来｜{base}",
        "点名目标人群提升点击",
    ),
    TitleMechanism(
        "contrast",
        "对比型",
        "平价vs进阶｜{base}怎么选",
        "对比结构引发讨论",
    ),
    TitleMechanism(
        "step",
        "教程型",
        "3步搞定{base}｜{kw}实操",
        "低门槛行动指令",
    ),
)


def _mechanism_candidates(
    topic: Topic, limit: int
) -> list[tuple[str, TitleMechanism]]:
    """按机制库生成候选标题（截断+去重），返回 (title, mechanism)。"""
    base = topic.title.strip() or "今日调酒"
    kws = topic.keywords or []
    kw = kws[0].strip() if kws and kws[0].strip() else "居家调酒"

    seen: set[str] = set()
    out: list[tuple[str, TitleMechanism]] = []
    for mech in TITLE_MECHANISMS:
        title = _truncate(mech.template.format(base=base, kw=kw), limit)
        if title and title not in seen:
            seen.add(title)
            out.append((title, mech))
    return out


def build_draft(topic: Topic, platform: Platform = Platform.XIAOHONGSHU) -> "Draft":
    """基于选题生成内容草稿（标题候选 + 正文 + 标签）。

    生成策略（酒类内容 SOP）：
    - 标题：按标题机制库生成多机制候选（带机制标注），并按平台长度截断。
    - 正文：开头钩子 + 内容方向要点 + 结尾互动引导。
    - 标签：从选题关键词派生。
    """
    title_limit = PLATFORM_TITLE_LIMIT.get(platform, 20)
    body_limit = PLATFORM_BODY_LIMIT.get(platform, 1000)

    pairs = _mechanism_candidates(topic, title_limit)
    candidates = [t for t, _ in pairs]
    detailed = [
        {
            "title": t,
            "mechanism": mech.mech_id,
            "mechanism_name": mech.name,
            "note": mech.note,
        }
        for t, mech in pairs
    ]
    body = _build_body(topic, body_limit)
    hashtags = _hashtag_variants(topic.keywords or [])

    return Draft(
        title=candidates[0] if candidates else topic.title,
        title_candidates=candidates,
        title_candidates_detailed=detailed,
        body=body,
        hashtags=hashtags,
        platform=platform.value,
        title_limit=title_limit,
        body_limit=body_limit,
    )


def _build_body(topic: Topic, limit: int) -> str:
    """按 SOP 结构生成正文：开头 + 要点 + 结尾。"""
    kws = topic.keywords or []
    desc_lines = _split_lines(topic.description or "")

    parts: list[str] = []

    # 开头钩子
    if desc_lines:
        parts.append(desc_lines[0])
    else:
        parts.append(f"今天来聊聊「{topic.title}」。")
    parts.append("")

    # 主体要点
    if len(desc_lines) > 1:
        for line in desc_lines[1:]:
            parts.append(f"- {line}")
        parts.append("")

    # 关键词自然植入
    if kws:
        parts.append(f"关键词：{'、'.join(kws)}")
        parts.append("")

    # 结尾互动引导
    parts.append("你最喜欢哪一款？评论区告诉我 👇")
    parts.append("")

    body = "\n".join(parts).strip()
    return _truncate(body, limit, ellipsis=False)


def _truncate(text: str, limit: int, ellipsis: bool = True) -> str:
    """按字符数截断文本（中文按字符计）。"""
    if len(text) <= limit:
        return text
    if ellipsis and limit > 3:
        return text[: limit - 1] + "…"
    return text[:limit]


# ---------------------------------------------------------------------------
# Checker：发布前全量校验
# ---------------------------------------------------------------------------


def check_content(
    content: Content,
    platform: Platform = Platform.XIAOHONGSHU,
    topic: Topic | None = None,
) -> "ContentCheckResult":
    """对内容执行发布前全量校验。

    校验维度：
    - 平台限制（标题/正文长度）
    - 合规红线
    - SOP 结构（段落数、标签、关键词覆盖）
    """
    title_limit = PLATFORM_TITLE_LIMIT.get(platform, 20)
    body_limit = PLATFORM_BODY_LIMIT.get(platform, 1000)

    platform_errors = _check_platform_limits(content, title_limit, body_limit)
    compliance = check_compliance(
        content.title, content.body, platform=platform.value
    )
    sop_warnings = _check_sop_structure(content, title_limit)
    sop_warnings += _check_ai_flavor(content)
    keyword_coverage = _check_keyword_coverage(content, topic)

    all_blocking = list(platform_errors)
    if not compliance.passed:
        all_blocking.append(f"合规红线: {compliance.summary()}")

    return ContentCheckResult(
        passed=len(all_blocking) == 0 and len(sop_warnings) == 0,
        platform_errors=platform_errors,
        blocking=all_blocking,
        compliance=compliance,
        sop_warnings=sop_warnings,
        keyword_coverage=keyword_coverage,
    )


def _check_platform_limits(
    content: Content, title_limit: int, body_limit: int
) -> list[str]:
    errors: list[str] = []
    if len(content.title) > title_limit:
        errors.append(
            f"标题超过 {title_limit} 字限制（当前 {len(content.title)} 字）"
        )
    if len(content.body) > body_limit:
        errors.append(
            f"正文超过 {body_limit} 字限制（当前 {len(content.body)} 字）"
        )
    return errors


def _check_sop_structure(content: Content, title_limit: int) -> list[str]:
    warnings: list[str] = []
    body = content.body or ""

    # 段落数：至少 2 段（开头 + 要点/结尾）
    paragraphs = [p for p in re.split(r"\n\s*\n", body.strip()) if p.strip()]
    if len(paragraphs) < 2:
        warnings.append("正文结构偏短，建议包含开头钩子 + 要点/结尾两段以上")

    # 标签：建议 3-8 个
    hashtags = re.findall(r"#(\S+)", body)
    if not hashtags:
        warnings.append("缺少话题标签（#标签），建议添加 3-8 个")
    elif len(hashtags) < 3:
        warnings.append(f"话题标签偏少（{len(hashtags)} 个），建议 3-8 个")

    # 标题非空且在限制内
    if not content.title.strip():
        warnings.append("标题为空")
    elif len(content.title) >= title_limit:
        warnings.append(f"标题接近 {title_limit} 字上限，发布前请确认")

    return warnings


def _check_keyword_coverage(
    content: Content, topic: Topic | None
) -> dict[str, bool]:
    """检查选题关键词在内容中的覆盖情况。"""
    if not topic or not topic.keywords:
        return {}
    text = f"{content.title}\n{content.body}"
    return {kw: kw in text for kw in topic.keywords}


# ---------------------------------------------------------------------------
# 去 AI 味检查（SOP Checker v2）
# ---------------------------------------------------------------------------

# 常见 AI 生成腔调标记词（套话/空洞程度词/模板连接词）
_AI_FLAVOR_MARKERS: tuple[str, ...] = (
    "首先",
    "其次",
    "再次",
    "综上所述",
    "总而言之",
    "总的来说",
    "值得注意的是",
    "不得不承认",
    "让我们一起",
    "在这个快节奏",
    "当今社会",
    "赋能",
    "完美呈现",
    "尽在掌握",
    "非常非常",
)

# emoji 区段（涵盖常用 emoji 与符号块）
_EMOJI_RE = re.compile(r"[\U0001F000-\U0001FAFF\u2600-\u27BF]")


def _check_ai_flavor(content: Content) -> list[str]:
    """AI 味检查：模板腔/空洞词/emoji 堆砌，返回警示列表。"""
    warnings: list[str] = []
    body = content.body or ""
    text = f"{content.title}{body}"

    for marker in _AI_FLAVOR_MARKERS:
        n = text.count(marker)
        if n > 0:
            warnings.append(
                f"疑似AI腔「{marker}」出现{n}次，建议口语化改写"
            )

    emojis = _EMOJI_RE.findall(body)
    if len(emojis) > 6:
        warnings.append(
            f"emoji 堆砌（{len(emojis)} 个），建议控制在 6 个以内"
        )

    return warnings


# ---------------------------------------------------------------------------
# 结果数据类
# ---------------------------------------------------------------------------


@dataclass
class Draft:
    """Builder 生成的草稿（不入库，供前端编辑）。"""

    title: str
    title_candidates: list[str]
    body: str
    hashtags: list[str]
    platform: str
    title_limit: int
    body_limit: int
    title_candidates_detailed: list[dict] = field(default_factory=list)
    # 草稿来源：template=确定性模板，llm=LLM 生成（可能回退）
    source: str = "template"


@dataclass
class ContentCheckResult:
    """Checker 的全量校验结果。"""

    passed: bool
    platform_errors: list[str]
    blocking: list[str]
    compliance: ComplianceReport
    sop_warnings: list[str]
    keyword_coverage: dict[str, bool]

    @property
    def compliance_passed(self) -> bool:
        return self.compliance.passed
