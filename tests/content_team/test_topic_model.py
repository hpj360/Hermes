"""选题模型单元测试。"""
from __future__ import annotations

import uuid

import pytest

from hermes.content_team.models.topic import Topic, TopicScore, TopicStatus


def test_topic_fields_assignment():
    """Topic 字段可正确赋值与读取（列默认值在 INSERT 时生效，由 API 测试覆盖）。"""
    member_id = uuid.uuid4()
    topic = Topic(
        title="测试选题",
        description="描述内容",
        priority=2,
        status=TopicStatus.PENDING,
        target_platforms=["wechat"],
        assigned_to=member_id,
    )
    assert topic.title == "测试选题"
    assert topic.description == "描述内容"
    assert topic.priority == 2
    assert topic.status == TopicStatus.PENDING
    assert topic.target_platforms == ["wechat"]
    assert topic.assigned_to == member_id


def test_topic_nullable_assigned_to():
    """Topic.assigned_to 默认为 None（未赋值时）。"""
    topic = Topic(title="未领取选题", target_platforms=[])
    assert topic.assigned_to is None


def test_topic_status_enum_values():
    """TopicStatus 枚举值覆盖四种状态。"""
    assert TopicStatus.PENDING.value == "PENDING"
    assert TopicStatus.IN_PROGRESS.value == "IN_PROGRESS"
    assert TopicStatus.PUBLISHED.value == "PUBLISHED"
    assert TopicStatus.ARCHIVED.value == "ARCHIVED"


def test_topic_status_is_str_enum():
    """TopicStatus 继承 str，可直接与字符串比较。"""
    assert TopicStatus.PENDING == "PENDING"


def test_topic_score_compute_total_all_ones():
    """全 1 输入得满分 1.0。"""
    assert TopicScore.compute_total(1.0, 1.0, 1.0) == pytest.approx(1.0)


def test_topic_score_compute_total_all_zeros():
    """全 0 输入得 0 分。"""
    assert TopicScore.compute_total(0.0, 0.0, 0.0) == pytest.approx(0.0)


def test_topic_score_compute_total_weights():
    """验证权重：heat*0.4 + expertise*0.3 + timeliness*0.3。"""
    # 仅热度
    assert TopicScore.compute_total(1.0, 0.0, 0.0) == pytest.approx(0.4)
    # 仅擅长度
    assert TopicScore.compute_total(0.0, 1.0, 0.0) == pytest.approx(0.3)
    # 仅时效性
    assert TopicScore.compute_total(0.0, 0.0, 1.0) == pytest.approx(0.3)


def test_topic_score_compute_total_mixed():
    """混合输入的加权计算。"""
    total = TopicScore.compute_total(0.8, 0.6, 0.4)
    expected = 0.8 * 0.4 + 0.6 * 0.3 + 0.4 * 0.3
    assert total == pytest.approx(expected)


def test_topic_score_weight_constants():
    """权重常量之和为 1.0。"""
    assert (
        TopicScore.WEIGHT_HEAT
        + TopicScore.WEIGHT_EXPERTISE
        + TopicScore.WEIGHT_TIMELINESS
    ) == pytest.approx(1.0)


@pytest.mark.parametrize(
    "heat, expertise, timeliness",
    [
        (0.5, 0.5, 0.5),
        (0.1, 0.9, 0.3),
        (0.7, 0.2, 0.8),
        (1.0, 0.0, 0.5),
    ],
)
def test_topic_score_total_in_range(heat, expertise, timeliness):
    """综合得分始终落在 [0, 1] 区间。"""
    total = TopicScore.compute_total(heat, expertise, timeliness)
    assert 0.0 <= total <= 1.0
