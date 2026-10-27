"""Deterministic provider HTTP replies below SDK/auth/compiler, never tool doubles."""

import asyncio
import json
import os
import time
from urllib.parse import urlsplit

import httpx

from scripts.harness_live.providers import MODELS, function_message
from scripts.harness_live.refinement import TOOL as REFINEMENT_TOOL
from scripts.harness_live.refinement import has_guidance, proposal
from scripts.harness_live.scenarios import next_step

PRIVATE_STATE = "ACCEPTANCE_PRIVATE_PROVIDER_STATE"


class ScriptedProvider:
    def __init__(self):
        self.scenario = os.environ.get("HARNESS_ACCEPTANCE_SCENARIO", "hello")
        self.provider = os.environ.get("HARNESS_ACCEPTANCE_PROVIDER", "gigachat")
        self.model = MODELS[self.provider]
        self.completions = 0
        self.tool_names = []
        self.blocked_requests = 0
        self.oauth = 0
        self.tool_states = {}
        self.read_barrier_waiting = False
        self.release_read = asyncio.Event()

    @staticmethod
    def completed_tools(messages):
        names = {}
        completed = []
        for message in messages:
            for call in message.get("tool_calls") or []:
                names[call["id"]] = call["function"]["name"]
            if message.get("role") == "function":
                completed.append(message.get("name"))
            if message.get("role") == "tool":
                completed.append(names.get(message.get("tool_call_id")))
        return completed

    def completion(self, request):
        payload = json.loads(request.content)
        assert payload["model"] == self.model
        self.completions += 1
        messages = payload["messages"]
        functions = payload.get("functions") or [
            item["function"] for item in payload.get("tools", [])
        ]
        contract = [item["name"] for item in functions] == ["submit_task_contract"]
        refinement = [item["name"] for item in functions] == [REFINEMENT_TOOL]
        if refinement:
            assert self.scenario in {"refine", "lesson_reuse"}
            function, content = proposal(), ""
        elif contract:
            from scripts.harness_live.long_run import criteria

            function = (
                "submit_task_contract",
                {
                    "kind": "change",
                    "criteria": criteria()
                    if self.scenario == "long"
                    else [{"criterion_id": "script", "kind": "file", "target": "hello_world.py"}],
                    "needs_clarification": self.scenario == "clarify"
                    and not self.answered(messages),
                    "question": "Как назвать создаваемый Python-файл?"
                    if self.scenario == "clarify" and not self.answered(messages)
                    else "",
                },
            )
            if self.scenario == "pdf_review":
                from scripts.harness_live.pdf_review import contract as pdf_contract

                function = ("submit_task_contract", pdf_contract())
            if self.scenario in {"lesson_reuse", "read_change", "question_change"}:
                from scripts.harness_live.lesson_reuse import CONTRACT

                function = ("submit_task_contract", CONTRACT)
            content = ""
        elif (
            self.scenario in {"read_change", "question_change"}
            and not functions
            and str(messages[0].get("content", "")).startswith("Ты выбираешь, какие")
        ):
            function = None
            content = json.dumps({"tools": ["ide_read_file"], "preferred_tool": "ide_read_file"})
        else:
            completed = self.completed_tools(messages)
            if self.provider == "gigachat" and completed and completed[-1] in self.tool_states:
                previous = next(
                    message for message in reversed(messages) if message.get("function_call")
                )
                assert previous.get("functions_state_id") == self.tool_states[completed[-1]], (
                    "acceptance_provider_state_stale"
                )
            if self.scenario == "clarify":
                assert any(
                    "Уточнение задачи пользователем" in str(message.get("content", ""))
                    and "hello_world.py" in str(message.get("content", ""))
                    for message in messages
                ), "acceptance_answer_missing_from_product_input"
            if (
                self.scenario in {"refine", "lesson_reuse"}
                and not completed
                and not has_guidance(messages)
            ):
                function = None
            else:
                if self.scenario in {"refine", "lesson_reuse"}:
                    assert has_guidance(messages), "refinement_guidance_missing"
                if self.scenario in {"lesson_reuse", "read_change"}:
                    from scripts.harness_live.lesson_reuse import next_step as next_read

                    function = next_read(completed)
                elif self.scenario == "question_change":
                    from scripts.harness_live.question_change import next_step as next_question

                    function = next_question(completed)
                elif self.scenario == "pdf_review":
                    from scripts.harness_live.pdf_review import next_step as next_pdf_step

                    function = next_pdf_step(completed)
                else:
                    scenario = (
                        "hello"
                        if self.scenario in {"clarify", "refine", "finish"}
                        else self.scenario
                    )
                    function = next_step(
                        scenario,
                        completed,
                    )
                if (
                    self.scenario == "finish"
                    and function
                    and function[0] == "ide_finish_task"
                    and [item["name"] for item in functions] != ["ide_finish_task"]
                ):
                    function = None
            content = "Скрипт создан и проверен запуском." if function is None else ""
            if self.scenario == "repair" and completed.count("ide_run_command") == 1:
                from scripts.harness_live.verification_repair import decide

                function, content = decide(function, messages, functions)
            if self.scenario == "pdf_review" and function is None:
                content = "Предложение трёх слайдов сохранено для просмотра. PDF ещё не собран."
        message = {"role": "assistant", "content": content}
        reason = "stop"
        if function:
            fields, reason = function_message(
                payload, function, provider=self.provider, index=self.completions
            )
            message.update(fields)
            if self.provider == "gigachat":
                state_id = f"{PRIVATE_STATE}_{self.completions}"
                message["functions_state_id"] = state_id
                self.tool_states[function[0]] = state_id
            if not contract and not refinement:
                self.tool_names.append(function[0])
        base = {
            "id": "acceptance-completion",
            "created": 0,
            "model": payload["model"],
            "usage": {"prompt_tokens": 128, "completion_tokens": 16, "total_tokens": 144},
        }
        if payload.get("stream"):
            chunk = {
                **base,
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": message, "finish_reason": reason}],
            }
            body = "data: " + json.dumps(chunk) + "\n\ndata: [DONE]\n\n"
            return httpx.Response(
                200, content=body.encode(), headers={"content-type": "text/event-stream"}
            )
        return httpx.Response(
            200,
            json={
                **base,
                "object": "chat.completion",
                "choices": [{"index": 0, "message": message, "finish_reason": reason}],
            },
        )

    @staticmethod
    def answered(messages):
        for message in messages:
            if message.get("role") not in {"tool", "function"}:
                continue
            try:
                value = json.loads(message.get("content") or "{}")
                if (
                    message.get("role") == "function"
                    and isinstance(value, dict)
                    and set(value) == {"result"}
                ):
                    value = json.loads(value["result"])
            except (ValueError, TypeError):
                continue
            answer = value.get("answer") if isinstance(value, dict) else None
            if isinstance(answer, dict) and answer.get("text") == "hello_world.py":
                return True
        return False

    def install(self):
        from service.settings import config

        provider_hosts = {
            urlsplit(value).hostname
            for value in (
                config.agents.gigachat_base_url,
                config.agents.gigachat_oauth_url,
                config.agents.openai_base_url,
                config.agents.routerai_base_url,
                config.agents.openrouter_base_url,
                config.agents.mws_base_url,
            )
            if value
        }
        provider_hosts |= {
            "gigachat.devices.sberbank.ru",
            "ngw.devices.sberbank.ru",
            "api.openai.com",
            "routerai.ru",
            "openrouter.ai",
        }
        original = httpx.AsyncHTTPTransport.handle_async_request
        owner = self

        async def handle(transport, request):
            if request.url.host in {"backend", "workspace"} and request.url.port in {8002, 8082}:
                return await original(transport, request)
            if request.url.host in provider_hosts:
                if request.url.path.endswith("/oauth"):
                    owner.oauth += 1
                    return httpx.Response(
                        200,
                        json={
                            "access_token": "fixture-oauth-token",
                            "expires_at": int((time.time() + 3600) * 1000),
                        },
                    )
                if request.method == "GET" and request.url.path.endswith("/models"):
                    return httpx.Response(
                        200,
                        json={
                            "object": "list",
                            "data": [
                                {
                                    "id": owner.model,
                                    "object": "model",
                                    "owned_by": owner.provider,
                                    "context_window": 131072,
                                    "capabilities": ["chat", "tools"],
                                }
                            ],
                        },
                    )
                if request.method == "POST" and request.url.path.endswith("/chat/completions"):
                    if (
                        owner.scenario == "read_change"
                        and owner.completed_tools(json.loads(request.content)["messages"])
                        == ["ide_read_file"]
                        and not owner.release_read.is_set()
                    ):
                        owner.read_barrier_waiting = True
                        await asyncio.wait_for(owner.release_read.wait(), timeout=90)
                    return owner.completion(request)
            owner.blocked_requests += 1
            raise httpx.ConnectError("acceptance_unexpected_transport", request=request)

        httpx.AsyncHTTPTransport.handle_async_request = handle
