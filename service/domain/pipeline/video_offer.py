"""Когда предлагать просмотр ролика: признак ссылки и разрешение админа.

Отдельный модуль, а не пара функций в конвейере: у правила своя причина меняться — список
площадок и расширений, — и знает о нём ровно один потребитель. Заодно конвейер держится
под потолком храповика: он и без того самый крупный файл пакета.
"""

from __future__ import annotations

_VIDEO_HOSTS = (
    "youtube.com/watch",
    "youtu.be/",
    "youtube.com/shorts",
    "vimeo.com/",
    "rutube.ru/video",
    "vk.com/video",
    "vkvideo.ru/",
    "dzen.ru/video",
    "ok.ru/video",
)
_VIDEO_EXTENSIONS = (".mp4", ".webm", ".mkv", ".mov", ".m3u8")


def _mentions_a_video(user_input: str) -> bool:
    """В сообщении есть ссылка на ролик."""
    text = str(user_input or "").lower()
    if "http" not in text:
        return False
    if any(host in text for host in _VIDEO_HOSTS):
        return True
    return any(ext in text for ext in _VIDEO_EXTENSIONS)


def _video_offer_allowed() -> bool:
    """Способность включена админом. Выключенную предлагать — обещать несуществующее."""
    from service.settings import config
    from service.shared.agent_settings import runtime_settings

    return bool(runtime_settings.get_agents("video_enabled", config.agents.video_enabled))


def explicit_video_offer(
    user_input, context, execution, *, route_override=None, resolved_category=None
):
    """Source-dependent file requests need consent even without auto routing.

    This is not a second model selector: it recognizes an existing deterministic
    video request and uses the same offer/continuation contract as auto-mode.
    Other explicitly selected document/workflow routes keep their own gates.
    """
    from service.domain.pipeline.confirmation import tool_offer_event
    from service.domain.video_summary.source import summary_video_url

    if (
        route_override not in {None, "", "general"}
        or resolved_category not in {None, "", "general"}
        or execution.policy.flag("confirmation_declined")
        or getattr(context, "video_tool_enabled", False)
        or summary_video_url(user_input) is None
        or not _video_offer_allowed()
    ):
        return None
    return tool_offer_event(
        "watch_video", "обработка видео", "video_confirmation_required", user_input
    )
