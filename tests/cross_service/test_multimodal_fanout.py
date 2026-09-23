"""Классификация залитого файла по типам.

Остаток от тестов мультимодального веера: сам веер уехал в сайдкар
(``agents/tests/cross_service/test_multimodal_fanout.py``) — он получает уже готовые
вложения и о разборе файлов ничего не знает. А раскладка файла по типам — работа
backend'а: от неё зависит, какой аналитик модальности попросят на той стороне.
"""

import pytest

from service.services.chat.application.use_cases.upload_file_use_case import UploadFileUseCase


@pytest.mark.asyncio
async def test_upload_classifies_code_and_data():
    uc = UploadFileUseCase(media_analysis_port=None, file_service=None)
    _, code_type = await uc._extract_text("script.py", "text/x-python", b"print('hi')")
    _, csv_type = await uc._extract_text("data.csv", "text/csv", b"a,b\n1,2")
    _, json_type = await uc._extract_text("cfg.json", "application/json", b'{"a": 1}')
    _, doc_type = await uc._extract_text("notes.txt", "text/plain", b"hello")
    assert code_type == "code"
    assert csv_type == "csv"
    assert json_type == "json"
    assert doc_type == "text"
