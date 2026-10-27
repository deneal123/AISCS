"""Validation feedback identifies declared fields without reflecting user data."""

import json

import pytest
from fastapi import FastAPI, Query
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, Field, field_validator
from pydantic_core import PydanticCustomError
from starlette.requests import Request

from service.shared.presentation.handlers.exceptions_handlers import (
    setup_exception_handlers,
    validation_exception_handler,
)

MARKER = "PRIVATE_VALIDATION_PASSWORD_REQUEST_MARKER"


class Input(BaseModel):
    password: str
    values: dict[str, int]

    @field_validator("password")
    @classmethod
    def validate_password(cls, value):
        raise ValueError(value)


@pytest.mark.asyncio
async def test_user_validator_message_and_dynamic_dict_key_are_not_reflected():
    app = FastAPI()
    setup_exception_handlers(app)

    @app.post("/validate")
    async def validate(payload: Input):
        return {}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://fixture") as client:
        response = await client.post(
            "/validate", json={"password": MARKER, "values": {MARKER: "not-an-int"}}
        )
    assert response.status_code == 422
    assert MARKER not in response.text
    details = response.json()["error"]["details"]
    assert {item["field"] for item in details} == {"body.password", "body.values.*"}
    assert {item["type"] for item in details} == {"value_error", "int_parsing"}


@pytest.mark.asyncio
async def test_custom_error_code_and_context_do_not_become_public_values():
    class CustomInput(BaseModel):
        value: str

        @field_validator("value")
        @classmethod
        def validate_value(cls, value):
            raise PydanticCustomError(value, value, {"private": value})

    app = FastAPI()
    setup_exception_handlers(app)

    @app.post("/validate")
    async def validate(payload: CustomInput):
        return {}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://fixture") as client:
        response = await client.post("/validate", json={"value": MARKER})
    assert response.status_code == 422
    assert MARKER not in response.text
    detail = response.json()["error"]["details"][0]
    assert detail["field"] == "body.value"
    assert detail["type"] == "value_error"


@pytest.mark.asyncio
async def test_declared_alias_nested_field_and_query_location_stay_useful():
    class Item(BaseModel):
        amount: int = Field(alias="total")

    class Payload(BaseModel):
        items: list[Item]

    app = FastAPI()
    setup_exception_handlers(app)

    @app.post("/validate/{thread_id}")
    async def validate(thread_id: int, payload: Payload, limit: int = Query()):
        return {}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://fixture") as client:
        response = await client.post(
            "/validate/not-int", params={"limit": "not-int"}, json={"items": [{"total": "bad"}]}
        )
    assert response.status_code == 422
    details = response.json()["error"]["details"]
    assert {detail["field"] for detail in details} == {
        "body.items.0.total",
        "query.limit",
        "path.thread_id",
    }
    assert all(detail["type"] == "int_parsing" for detail in details)
    assert all(set(detail) == {"field", "message", "type"} for detail in details)


@pytest.mark.asyncio
async def test_extra_field_key_and_value_never_echo_back():
    class StrictInput(BaseModel):
        model_config = {"extra": "forbid"}
        title: str

    app = FastAPI()
    setup_exception_handlers(app)

    @app.post("/validate")
    async def validate(payload: StrictInput):
        return {}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://fixture") as client:
        response = await client.post("/validate", json={"title": "ok", MARKER: MARKER})
    assert response.status_code == 422
    assert MARKER not in response.text
    assert response.json()["error"]["details"][0]["field"] == "body.*"


@pytest.mark.asyncio
async def test_no_route_errors_are_bounded_without_stringifying_private_object():
    class Private:
        def __str__(self):
            raise AssertionError("Private object must not be stringified")

    request = Request({"type": "http", "headers": []})
    error = RequestValidationError(
        [{"loc": ("body", MARKER, Private()), "msg": MARKER, "type": MARKER, "input": MARKER}]
    )
    response = await validation_exception_handler(request, error)
    assert response.status_code == 422
    assert MARKER.encode() not in response.body
    assert json.loads(response.body)["error"]["details"][0]["type"] == "value_error"


@pytest.mark.asyncio
async def test_large_validation_response_is_bounded():
    request = Request({"type": "http", "headers": []})
    error = RequestValidationError(
        [{"loc": ("body", MARKER), "msg": MARKER, "type": "value_error"}] * 1000
    )
    response = await validation_exception_handler(request, error)
    assert response.status_code == 422
    assert len(json.loads(response.body)["error"]["details"]) <= 50
    assert MARKER.encode() not in response.body
    assert json.loads(response.body)["error"]["details"][-1]["message"] == (
        "Additional validation errors omitted"
    )


@pytest.mark.asyncio
async def test_missing_field_and_malformed_json_keep_safe_actionable_feedback():
    class Payload(BaseModel):
        title: str

    app = FastAPI()
    setup_exception_handlers(app)

    @app.post("/validate")
    async def validate(payload: Payload):
        return {}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://fixture") as client:
        missing = await client.post("/validate", json={})
        malformed = await client.post(
            "/validate",
            content='{"private":"' + MARKER,
            headers={"Content-Type": "application/json"},
        )
    assert missing.status_code == 422
    assert missing.json()["error"]["details"] == [
        {"field": "body.title", "message": "Field required", "type": "missing"}
    ]
    assert malformed.status_code == 422
    assert MARKER not in malformed.text
    assert malformed.json()["error"]["details"][0]["type"] == "json_invalid"


@pytest.mark.asyncio
async def test_route_aliases_do_not_leak_between_requests():
    class OwnedNames(BaseModel):
        permitted: int

    class OtherNames(BaseModel):
        values: dict[str, int]

    app = FastAPI()
    setup_exception_handlers(app)

    @app.post("/first")
    async def first(payload: OwnedNames):
        return {}

    @app.post("/second")
    async def second(payload: OtherNames):
        return {}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://fixture") as client:
        first_response = await client.post("/first", json={"permitted": "bad"})
        second_response = await client.post("/second", json={"values": {"permitted": "bad"}})
    assert first_response.json()["error"]["details"][0]["field"] == "body.permitted"
    assert second_response.json()["error"]["details"][0]["field"] == "body.values.*"
