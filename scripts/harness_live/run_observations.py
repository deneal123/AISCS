"""Приёмочная диагностика транспорта: без запросов, ответов и токенов доступа."""

from fastapi import Header


class ObserveRuns:
    def __init__(self, app, rows):
        self.app, self.rows = app, rows

    async def __call__(self, scope, receive, send):
        if scope.get("path") != "/run":
            return await self.app(scope, receive, send)
        observed = {"status": None, "completed": False}
        self.rows.append(observed)
        del self.rows[:-16]

        async def observed_send(message):
            if message["type"] == "http.response.start":
                observed["status"] = message["status"]
            if message["type"] == "http.response.body" and not message.get("more_body"):
                observed["completed"] = True
            await send(message)

        try:
            return await self.app(scope, receive, observed_send)
        except BaseException as error:
            name = type(error).__name__
            observed["failure"] = (
                name
                if name
                in {
                    "RuntimeError",
                    "AttributeError",
                    "TypeError",
                    "ValueError",
                    "CancelledError",
                    "AssertionError",
                    "ExceptionGroup",
                }
                else "internal"
            )
            raise


def install_run_observations(app):
    from service.presentation.deps import internal_auth

    rows = []
    app.add_middleware(ObserveRuns, rows=rows)

    @app.get("/__harness_acceptance__/runs", include_in_schema=False)
    async def observations(authorization: str | None = Header(default=None)):
        internal_auth(authorization)
        return rows
