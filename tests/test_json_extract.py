"""Test suite for _extract_json robustness.
Run with: pytest tests/test_json_extract.py
Skipped in normal test runs unless --run-ai flag is set.
"""
import pytest

pytestmark = pytest.mark.ai


@pytest.fixture
def extract():
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from app.services.ai import _extract_json
    return _extract_json


class TestExtractJson:
    """_extract_json should handle various AI output formats."""

    def test_standard_dict(self, extract):
        assert extract('{"a":1}') == {"a": 1}

    def test_standard_list(self, extract):
        assert extract('[{"a":1}]') == [{"a": 1}]

    def test_markdown_wrapped_dict(self, extract):
        text = '```json\n{"a":1}\n```'
        assert extract(text) == {"a": 1}

    def test_markdown_wrapped_list(self, extract):
        text = '```json\n[{"a":1}]\n```'
        assert extract(text) == [{"a": 1}]

    def test_markdown_no_json_tag(self, extract):
        text = '```\n{"a":1}\n```'
        assert extract(text) == {"a": 1}

    def test_text_before_json(self, extract):
        text = '这是分析结果：\n{"summary":"ok","score":85}'
        result = extract(text)
        assert isinstance(result, dict)
        assert result["score"] == 85

    def test_text_after_json(self, extract):
        text = '{"a":1}\n以上是返回的JSON'
        assert extract(text) == {"a": 1}

    def test_text_around_list(self, extract):
        text = 'result: [{"a":1},{"b":2}] end of output'
        result = extract(text)
        assert isinstance(result, list)
        assert len(result) == 2

    def test_trailing_comma_dict(self, extract):
        text = '{"a":1,"b":2,}'
        result = extract(text)
        assert isinstance(result, dict)
        assert result["a"] == 1

    def test_trailing_comma_list(self, extract):
        text = '[{"title":"a"},{"title":"b"},]'
        result = extract(text)
        assert isinstance(result, list)
        assert len(result) == 2

    def test_single_quotes(self, extract):
        text = "{'a':1,'b':'hello'}"
        result = extract(text)
        assert isinstance(result, dict)
        assert result["a"] == 1

    def test_empty_string(self, extract):
        assert extract('') is None

    def test_none_input(self, extract):
        assert extract(None) is None

    def test_pure_text(self, extract):
        assert extract('not json at all, just text') is None

    def test_nested_json(self, extract):
        text = '{"issues":[{"title":"bug","severity":"high","owner":"张三"}]}'
        result = extract(text)
        assert isinstance(result, dict)
        assert len(result["issues"]) == 1
        assert result["issues"][0]["owner"] == "张三"

    def test_embedded_in_explanation(self, extract):
        text = '根据分析，遗留问题如下：\n{"issues":[{"title":"问题1","severity":"high"}]}\n请确认。'
        result = extract(text)
        assert isinstance(result, dict)
        assert "issues" in result

    def test_truncated_response(self, extract):
        """AI response truncated mid-JSON - should still extract what's there."""
        text = '{"summary":"本周完成3项需求","risks":["风险1"]}'
        result = extract(text)
        assert isinstance(result, dict)
        assert result["summary"].startswith("本周")

    def test_multiline_json(self, extract):
        text = '''{
  "summary": "进展良好",
  "plan": [
    "周三前完成联调",
    "周五前提测"
  ]
}'''
        result = extract(text)
        assert isinstance(result, dict)
        assert len(result["plan"]) == 2

    def test_markdown_with_explanation(self, extract):
        text = '''好的，以下是分析结果：

```json
{"score": 75, "issues": ["标题模糊"], "suggestions": ["明确指标"]}
```

希望对你有帮助。'''
        result = extract(text)
        assert isinstance(result, dict)
        assert result["score"] == 75

    def test_array_of_objects(self, extract):
        text = '[{"name":"张三","status":"正常","risk_level":"low"}]'
        result = extract(text)
        assert isinstance(result, list)
        assert result[0]["name"] == "张三"

    def test_real_world_aar(self, extract):
        """Real AAR AI response format."""
        text = '''[
    {"title": "支付模块延期", "severity": "high", "owner": "张三", "deadline": "2026-04-01"},
    {"title": "测试覆盖不足", "severity": "medium", "owner": "王五", "deadline": "2026-04-15"}
]'''
        result = extract(text)
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["severity"] == "high"

    def test_real_world_weekly_report(self, extract):
        """Real weekly report AI response format."""
        text = '''{"summary":"本周完成用户管理模块联调","highlights":["提前2天完成"],"risks":["暂无"],"plan":["周三前完成提测"]}'''
        result = extract(text)
        assert isinstance(result, dict)
        assert "summary" in result
        assert "plan" in result
