"""Два пути исполнения агента, разнесённые по файлам.

`SimpleStreamingAgent` держал оба сразу и весил 741 строку. Это не варианты одного
алгоритма: SDK сам ведёт цикл инструментов и отдаёт свои события, прямой стрим ведёт
цикл сам. Метод `process()` остался диспетчером — начало, гардрейлы, выбор пути.

    sdk_run.py   через Agents SDK (Responses-стрим) + аварийный chat/completions
    chat_run.py  прямой chat/completions-стрим — для провайдеров, у которых SDK-стрим
                 ненадёжен (mws, openrouter, gigachat, routerai)
"""

from service.domain.runners.chat_run import ChatRunMixin
from service.domain.runners.sdk_run import SdkRunMixin

__all__ = ["ChatRunMixin", "SdkRunMixin"]
