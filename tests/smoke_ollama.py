"""
Ollama AI 解析烟测试 — 手动运行，不纳入自动回归
用法: python tests/smoke_ollama.py

需要本地 Ollama 运行中，会实际调用模型推理
"""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Use local Ollama
os.environ['OLLAMA_BASE_URL'] = 'http://localhost:11434'
os.environ['OLLAMA_MODEL'] = 'macvoice'  # local qwen2 7B model

from app import create_app
from app.services.ai import parse_requirement, _extract_json

app = create_app('testing')

TEST_INPUT = """
张经理：我们的后台管理系统需要加一个批量导出功能
李开发：导出什么格式？
张经理：Excel，要能选择时间范围和状态筛选
李开发：大概多少数据量？需要异步处理吗
张经理：最多几万条吧，同步应该就行，尽快搞定，下周要用
"""


def test_parse():
    print('=' * 50)
    print('Ollama AI 解析烟测试')
    print('=' * 50)
    print(f'模型: {app.config["OLLAMA_MODEL"]}')
    print(f'地址: {app.config["OLLAMA_BASE_URL"]}')
    print()

    print('【输入文本】')
    print(TEST_INPUT.strip())
    print()

    print('正在调用 Ollama ... (可能需要 10-30 秒)')
    with app.app_context():
        result, raw = parse_requirement(TEST_INPUT)

    print('【AI 原始返回】')
    print(raw)
    print()

    if result is None:
        print('FAIL: AI 返回解析失败')
        print('可能原因: Ollama 未运行 / 模型未加载 / 返回非 JSON')
        sys.exit(1)

    print('【解析结果 JSON】')
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print()

    # Basic checks
    errors = []
    if 'title' not in result:
        errors.append('缺少 title 字段')
    elif len(result['title']) > 50:
        errors.append(f'title 过长: {len(result["title"])} 字')

    if 'description' not in result:
        errors.append('缺少 description 字段')

    if result.get('priority') not in ('high', 'medium', 'low', None):
        errors.append(f'priority 值异常: {result.get("priority")}')

    if 'subtasks' in result and not isinstance(result['subtasks'], list):
        errors.append(f'subtasks 应为列表, 实际: {type(result["subtasks"])}')

    if errors:
        print('WARN: 以下字段不符合预期:')
        for e in errors:
            print(f'  - {e}')
    else:
        print('PASS: 所有字段格式正确')
        print(f'  标题: {result["title"]}')
        print(f'  优先级: {result.get("priority", "未识别")}')
        print(f'  工期: {result.get("estimate_days", "未识别")} 人天')
        print(f'  子任务: {len(result.get("subtasks", []))} 个')


if __name__ == '__main__':
    test_parse()
