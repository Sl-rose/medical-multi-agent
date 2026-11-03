"""medical_safety 模块的单元测试范式。

这是给团队的「测试长什么样」示例：纯函数、无外部依赖、跑得飞快。
运行：pytest tests/test_medical_safety.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from medical_safety import (
    DISCLAIMER,
    EMERGENCY_ADVICE,
    EMERGENCY_KEYWORDS,
    assess_medical_safety,
    build_safety_context,
    prepend_emergency_warning_if_needed,
)


def test_assess_medical_safety_detects_emergency():
    result = assess_medical_safety("我现在胸痛得厉害，喘不上气")
    assert result.emergency is True
    assert "胸痛" in result.matched_keywords
    assert "喘不上气" in result.matched_keywords


def test_assess_medical_safety_normal_text():
    result = assess_medical_safety("最近有点咳嗽，嗓子干")
    assert result.emergency is False
    assert result.matched_keywords == ()


def test_assess_medical_safety_empty_input():
    result = assess_medical_safety("")
    assert result.emergency is False


def test_build_safety_context_includes_disclaimer_for_normal():
    ctx = build_safety_context("患者主诉轻度乏力")
    assert DISCLAIMER in ctx
    assert EMERGENCY_ADVICE not in ctx


def test_build_safety_context_prioritizes_emergency():
    ctx = build_safety_context("突然昏迷了")
    assert EMERGENCY_ADVICE in ctx
    assert "昏迷" in ctx


def test_prepend_emergency_warning_when_missing():
    reply = "建议你先休息观察"
    out = prepend_emergency_warning_if_needed(reply, "我大出血了")
    assert out.startswith(EMERGENCY_ADVICE)
    assert reply in out


def test_prepend_emergency_warning_keeps_existing():
    reply = f"{EMERGENCY_ADVICE}\n请立即就医"
    out = prepend_emergency_warning_if_needed(reply, "我大出血了")
    # 已有急症建议则不再重复前置
    assert out == reply


def test_emergency_keywords_not_empty():
    assert len(EMERGENCY_KEYWORDS) > 0
    assert all(isinstance(k, str) and k for k in EMERGENCY_KEYWORDS)
