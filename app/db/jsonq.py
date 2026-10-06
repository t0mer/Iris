"""JSON queries that differ between SQLite, PostgreSQL and MySQL."""

from typing import Any

from sqlalchemy import String, bindparam
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.compiler import SQLCompiler
from sqlalchemy.sql.elements import ClauseElement, ColumnElement
from sqlalchemy.types import Boolean


class json_array_contains(ColumnElement[bool]):  # noqa: N801 - reads like a SQL function
    """True when the JSON array in `column` contains the string `value`."""

    inherit_cache = True
    type = Boolean()

    def __init__(self, column: Any, value: str) -> None:
        self.column = column
        self.value = bindparam(None, value, type_=String(), unique=True)


def _parts(element: json_array_contains, compiler: SQLCompiler, **kw: Any) -> tuple[str, str]:
    return compiler.process(element.column, **kw), compiler.process(element.value, **kw)


@compiles(json_array_contains)
@compiles(json_array_contains, "sqlite")
def _sqlite(element: ClauseElement, compiler: SQLCompiler, **kw: Any) -> str:
    assert isinstance(element, json_array_contains)
    col, val = _parts(element, compiler, **kw)
    return f"EXISTS (SELECT 1 FROM json_each({col}) WHERE json_each.value = {val})"


@compiles(json_array_contains, "postgresql")
def _postgres(element: ClauseElement, compiler: SQLCompiler, **kw: Any) -> str:
    assert isinstance(element, json_array_contains)
    col, val = _parts(element, compiler, **kw)
    return f"jsonb_exists(CAST({col} AS JSONB), {val})"


@compiles(json_array_contains, "mysql")
def _mysql(element: ClauseElement, compiler: SQLCompiler, **kw: Any) -> str:
    assert isinstance(element, json_array_contains)
    col, val = _parts(element, compiler, **kw)
    return f"JSON_CONTAINS({col}, JSON_QUOTE({val}))"
