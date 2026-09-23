"""Просмотр ролика ПРЕДЛАГАЕТСЯ кнопкой, а не включается сам.

🔴 Час видео — это сотня кадров, которые переезжают в контекст КАЖДОГО следующего
сообщения треда. Решать такое за человека нельзя: ошибка здесь не «ответ вышел хуже», а
списанные деньги, которых не просили.

⚠️ Ссылку узнаём ДЕТЕРМИНИРОВАННО. Тот же урок, что с файловыми инструментами и оговорками
у личностей: полагаться на то, что решатель опознает КАЖДУЮ форму ссылки, нельзя, а цена
промаха — «посмотри этот ролик» без просмотра.
"""

from __future__ import annotations

import pytest

from service.domain.pipeline import auto_mode


@pytest.mark.parametrize(
    "text",
    [
        "перескажи https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "что тут https://youtu.be/dQw4w9WgXcQ",
        "https://youtube.com/shorts/abc",
        "глянь https://rutube.ru/video/abc/",
        "https://vk.com/video-1_2",
        "вот запись https://example.com/lecture.mp4",
        "поток https://cdn.example.com/live/index.m3u8",
    ],
)
def test_a_video_link_is_recognised(text):
    """⚠️ Список не претендует на полноту, но обязан покрывать то, что присылают чаще всего."""
    assert auto_mode._mentions_a_video(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "расскажи про youtube как компанию",
        "почитай https://example.com/article",
        "посмотри видео и скажи что там",
        "",
        "mp4 это контейнер, а не кодек",
    ],
)
def test_text_without_a_link_is_not_a_video(text):
    """🔴 ГРАНИЦА. Предлагать просмотр там, где ссылки нет, — обещать несуществующее.

    Особенно «посмотри видео и скажи что там»: слова есть, ролика нет, и карточка
    предложила бы запустить дорогое над пустотой.
    """
    assert auto_mode._mentions_a_video(text) is False


def _plan_with(monkeypatch, *, offered_mode=None, video_enabled=True):
    """Собирает предложение так, как это делает конвейер, минуя вызов решателя."""
    monkeypatch.setattr(auto_mode, "_video_offer_allowed", lambda: video_enabled)
    return offered_mode


def test_the_offer_is_a_tool_not_a_route(monkeypatch):
    """🔴 РОД ПРЕДЛОЖЕНИЯ РАЗЛИЧАЕТСЯ. Принимаются они по-разному: режим перезапускает
    прогон маршрутом, инструмент лишь снимает запор с признака. Свалив их в одно, клиент
    отправил бы `route_override` с именем, которого среди маршрутов нет."""
    event = auto_mode._tool_offer_event("watch_video", "просмотр видео", "есть ссылка", "текст")

    offer = event.metadata["mode_offer"]
    assert offer["offer_kind"] == "tool"
    assert offer["mode"] == "watch_video"
    assert event.metadata["kind"] == "mode_offer", "карточка должна быть той же, что у режимов"


def test_the_offer_carries_a_server_anchored_deadline():
    """⚠️ Отсчёт СЕРВЕРНЫЙ — таймер в браузере переживают перезагрузкой и второй вкладкой."""
    event = auto_mode._tool_offer_event("watch_video", "просмотр видео", "есть ссылка", "текст")

    offer = event.metadata["mode_offer"]
    assert offer["offered_at"], "без серверной метки срок ничем не задан"
    assert offer["expires_in_sec"] > 0


def test_offer_does_not_duplicate_the_request_text_into_trace_metadata():
    """The UI takes the request from its anchored user message, never the trace offer."""
    event = auto_mode._tool_offer_event("watch_video", "просмотр", "причина", "перескажи ролик")

    assert "prompt" not in event.metadata["mode_offer"]


def test_a_disabled_capability_is_not_offered(monkeypatch):
    """🔴 Выключенную админом способность предлагать — обещать то, чего сервис не сделает."""
    from service.settings import config

    monkeypatch.setattr(config.agents, "video_enabled", False)

    class _NoOverlay:
        @staticmethod
        def get_agents(_name, fallback):
            return fallback

    monkeypatch.setattr(auto_mode, "_video_offer_allowed", auto_mode._video_offer_allowed)
    monkeypatch.setattr("service.shared.agent_settings.runtime_settings", _NoOverlay)

    assert auto_mode._video_offer_allowed() is False


def test_the_offer_is_wired_into_the_plan():
    """🔴 ТОЧКА ВЫЗОВА. Событие, которое никто не собирает, до человека не доедет.

    Проверяем и ВТОРОЕ условие: поверх уже предложенного режима вторую карточку не шлём —
    две подряд про одно сообщение это не выбор, а шум.
    """
    import ast
    import inspect

    source = inspect.getsource(auto_mode.resolve_auto_plan)
    tree = ast.parse(source.strip())

    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_tool_offer_event"
    ]
    assert calls, "предложение просмотра не собирается конвейером вовсе"
    assert "offered_tool=offered_tool" in source, "план не доносит предложение до вызывающего"
    # ⚠️ УСЛОВИЯ ПРОВЕРЯЮТСЯ ПОВЕДЕНИЕМ, А НЕ ПОДСТРОКОЙ. Прежняя строка сверялась с
    # ТЕКСТОМ условия и краснела на любой его перепись — в том числе на верной: правку
    # «не предлагать уже согласованное» она объявила поломкой. Проверка текста исходника
    # в этом проекте уже переживала мутации, которые ломали смысл.
    guarded = {
        name
        for node in ast.walk(tree)
        if isinstance(node, ast.BoolOp)
        for value in node.values
        for name in ast.walk(value)
        if isinstance(name, ast.Name) or isinstance(name, ast.Call)
        for name in [getattr(name, "id", None) or getattr(getattr(name, "func", None), "id", None)]
        if name
    }
    assert "_mentions_a_video" in guarded, "предложение не привязано к наличию ссылки"
    assert "_video_offer_allowed" in guarded, "выключенную админом способность всё ещё предлагают"
