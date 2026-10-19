"""OpenAPI 3.1 from dataclasses: the schema the web app's client is generated from.

A response body is a frozen dataclass, and a :class:`Route` names the one it
returns. :func:`document` walks every type the routes reach and puts each
dataclass in ``components/schemas`` once, so a model is declared in one place
and the schema can't drift from it. OpenAPI 3.1 uses JSON Schema 2020-12:
``X | None`` is ``"type": ["x", "null"]``, a tuple or list is an array, and
every field is required (a value that can be missing is ``null``, never absent).
A field's ``doc(...)`` text becomes its ``description``.

No pydantic: the pit wall's slim image carries aiohttp, DuckDB and PyYAML only
(#237 R9), and the mapping the models need is the few dozen lines below.

:func:`spec` is the schema of everything the browser reads from the pit wall's
origin. A module adds its routes there, as a tuple of :class:`Route` beside its
models; ``scripts/openapi.py`` writes the result to ``web/openapi.json`` and
``make check`` fails when the committed file is stale.
"""

from __future__ import annotations

import dataclasses
import json
import types
from dataclasses import dataclass, field
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints

# The document's own version. Not the package version: that changes every
# release, and the committed schema would go stale with it.
API_VERSION = "1"

_PRIMITIVES: dict[Any, str] = {str: "string", int: "integer", float: "number", bool: "boolean"}

_STATUS_TEXT = {
    200: "OK",
    304: "Not modified: nothing has changed since the ETag sent in If-None-Match",
    400: "A bad parameter",
    404: "No such session, lap or path",
    502: "The engineer did not answer",
    503: "Unhealthy, or the index is busy",
}


def doc(text: str, **kwargs: Any) -> Any:
    """A dataclass field with a description for the schema: ``x: int = doc("...")``."""
    return field(metadata={"doc": text}, **kwargs)


@dataclass(frozen=True, slots=True)
class ApiError:
    """The body of every error response."""

    error: str = doc("What went wrong, in a sentence")


@dataclass(frozen=True, slots=True)
class Param:
    """A path or query parameter. ``schema`` is its JSON Schema."""

    name: str
    where: Literal["path", "query"]
    description: str
    schema: dict[str, Any] = field(default_factory=lambda: {"type": "string"})


@dataclass(frozen=True, slots=True)
class Route:
    """One operation. ``response`` is the 200 body's type, a dataclass or any
    type :func:`schema_for` maps; ``errors`` are the statuses answered with
    :class:`ApiError`; ``etag`` adds the 304 a matching If-None-Match gets;
    ``unhealthy`` adds a 503 with the same body as the 200 (a health check)."""

    method: str
    path: str  # OpenAPI's form: /api/v1/sessions/{id}
    summary: str
    response: Any
    operation_id: str
    params: tuple[Param, ...] = ()
    errors: tuple[int, ...] = ()
    etag: bool = False
    unhealthy: bool = False
    tag: str = "pitwall"


def schema_for(tp: Any, components: dict[str, Any]) -> dict[str, Any]:
    """The JSON Schema of a type. A dataclass is added to ``components`` (by its
    class name, so two models must not share one) and referenced."""
    if tp is Any:
        return {}
    if tp is type(None):
        return {"type": "null"}
    if tp in _PRIMITIVES:
        return {"type": _PRIMITIVES[tp]}
    origin, args = get_origin(tp), get_args(tp)
    if origin in (Union, types.UnionType):
        parts = [schema_for(a, components) for a in args]
        if all(set(p) == {"type"} for p in parts):  # primitives and null: one type list
            return {"type": [p["type"] for p in parts]}
        return {"anyOf": parts}
    if origin is list or (origin is tuple and len(args) == 2 and args[1] is Ellipsis):
        return {"type": "array", "items": schema_for(args[0], components)}
    if origin is dict:
        return {"type": "object", "additionalProperties": schema_for(args[1], components)}
    if origin is Literal:
        return {"enum": list(args)}
    if dataclasses.is_dataclass(tp) and isinstance(tp, type):
        name = tp.__name__
        if name not in components:
            components[name] = {}  # claimed first, so a model that refers to itself ends
            components[name] = _object(tp, components)
        return {"$ref": f"#/components/schemas/{name}"}
    raise TypeError(f"no JSON Schema for {tp!r}")


def _object(cls: type, components: dict[str, Any]) -> dict[str, Any]:
    hints = get_type_hints(cls)
    props: dict[str, Any] = {}
    for f in dataclasses.fields(cls):
        prop = schema_for(hints[f.name], components)
        if "doc" in f.metadata:
            # A $ref takes no siblings in some generators: wrap it to describe it.
            prop = {"allOf": [prop]} if "$ref" in prop else dict(prop)
            prop["description"] = f.metadata["doc"]
        props[f.name] = prop
    out: dict[str, Any] = {"type": "object"}
    text = cls.__doc__ or ""
    if text and not text.startswith(f"{cls.__name__}("):  # not dataclass's own signature
        out["description"] = " ".join(text.split("\n\n")[0].split())
    out |= {"properties": props, "required": list(props), "additionalProperties": False}
    return out


def _json(schema: dict[str, Any], description: str) -> dict[str, Any]:
    return {"description": description, "content": {"application/json": {"schema": schema}}}


def _operation(route: Route, components: dict[str, Any]) -> dict[str, Any]:
    responses: dict[str, Any] = {"200": _json(schema_for(route.response, components), "OK")}
    if route.unhealthy:
        responses["503"] = _json(schema_for(route.response, components), "Unhealthy")
    if route.etag:
        responses["304"] = {"description": _STATUS_TEXT[304]}
    for status in route.errors:
        responses[str(status)] = _json(schema_for(ApiError, components), _STATUS_TEXT[status])
    op: dict[str, Any] = {
        "operationId": route.operation_id,
        "summary": route.summary,
        "tags": [route.tag],
    }
    if route.params:
        op["parameters"] = [
            {
                "name": p.name,
                "in": p.where,
                "required": p.where == "path",
                "description": p.description,
                "schema": p.schema,
            }
            for p in route.params
        ]
    op["responses"] = responses
    return op


def document(routes: tuple[Route, ...] | list[Route], title: str, description: str) -> dict:
    """The OpenAPI 3.1 document for ``routes``."""
    components: dict[str, Any] = {}
    paths: dict[str, dict[str, Any]] = {}
    for route in routes:
        paths.setdefault(route.path, {})[route.method.lower()] = _operation(route, components)
    return {
        "openapi": "3.1.0",
        "info": {"title": title, "version": API_VERSION, "description": description},
        "paths": paths,
        "components": {"schemas": dict(sorted(components.items()))},
    }


def spec() -> dict[str, Any]:
    """Everything the browser reads from the pit wall's origin. A module adds
    its routes here: ``routes = (*api_models.ROUTES, *other.ROUTES)``."""
    from those_who_run import status
    from those_who_run.pitwall import api_models

    routes = (*api_models.ROUTES, *status.ROUTES)
    return document(
        routes,
        title="Those Who Run: pit wall",
        description="The pit wall's read-only data API, and the engineer's routes it forwards.",
    )


def dump(document: dict[str, Any]) -> str:
    """The document as the committed file holds it."""
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"
