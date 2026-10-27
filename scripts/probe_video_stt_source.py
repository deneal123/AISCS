"""Opt-in dev media probe. No STT, inference, transcript or credentials output."""

from __future__ import annotations

import json
import subprocess

SOURCE = """
import asyncio,json,logging
logging.disable(logging.CRITICAL)
from service.settings import config
from service.services.chat.infrastructure.media.video_audio import fetch_video_audio
from service.services.chat.application.video_stt.execution import VideoSttFailure
async def main():
 try:
  audio=await fetch_video_audio(config.agents.video_url,config.agents.video_api_key,
   'https://www.youtube.com/watch?v=sXKnmgmbkoE',timeout_sec=240)
  print(json.dumps({'status':'ready','bytes':len(audio.content),
   'duration_sec':audio.duration_sec,'sha256':audio.sha256}))
 except VideoSttFailure as exc:
  print(json.dumps({'status':'unavailable','code':exc.code}))
 except Exception:
  print(json.dumps({'status':'unavailable','code':'internal'}))
asyncio.run(main())
"""


def main() -> None:
    try:
        result = subprocess.run(
            ["docker", "exec", "-i", "gpthub-dev-backend-1", "python", "-"],
            input=SOURCE,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=260,
        )
        report = json.loads(result.stdout) if result.returncode == 0 else None
        if not isinstance(report, dict) or report.get("status") not in {
            "ready",
            "unavailable",
        }:
            raise ValueError
        print(json.dumps(report))
    except Exception:
        print(json.dumps({"status": "unavailable", "code": "probe_failed"}))


if __name__ == "__main__":
    main()
