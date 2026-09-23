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
