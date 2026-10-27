"""Провайдеры LLM: пять клиентов и общая машинерия, из которой они собраны.

Здесь всё, что знает про КОНКРЕТНЫХ провайдеров, и ничего, что знает про их применение:
маршрутизацию, фейловер и сборку ответа делают соседние пакеты.

    spec.py       ProviderSpec — чем один провайдер отличается от другого
    runtime.py    ФАБРИКА: одна обвязка на всех + хуки на экзотику
    mws.py / openrouter.py / routerai.py — декларации простых адаптеров
    gigachat/     адаптер, OAuth, изображения, schema/function dialect
    openai/       нативный адаптер и общий OpenAI-compatible протокол
    management/   admission, generations, inventory, snapshots и lifecycle
    transports/   HTTP/proxy construction и optional SDK binding
    ../models/    catalogs, qualification, requirements и model-list cache
    credentials.py        runtime-override ключей из админки

⚠️ Пакет НИЧЕГО не реэкспортит. Провайдер адресуется через `registry`, а не импортом
конкретного модуля: имя провайдера — это строка из настроек, и разрешать её должен
реестр. Прямой импорт `providers.mws` уместен только в тестах этого провайдера.
"""
