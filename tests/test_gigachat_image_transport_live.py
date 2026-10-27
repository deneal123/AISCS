"""Opt-in actual native file API, one synthetic image, zero inference or billing."""

import ast
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

_PROBE = """
import asyncio,base64,hashlib,json,logging
from io import BytesIO
from pathlib import Path
from PIL import Image,ImageDraw
logging.disable(logging.CRITICAL)
from service.domain.client import registry
from service.domain.client.models.requirements import ModelRequirement
from service.domain.client.protocol import classify_provider_failure
from service.domain.client.providers.gigachat import adapter as gigachat, images as gigachat_images
stage='freshness'; identity=None; client=None
async def main():
 global stage,identity,client
 assert hashlib.sha256(Path(gigachat.__file__).read_bytes()).hexdigest()=='__PROFILE__'
 assert hashlib.sha256(Path(gigachat_images.__file__).read_bytes()).hexdigest()=='__IMAGES__'
 try:
  stage='catalog'
  catalog=await registry.get_provider_model_catalog('gigachat',force_refresh=True)
  assert catalog.source.value=='live' and catalog.status.value=='available' and catalog.fresh
  decision=await registry.qualify_model('gigachat',
   requirement=ModelRequirement(vision=True,tools=True),catalog=catalog)
  assert decision.compatible
  client=gigachat._RUNTIME.client
  assert client is not None
  output=BytesIO(); image=Image.new('RGB',(640,480),'white')
  ImageDraw.Draw(image).text((60,80),'Synthetic layout transport fixture',fill='black')
  image.save(output,'PNG')
  messages=[{'role':'user','content':[{'type':'text','text':'Synthetic transport fixture'},
   {'type':'image_url','image_url':{'url':'data:image/png;base64,'+
    base64.b64encode(output.getvalue()).decode()}}]}]
  stage='upload'
  async with gigachat_images.native_image_messages(client,'gigachat',messages) as native:
   identity=native[0]['attachments'][0]
   assert type(identity) is str and type(native[0]['content']) is str
   assert 'image_url' not in json.dumps(native)
   stage='readback'
   stored=await client.get('/files/'+identity,cast_to=object,
    options={'max_retries':0,'timeout':10})
   assert stored['id']==identity and stored['purpose']=='general'
  stage='cleanup_verification'
  listing=await client.get('/files',cast_to=object,options={'max_retries':0,'timeout':10})
  assert isinstance(listing,dict) and isinstance(listing.get('data'),list)
  assert not any(item.get('id')==identity for item in listing['data'])
  identity=None
  print(json.dumps({'status':'passed','provider':'gigachat','model':decision.model,
   'uploads':1,'deleted':1,'model_calls':0,'library_writes':0}))
 finally:
  if identity is not None and client is not None:
   await client.post('/files/'+identity+'/delete',cast_to=object,
    options={'max_retries':0,'timeout':3})
  for module in registry.PROVIDER_MODULES.values():
   runtime=getattr(module,'_RUNTIME',None)
   if runtime is not None: await runtime.drain_generations()
try: asyncio.run(asyncio.wait_for(main(),50))
except Exception as exc:
 print(json.dumps({'status':'failed','stage':stage,
  'reason':classify_provider_failure(exc,provider='gigachat').code.value})); raise SystemExit(1)
"""


def test_native_file_probe_compiles():
    ast.parse(_PROBE)


@pytest.mark.skipif(os.getenv("S37_LIVE_GIGACHAT_FILES") != "1", reason="opt-in dev GigaChat files")
def test_actual_gigachat_file_upload_and_verified_deletion():
    base = Path("service/domain/client/providers/gigachat")
    probe = _PROBE
    for marker, filename in (("__PROFILE__", "adapter.py"), ("__IMAGES__", "images.py")):
        probe = probe.replace(marker, hashlib.sha256((base / filename).read_bytes()).hexdigest())
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-agents-1", "python", "-"],
        input=probe.encode(),
        capture_output=True,
        timeout=65,
    )
    lines = result.stdout.decode("utf-8", errors="replace").strip().splitlines()
    assert lines, "gigachat_file_probe_missing_result"
    report = json.loads(lines[-1])
    assert result.returncode == 0 and report.get("status") == "passed", (
        "gigachat_file_probe_failed_"
        + str(report.get("stage", "unknown"))
        + "_"
        + str(report.get("reason", "unknown"))
    )
    assert report["uploads"] == report["deleted"] == 1
    assert report["model_calls"] == report["library_writes"] == 0
