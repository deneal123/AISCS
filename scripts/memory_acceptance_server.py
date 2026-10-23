"""Изолированный dev-процесс MemOS: реальные хранилища, только собственный тестовый куб."""

import contextlib
import hmac
import io
import json
import logging
import os


actor = os.environ["MEMORY_ACCEPTANCE_ACTOR"]
assert actor.startswith("memory-live-") and len(actor) < 80
key = os.environ["MOS_EMBEDDER_API_KEY"]
os.environ.update(
    API_SCHEDULER_ON="false",
    ENABLE_CHAT_API="false",
    MOS_MULTIPROVIDER_ENABLED="true",
    OPENAI_API_BASE="http://backend:18096/v1",
    MEMRADER_API_BASE="http://backend:18096/v1",
    MOS_EMBEDDER_API_BASE="http://backend:18096/v1",
    MOS_CHAT_MODEL="gpthub-memory",
    MEMRADER_MODEL="gpthub-memory",
    MOS_MAX_TOKENS="400",
    MEMRADER_MAX_TOKENS="400",
)
logging.disable(logging.CRITICAL)

with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    import uvicorn

    from starlette.responses import JSONResponse

    from memos.api.server_api import app


@app.middleware("http")
async def bounded_actor(request, call_next):
    if request.url.path == "/health":
        return await call_next(request)
    if not hmac.compare_digest(request.headers.get("Authorization", ""), "Bearer " + key):
        return JSONResponse({}, status_code=401)
    if request.url.path not in ("/product/add", "/product/search", "/product/admin/wipe_user"):
        return JSONResponse({}, status_code=404)
    body = json.loads(await request.body())
    user = "user:" + actor
    cube = "gpthub-" + user
    if request.url.path.endswith("wipe_user"):
        allowed = body == {"user_name": cube}
    else:
        allowed = body.get("user_id") == user and body.get("mem_cube_id") == cube
    if not allowed:
        return JSONResponse({}, status_code=403)
    return await call_next(request)


print(json.dumps({"isolated_memory_server": "starting"}), flush=True)
with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    uvicorn.run(app, host="0.0.0.0", port=18097, log_level="critical")
