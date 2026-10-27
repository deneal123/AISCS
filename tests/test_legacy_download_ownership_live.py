"""Opt-in two-actor dev security acceptance; no model or object writes."""

import asyncio
import json
import os
import subprocess

import httpx
import pytest


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv("S37_LIVE_DOWNLOAD_OWNERSHIP") != "1", reason="local two-actor auth")
async def test_owned_pdf_is_not_downloadable_by_another_authenticated_actor():
    # Fixture credentials/storage locators cross only this private process pipe.
    # Do not write them to env, files, test artifacts, logs or terminal output.
    probe = """
import asyncio,json,logging,secrets
from argon2 import PasswordHasher
from sqlalchemy import text
from service.settings import Config
from service.infrastructure.database.postgresql import PgConnector
from service.services.profile.persistence.profile_repository import ProfileRepository
from service.services.profile.persistence.auth_repository import AuthRepository
from service.services.profile.application.auth_service import AuthService
logging.disable(logging.CRITICAL)
async def main():
 try:
  config=Config(); connector=PgConnector(config.pg); repo=ProfileRepository(connector)
  owner=await repo.fetch_user_by_email('s37-e2e-391e5206659a3654@example.com')
  reader=await repo.fetch_user_by_email('s37-security-reader@example.com')
  if reader is None:
   reader=await repo.create_user(email='s37-security-reader@example.com',
    password_hash=PasswordHasher().hash(secrets.token_urlsafe(32)+'A1'),consent_version='dev')
   await repo.set_email_verified(str(reader.id))
  async with connector.get_session_context() as session:
   result=await session.execute(text('''SELECT f.id,f.file_name FROM profile.user_file f
    WHERE f.user_id=:owner AND f.file_name LIKE '%.pdf' ORDER BY f.created_at DESC LIMIT 1
   '''),{'owner':owner.id})
   row=result.mappings().first()
  if row is None:raise ValueError('owned_pdf_fixture_missing')
  auth=AuthService(config.auth,AuthRepository(connector),None,config.email)
  own_session=await auth._create_activated_session(owner,'s37-security-owner',None)
  other_session=await auth._create_activated_session(reader,'s37-security-reader',None)
  print(json.dumps({'owner_token':own_session.token,'reader_token':other_session.token,
   'file_key':row['file_name'],'file_id':str(row['id'])}))
 except Exception:
  print('{}'); raise SystemExit(1)
asyncio.run(main())
"""
    result = await asyncio.to_thread(
        subprocess.run,
        ["docker", "exec", "-i", "gpthub-dev-backend-1", "python", "-"],
        input=probe.encode(),
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, "isolated_security_fixture_unavailable"
    fixture = json.loads(result.stdout)
    async with httpx.AsyncClient(base_url="http://localhost:8001", timeout=30) as client:
        for actor in ("reader", "owner"):
            client.cookies.set("auth_token", fixture[f"{actor}_token"])
            for route, params in (
                ("/api/chats/files/download", {"file_key": fixture["file_key"]}),
                (f"/api/service/files/v1/{fixture['file_id']}/download", {}),
            ):
                response = await client.get(route, params=params, follow_redirects=False)
                if actor == "reader":
                    assert response.status_code == 404, "foreign_file_access_not_denied"
                    assert "location" not in response.headers
                else:
                    assert response.status_code in {200, 307}, "owned_file_unavailable"
