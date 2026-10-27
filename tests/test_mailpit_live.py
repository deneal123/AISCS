"""Opt-in dev HTTP/Celery/SMTP acceptance; only this test's user and mail are removed."""

import json
import os
import re
import secrets
import subprocess
import time
import uuid

import httpx
import pytest

_CLEANUP = r"""
import asyncio,json,logging,re,sys
logging.disable(logging.CRITICAL)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from redis.asyncio import Redis
from service.settings import Config
from service.infrastructure.cache.sessions import RedisSessionStore
async def main():
 email=json.load(sys.stdin)['email']
 assert re.fullmatch(r'mailpit-smoke-[0-9a-f]{32}@example.com',email)
 cfg=Config(); engine=create_async_engine(cfg.pg.dsn)
 try:
  async with engine.begin() as connection:
   owner=await connection.scalar(
    text('SELECT id FROM profile.user WHERE email=:email'),{'email':email})
   if owner:
    await connection.execute(
     text('DELETE FROM session.user_session WHERE user_id=:owner'),{'owner':owner})
    await connection.execute(text('DELETE FROM profile.user WHERE id=:owner AND email=:email'),
     {'owner':owner,'email':email})
 finally: await engine.dispose()
 redis=Redis.from_url(cfg.redis.dsn)
 try:
  if owner:
   await RedisSessionStore(redis,cfg.redis).invalidate_user_sessions(owner)
   await redis.delete(f'{cfg.redis.cache_prefix}:profile:id:v2:{owner}')
  await redis.delete(f'{cfg.redis.cache_prefix}:profile:email:v2:{email}')
  await redis.delete(f'{cfg.redis.cache_prefix}:auth:otp:{email}')
 finally: await redis.aclose()
 print(json.dumps({'status':'cleaned'}))
asyncio.run(main())
"""

_INLINE = r"""
import asyncio,json,logging,re,sys
from unittest.mock import patch
logging.disable(logging.CRITICAL)
from service.settings import Config
from service.infrastructure.mail.smtp_mailer import SmtpMailer
from service.infrastructure.mail.dispatcher import VerificationCodeDispatcher
async def main():
 email=json.load(sys.stdin)['email']
 assert re.fullmatch(r'mailpit-smoke-[0-9a-f]{32}@example.com',email)
 cfg=Config()
 assert cfg.email.host=='mailpit' and cfg.email.port==1025
 assert cfg.email.enabled and not cfg.email.use_tls and not cfg.email.start_tls
 assert not cfg.email.login and not cfg.email.password
 dispatcher=VerificationCodeDispatcher(SmtpMailer(cfg.email),enabled=True,dev_mode=False,ttl_seconds=600)
 with patch('service.infrastructure.messaging.tasks.send_verification_email.delay',
  side_effect=RuntimeError('synthetic_broker_unavailable')):
  await dispatcher.send(email=email,code='123456',purpose='register')
 print(json.dumps({'status':'inline_completed'}))
asyncio.run(main())
"""


def _probe(source, email):
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-backend-1", "python", "-"],
        input=(source.replace("json.load(sys.stdin)['email']", repr(email))).encode(),
        capture_output=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail("mailpit_probe_failed")
    return json.loads(result.stdout)


def _owned_messages(client, email):
    response = client.get("/api/v1/messages")
    assert response.status_code == 200, "mailpit_inventory_unavailable"
    return [
        message
        for message in response.json().get("messages", [])
        if any(recipient.get("Address") == email for recipient in message.get("To", []))
    ]


def _wait_message(client, email, existing):
    deadline = time.monotonic() + 35
    while time.monotonic() < deadline:
        fresh = [
            message for message in _owned_messages(client, email) if message["ID"] not in existing
        ]
        if fresh:
            assert len(fresh) == 1, "duplicate_verification_email"
            response = client.get(f"/api/v1/message/{fresh[0]['ID']}")
            assert response.status_code == 200, "mailpit_message_unavailable"
            body = response.json()
            assert body.get("HTML") and body.get("Text"), "mailpit_missing_multipart_body"
            codes = re.findall(r"(?<!\d)\d{6}(?!\d)", body["Text"])
            assert len(codes) == 1, "mailpit_invalid_verification_code"
            return codes[0]
        time.sleep(0.5)
    pytest.fail("mailpit_delivery_timeout")


@pytest.mark.skipif(os.getenv("LIVE_MAILPIT") != "1", reason="opt-in dev SMTP acceptance")
def test_registration_resend_verification_and_inline_delivery():
    email = f"mailpit-smoke-{uuid.uuid4().hex}@example.com"
    password = secrets.token_urlsafe(24) + "A1"
    with (
        httpx.Client(base_url="http://127.0.0.1:8001", trust_env=False, timeout=20) as backend,
        httpx.Client(base_url="http://127.0.0.1:8026", trust_env=False, timeout=10) as mailpit,
    ):
        assert mailpit.get("/readyz").status_code == 200
        try:
            registered = backend.post(
                "/api/auth/v1/register",
                json={
                    "email": email,
                    "password": password,
                    "consent_pd": True,
                    "consent_transfer": True,
                    "consent_version": "mailpit-smoke",
                },
            )
            assert registered.status_code == 200, "registration_failed"
            first_code = _wait_message(mailpit, email, set())
            previous = {message["ID"] for message in _owned_messages(mailpit, email)}
            resend = backend.post("/api/auth/v1/resend", json={"email": email})
            assert resend.status_code == 200, "resend_failed"
            code = _wait_message(mailpit, email, previous)
            assert first_code and code
            verified = backend.post("/api/auth/v1/verify", json={"email": email, "code": code})
            assert verified.status_code == 200, "email_verification_failed"
            assert "auth_token" in backend.cookies, "verification_session_missing"
            previous = {message["ID"] for message in _owned_messages(mailpit, email)}
            assert _probe(_INLINE, email)["status"] == "inline_completed"
            assert _wait_message(mailpit, email, previous) == "123456"
            assert len(_owned_messages(mailpit, email)) == 3
        finally:
            try:
                ids = [message["ID"] for message in _owned_messages(mailpit, email)]
                if ids:
                    removed = mailpit.request("DELETE", "/api/v1/messages", json={"IDs": ids})
                    assert removed.status_code == 200, "mailpit_cleanup_failed"
                assert not _owned_messages(mailpit, email), "mailpit_owned_mail_remaining"
            finally:
                assert _probe(_CLEANUP, email)["status"] == "cleaned"
