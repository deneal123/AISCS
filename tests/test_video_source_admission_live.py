"""Opt-in installed video boundary probe; no actual media/provider/storage calls."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

_FILES = (
    "service/domain/tools/video_tool.py",
    "service/domain/video_summary/source.py",
    "service/infrastructure/video_stream.py",
)
_PROBE = """
import asyncio,hashlib,json,sys
import httpx
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from service.domain.execution.context import PrivateRunResources, use_run_execution
from service.domain.tools import video_tool,unbilled_calls
from service.domain.video_summary import source
from service.domain.runners.tool_runtime.contracts import ToolCallOutcome
from service.infrastructure import video_stt,video_stream
from service.infrastructure.sidecar import SidecarClient,SidecarUnavailable
async def main():
 expected=json.load(sys.stdin)
 for module,name in ((video_tool,expected['files'][0]),(source,expected['files'][1]),
                     (video_stream,expected['files'][2])):
  assert hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()==expected['hashes'][name]
 cases=('private-source',{'text':'private-source'},0,
        [{'t_sec':False,'text':'private-source'}],
        [{'t_sec':0,'text':'private-source'+chr(0xd800)}])
 for raw in cases:
  context=SimpleNamespace(context_budget_tokens=32000)
  payload={'duration_sec':10,'transcript':raw,
           'frames':[{'t_sec':0,'image_b64':'private-frame'}]}
  with use_run_execution(PrivateRunResources()) as execution,unbilled_calls.collect() as billing:
   with patch.object(video_tool,'_client',return_value=object()), \
        patch.object(video_tool,'acquire_video',AsyncMock(return_value=payload)) as acquisition:
    result=await video_tool.watch_video_tool(SimpleNamespace(context=context),
                                           json.dumps({'url':'https://youtu.be/probe'}))
   acquisition.assert_awaited_once()
   assert isinstance(result,ToolCallOutcome)
   assert result.status=='failed' and result.failure_code=='protocol'
   assert not result.billable and not result.retryable
   assert 'private' not in result.text
   assert not getattr(context,'watched_frames',[])
   assert execution.artifacts.get(source.SOURCE_KEY,source.VideoTranscript) is None
   assert execution.usage.billable_calls==0
   assert billing['waived']=={'watch_video':1}
 bad_frames=('private-frame',{'image_b64':'private-frame'},False,[None],
             [{'t_sec':0}],[{'t_sec':0,'image_b64':1}],
             [{'t_sec':float('nan'),'image_b64':'private-frame'}],
             [{'t_sec':True,'image_b64':'private-frame'}])
 for frames in bad_frames:
  for transcript in ([],[{'t_sec':0,'text':'speech'}]):
   context=SimpleNamespace(context_budget_tokens=32000)
   payload={'duration_sec':10,'transcript':transcript,'frames':frames}
   with use_run_execution(PrivateRunResources()) as execution,unbilled_calls.collect() as billing:
    with patch.object(video_tool,'_client',return_value=object()), \
         patch.object(video_tool,'acquire_video',AsyncMock(return_value=payload)), \
         patch.object(video_stt,'acquire_local_transcript',AsyncMock(return_value=None)) as fallback:
     result=await video_tool.watch_video_tool(SimpleNamespace(context=context),
                                            json.dumps({'url':'https://youtu.be/probe'}))
    assert isinstance(result,ToolCallOutcome) and result.failure_code=='protocol'
    assert not result.billable and not result.retryable and 'private' not in result.text
    assert not getattr(context,'watched_frames',[])
    assert execution.artifacts.get(source.SOURCE_KEY,source.VideoTranscript) is None
    assert billing['waived']=={'watch_video':1}
    fallback.assert_not_awaited()
 results=(
  ({'duration_sec':10,'transcript':[],'frames':[]},False),
  ({'duration_sec':'10','transcript':[{'t_sec':'2.5','text':'speech'}]},True),
  ({'duration_sec':10,'transcript':[{'t_sec':0,'text':'speech'}],
    'warnings':['private-provider-warning']},True))
 for payload,success in results:
  with use_run_execution(PrivateRunResources()),unbilled_calls.collect() as billing:
   with patch.object(video_tool,'_client',return_value=object()), \
        patch.object(video_tool,'acquire_video',AsyncMock(return_value=payload)), \
        patch.object(video_stt,'acquire_local_transcript',AsyncMock(return_value=None)):
    result=await video_tool.watch_video_tool(SimpleNamespace(context=None),
                                           json.dumps({'url':'https://youtu.be/probe'}))
   if success:
    assert isinstance(result,str) and 'speech' in result and 'private' not in result
   else:
    assert isinstance(result,ToolCallOutcome) and result.status=='failed'
    assert not result.billable and billing['waived']=={'watch_video':1}
 class Stream(httpx.AsyncByteStream):
  def __init__(self,chunks): self.chunks=chunks;self.reads=0;self.closed=False
  async def __aiter__(self):
   for chunk in self.chunks: self.reads+=1;yield chunk
  async def aclose(self): self.closed=True
 previous_limit=video_stream._MAX_FRAME_BYTES
 for chunks,limit,max_reads in (([b'xxxx']*100,8,3),([b'private-invalid-json'],1024,1)):
  stream=Stream(chunks)
  def handle(request):
   return httpx.Response(200,headers={'content-type':'application/json'},stream=stream)
  client=SidecarClient(service='video',base_url='http://video-fixture',timeout=2,
                       transport=httpx.MockTransport(handle))
  try:
   video_stream._MAX_FRAME_BYTES=limit
   try: await video_stream.acquire_video(client,{},'')
   except SidecarUnavailable as error:
    assert error.code=='protocol' and 'private' not in str(error)
   else: raise AssertionError
  finally: video_stream._MAX_FRAME_BYTES=previous_limit
  assert stream.closed and stream.reads<=max_reads
 print(json.dumps({'status':'passed','cases':len(cases)+len(results)+2+len(bad_frames)*2,
                   'source_matches':True,'real_calls':0}))
try: asyncio.run(main())
except BaseException:
 print(json.dumps({'status':'failed','failure_code':'video_source_probe'}));sys.exit(1)
"""


@pytest.mark.skipif(
    os.getenv("S37_LIVE_VIDEO_SOURCE_ADMISSION") != "1", reason="opt-in installed video probe"
)
def test_installed_video_source_admission():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-agents-1", "python", "-c", _PROBE],
        input=json.dumps(
            {
                "files": _FILES,
                "hashes": {
                    name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in _FILES
                },
            }
        ),
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, "installed_video_source_probe_failed"
    assert json.loads(result.stdout) == {
        "status": "passed",
        "cases": 26,
        "source_matches": True,
        "real_calls": 0,
    }
