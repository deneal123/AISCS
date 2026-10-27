"""Read-only Redis serialization probe; no inference, charges or stored writes."""

import json
import subprocess
import wave
from pathlib import Path

SOURCE = """
import asyncio,json,logging,sys
logging.disable(logging.CRITICAL)
from service.settings import config
from service.infrastructure.cache.manager import RedisManager
async def main():
 redis=RedisManager(config.redis)
 try:
  duration=json.load(sys.stdin)['duration']
  raw=await redis.get_client().eval(
   'return cjson.encode(cjson.decode(ARGV[1]))',0,
   json.dumps({'duration_limit_sec':duration}))
  restored=json.loads(raw)['duration_limit_sec']
  print(json.dumps({'exact_match':duration==restored,
   'absolute_difference':abs(duration-restored)}))
 finally:
  await redis.close()
asyncio.run(main())
"""


def main():
    root = Path(__file__).resolve().parents[1]
    with wave.open(
        str(root / "frontend/test-results/s38-stt-runtime/controlled.wav")
    ) as audio:
        duration = audio.getnframes() / audio.getframerate() + 1
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-backend-1", "python", "-c", SOURCE],
        input=json.dumps({"duration": duration}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    print(
        result.stdout.strip() if result.returncode == 0 else '{"status":"unavailable"}'
    )


if __name__ == "__main__":
    main()
