from app.services.llm import extract_json


def test_extract_json_plain():
    assert extract_json('{"value": 1}') == '{"value": 1}'


def test_extract_json_fenced():
    assert extract_json('```json\n{"value": 1}\n```') == '{"value": 1}'


def test_extract_json_with_prose():
    assert extract_json('结果如下：{"value": 1}，完毕') == '{"value": 1}'
