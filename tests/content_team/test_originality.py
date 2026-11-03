"""机器原创性检查测试（字面层 / API）。"""
from __future__ import annotations

from hermes.content_team.originality import (
    OriginalityRef,
    _normalize,
    check_originality,
)


def test_normalize_strips_punct_and_lowercases():
    assert _normalize("Hello, 世界！ Go-Go") == "hello世界gogo"


def test_identical_content_flags():
    refs = [
        OriginalityRef(
            ref_type="content",
            ref_id="11111111-1111-1111-1111-111111111111",
            ref_title="金汤力入门",
            text="今天分享一款最简单的居家调酒：金酒加汤力水，加冰搅拌，挤一片柠檬就完成，微醺刚刚好",
        )
    ]
    hits = check_originality(
        "金汤力入门",
        "今天分享一款最简单的居家调酒：金酒加汤力水，加冰搅拌，挤一片柠檬就完成，微醺刚刚好",
        refs,
    )
    assert len(hits) == 1
    assert hits[0].ref_type == "content"
    assert hits[0].similarity >= 0.2
    assert len(hits[0].longest_common_run) >= 8


def test_distinct_content_passes():
    refs = [
        OriginalityRef(
            ref_type="content",
            ref_id="22222222-2222-2222-2222-222222222222",
            ref_title="完全不同的内容",
            text="威士忌的风味来自橡木桶陈酿过程",
        )
    ]
    hits = check_originality(
        "金汤力入门",
        "金汤力的做法：金酒、汤力水、青柠角与冰块，杯子先装满冰",
        refs,
    )
    assert hits == []


def test_min_similarity_threshold_respected():
    body = (
        "今天来分享居家调酒的入门方法，先从最简单的金汤力开始说起，"
        "准备金酒与汤力水，按一比三比例加入装满冰块的杯中，轻轻搅拌即可"
    )
    refs = [
        OriginalityRef(
            "content",
            "0" * 36,
            "相似参考",
            body,  # 与 body 完全相同 → sim=1.0
        )
    ]
    strict = check_originality("居家调酒入门", body, refs, min_similarity=0.9999)
    assert strict == []  # 阈值极端高（>实际相似度）时不误报
    loose = check_originality("居家调酒入门", body, refs, min_similarity=0.2)
    assert len(loose) == 1
    assert loose[0].similarity >= 0.5  # 正文全同，仅参考标题不同


def test_reference_capped_results():
    base = "这是一段比较长的通用参考文本" * 8
    refs = [
        OriginalityRef(
            ref_type="content",
            ref_id=str(i),
            ref_title=f"重复参考{i}",
            text=base,
        )
        for i in range(10)
    ]
    hits = check_originality(
        "随意标题只要够长就行",
        base + "补充一点不同",
        refs,
    )
    assert 0 < len(hits) <= 5


async def test_originality_endpoint_flags_duplicate(client):
    """POST /api/originality/check 与库内内容高度相似时命中。"""
    src = await client.post(
        "/api/content",
        json={
            "title": "金汤力入门",
            "body": "今天分享一款最简单的居家调酒：金酒加汤力水，加冰搅拌，挤一片柠檬就完成，微醺刚刚好",
        },
    )
    assert src.status_code == 201

    resp = await client.post(
        "/api/originality/check",
        json={
            "title": "金汤力怎么调",
            "body": "今天分享一款最简单的居家调酒：金酒加汤力水，加冰搅拌，挤一片柠檬就完成，微醺刚刚好",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["checked"] >= 1
    assert data["max_similarity"] >= 0.2
    results = data["results"]
    assert results
    assert results[0]["ref_type"] == "content"
    assert results[0]["ref_id"] == src.json()["id"]


async def test_originality_endpoint_exclude_self(client):
    """exclude_content_id 排除自身（编辑场景查重）。"""
    src = await client.post(
        "/api/content",
        json={
            "title": "威士忌产区入门",
            "body": "苏格兰、爱尔兰、美国波本、日本威士忌各有风格，先从苏格兰单一麦芽入门最稳妥",
        },
    )
    cid = src.json()["id"]

    resp = await client.post(
        "/api/originality/check",
        json={
            "title": "威士忌产区入门",
            "body": "苏格兰、爱尔兰、美国波本、日本威士忌各有风格，先从苏格兰单一麦芽入门最稳妥",
            "exclude_content_id": cid,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert all(r["ref_id"] != cid for r in data["results"])


async def test_originality_endpoint_threshold_validation(client):
    resp = await client.post(
        "/api/originality/check",
        json={"title": "标题", "body": "正文", "min_similarity": 1.5},
    )
    assert resp.status_code == 422
