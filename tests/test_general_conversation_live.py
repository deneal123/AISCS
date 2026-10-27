"""Opt-in private pipeline replay; GigaChat only, no persistent user or memory writes.

This is a bounded behavioural sentinel, not authenticated browser/billing acceptance.
"""

import json
import os
import subprocess

import pytest

_PROBE = r"""
import asyncio,json,logging,re,sys,time,uuid
logging.disable(logging.CRITICAL)
import httpx
from service.settings import Config
report=[]
async def main():
 cfg=Config(); history=[]; thread=str(uuid.uuid4())
 inputs=json.load(sys.stdin)['inputs']
 async with httpx.AsyncClient(timeout=120,trust_env=False) as client:
  for index,query in enumerate(inputs):
   start=time.monotonic()
   body={'text':query,'thread_id':thread,'user_id':'conversation-acceptance',
    'selected_model':'GigaChat-2-Max','history_messages':history,
    'memory_enabled':False,'planning':False,'multi_intent':False,
    'persona_ids':['psychologist'],
    'provider_policy':{'disabled':['openai','openrouter','mws','routerai'],'blocked':[]}}
   result=None; terminals=0; offers=0; errors=0; stream_parts=[]
   async with client.stream('POST',cfg.agents.sidecar_url.rstrip('/')+'/run',json=body,
    headers={'Authorization':'Bearer '+cfg.agents.llm_gateway_api_key}) as response:
    assert response.status_code==200
    async for line in response.aiter_lines():
     if not line.strip(): continue
     event=json.loads(line)
     if '__result__' in event: result=event['__result__']; terminals+=1
     if '__error__' in event: errors+=1
     if event.get('type')=='error': errors+=1
     if event.get('type')=='stream_chunk' and isinstance(event.get('data'),str):
      stream_parts.append(event['data'])
     metadata=event.get('metadata') or {}
     if metadata.get('kind') in ('tool_offer','mode_offer'): offers+=1
   assert isinstance(result,dict) and terminals==1
   reply=result.get('reply',''); assert isinstance(reply,str)
   calls=result.get('per_call_usage',[])
   lower=reply.lower()
   raw_lower=''.join(stream_parts).lower()
   warnings=('не психотерапия','не медицинская помощь')
   report.append({'case':index+1,'terminal_count':terminals,'errors':errors,
    'reply_present':bool(reply.strip()),
    'failed_outcome':(result.get('metadata') or {}).get('execution_status')=='failed',
    'offers':offers,'receipt_count':len(calls),
    'gigachat_only':bool(calls) and all(c.get('provider')=='gigachat' for c in calls),
    'authoring_model_exact':all(c.get('model')=='GigaChat-2-Max'
      for c in calls if not c.get('kind') or c.get('kind')=='chat'),
    'psychological_appendix': 'не психотерапия' in lower or 'не медицинская помощь' in lower,
    'platform_psychological_appendix':any(w in lower and w not in raw_lower for w in warnings),
    'wrong_user_address':bool(re.search(r'привет[,! ]+алина',lower)),
    'provider_refusal':'чувствительными темами' in lower or 'временно ограничены' in lower,
    'hidden_motives':'за таким вопросом' in lower or 'скрывается желание' in lower,
    'prompt':sum(int(c.get('prompt',0)) for c in calls),
    'completion':sum(int(c.get('completion',0)) for c in calls),
    'seconds':round(time.monotonic()-start,2)})
   history.extend([{'role':'user','content':query},{'role':'assistant','content':reply}])
 print(json.dumps({'cases':report}))
try:
 asyncio.run(main())
except BaseException:
 print(json.dumps({'status':'failed','stage':'conversation_pipeline','cases':report}))
 raise SystemExit(1)
"""


@pytest.mark.skipif(
    os.getenv("S37_LIVE_CONVERSATION") != "1", reason="explicit metered GigaChat replay"
)
def test_five_turn_conversation_keeps_roles_and_natural_greetings():
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-backend-1", "python", "-c", _PROBE],
        input=json.dumps(
            {
                "inputs": [
                    "как дела чел",
                    "у тебя был секс когда нибудь?",
                    "ты Алина 28 лет",
                    "привет",
                    "не я Алина, а ты Алина",
                ]
            }
        ),
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=660,
        check=False,
    )
    report = json.loads(result.stdout)
    # Only closed outcomes and aggregate usage enter the acceptance output.
    print(json.dumps(report))
    assert result.returncode == 0, "conversation_pipeline_unavailable"
    cases = report["cases"]
    assert len(cases) == 5
    assert all(c["gigachat_only"] and c["authoring_model_exact"] for c in cases)
    assert all(c["terminal_count"] == 1 and c["errors"] == 0 and c["offers"] == 0 for c in cases)
    assert all(c["reply_present"] and not c["failed_outcome"] for c in cases)
    for index in (0, 2, 3, 4):
        assert not cases[index]["platform_psychological_appendix"]
    for index in (0, 3):
        assert not cases[index]["psychological_appendix"]
        assert not cases[index]["wrong_user_address"]
        assert not cases[index]["hidden_motives"]
        assert not cases[index]["provider_refusal"]
