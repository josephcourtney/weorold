"""Shared JSON loading, JSON Schema validation, and deterministic writing."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import cast

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError as JsonSchemaLibraryError
from jsonschema.exceptions import ValidationError
from jsonschema.protocols import Validator

JsonScalar = None | bool | int | float | str
JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject = dict[str, JsonValue]
JsonPathPart = str | int

SCHEMA_DIRECTORY = Path(__file__).resolve().parent / "schemas"
_SCHEMA_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.schema\.json$")
_REQUIRED_PROPERTY_PATTERN = re.compile(r"^'(?P<name>.*)' is a required property$")


class JsonDocumentError(ValueError):
    """Base class for errors involving a JSON document or its schema."""


class JsonSyntaxError(JsonDocumentError):
    """A document or schema is not syntactically valid JSON."""


class JsonSchemaDefinitionError(JsonDocumentError):
    """A repository-owned JSON Schema is invalid."""


@dataclass(frozen=True)
class JsonValidationIssue:
    """One JSON Schema violation at a concrete instance path."""

    path: tuple[JsonPathPart, ...]
    keyword: str
    message: str

    def __str__(self) -> str:
        return f"{_json_path(self.path)}: {self.message} [{self.keyword}]"


class JsonValidationError(JsonDocumentError):
    """A JSON value does not conform to a repository-owned schema."""

    def __init__(
        self,
        source: str,
        schema_name: str,
        issues: tuple[JsonValidationIssue, ...],
    ) -> None:
        self.source = source
        self.schema_name = schema_name
        self.issues = issues
        details = "\n".join(f"  - {issue}" for issue in issues)
        super().__init__(
            f"{source}: validation against {schema_name} failed with "
            f"{len(issues)} issue(s):\n{details}"
        )


class JsonSemanticError(JsonDocumentError):
    """A structurally valid JSON document violates a domain rule."""


def normalize_json(value: object, *, path: str = "$") -> JsonValue:
    """Convert JSON-compatible Python containers to canonical JSON containers."""
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise JsonSemanticError(f"{path}: non-finite numbers are not valid JSON")
        return value
    if isinstance(value, Mapping):
        output: JsonObject = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise JsonSemanticError(f"{path}: JSON object keys must be strings")
            output[key] = normalize_json(item, path=f"{path}.{key}")
        return output
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [normalize_json(item, path=f"{path}[{index}]") for index, item in enumerate(value)]
    raise JsonSemanticError(f"{path}: unsupported JSON value type {type(value).__name__}")


def _schema_path(schema_name: str) -> Path:
    if not _SCHEMA_NAME_PATTERN.fullmatch(schema_name):
        raise JsonSchemaDefinitionError(f"invalid schema name: {schema_name!r}")
    path = (SCHEMA_DIRECTORY / schema_name).resolve()
    if path.parent != SCHEMA_DIRECTORY.resolve():
        raise JsonSchemaDefinitionError(f"schema escapes schema directory: {schema_name!r}")
    return path


def _decode_json(text: str, source: str) -> JsonValue:
    try:
        return cast(JsonValue, json.loads(text))
    except json.JSONDecodeError as error:
        raise JsonSyntaxError(
            f"{source}:{error.lineno}:{error.colno}: invalid JSON: {error.msg}"
        ) from error


@cache
def _validator(schema_name: str) -> Validator:
    schema_path = _schema_path(schema_name)
    try:
        schema_text = schema_path.read_text(encoding="utf-8")
    except OSError as error:
        raise JsonSchemaDefinitionError(f"could not read schema {schema_path}: {error}") from error
    try:
        schema = _decode_json(schema_text, str(schema_path))
    except JsonSyntaxError as error:
        raise JsonSchemaDefinitionError(str(error)) from error
    if not isinstance(schema, dict):
        raise JsonSchemaDefinitionError(f"{schema_path}: schema root must be an object")
    try:
        Draft202012Validator.check_schema(schema)
    except JsonSchemaLibraryError as error:
        raise JsonSchemaDefinitionError(
            f"{schema_path}: invalid JSON Schema: {error.message}"
        ) from error
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _json_path(parts: tuple[JsonPathPart, ...]) -> str:
    path = "$"
    for part in parts:
        if isinstance(part, int):
            path += f"[{part}]"
        elif part.isidentifier():
            path += f".{part}"
        else:
            path += f"[{json.dumps(part, ensure_ascii=False)}]"
    return path


def _error_path(error: ValidationError) -> tuple[JsonPathPart, ...]:
    parts = tuple(error.absolute_path)
    if error.validator == "required":
        match = _REQUIRED_PROPERTY_PATTERN.match(error.message)
        if match is not None:
            return (*parts, match.group("name"))
    return parts


def _error_sort_key(error: ValidationError) -> tuple[tuple[str, ...], str, str]:
    return (
        tuple(str(part) for part in _error_path(error)),
        str(error.validator),
        error.message,
    )


def validate_json(value: object, schema_name: str, *, source: str = "<value>") -> JsonValue:
    normalized = normalize_json(value)
    errors = sorted(_validator(schema_name).iter_errors(normalized), key=_error_sort_key)
    if errors:
        issues = tuple(
            JsonValidationIssue(
                path=_error_path(error),
                keyword=str(error.validator),
                message=error.message,
            )
            for error in errors
        )
        raise JsonValidationError(source, schema_name, issues)
    return normalized


def loads_json(text: str, schema_name: str, *, source: str = "<string>") -> JsonValue:
    return validate_json(_decode_json(text, source), schema_name, source=source)


def loads_object(text: str, schema_name: str, *, source: str = "<string>") -> JsonObject:
    value = loads_json(text, schema_name, source=source)
    if not isinstance(value, dict):
        msg = f"object schema {schema_name} accepted a non-object value"
        raise JsonSchemaDefinitionError(msg)
    return value


def load_json(path: Path, schema_name: str) -> JsonValue:
    return loads_json(path.read_text(encoding="utf-8"), schema_name, source=str(path))


def load_object(path: Path, schema_name: str) -> JsonObject:
    value = load_json(path, schema_name)
    if not isinstance(value, dict):
        msg = f"object schema {schema_name} accepted a non-object value"
        raise JsonSchemaDefinitionError(msg)
    return value


def canonical_json(value: object) -> str:
    return json.dumps(
        normalize_json(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def write_json(
    path: Path,
    value: object,
    schema_name: str,
    *,
    indent: int = 2,
    sort_keys: bool = True,
) -> None:
    validated = validate_json(value, schema_name, source=str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            validated,
            indent=indent,
            sort_keys=sort_keys,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
