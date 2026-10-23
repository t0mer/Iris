"""Catch API field drift in the main hand-written portal models."""

import re
from pathlib import Path

import pytest
from pydantic import BaseModel

from app.api.alerts import AlertOut
from app.api.instances import InstanceOut
from app.api.messages import MessageOut


@pytest.mark.parametrize(
    "name,model", [("Message", MessageOut), ("Alert", AlertOut), ("Instance", InstanceOut)]
)
def test_frontend_fields_exist_in_api_schema(name: str, model: type[BaseModel]) -> None:
    source = (Path(__file__).parents[1] / "web/src/lib/types.ts").read_text(encoding="utf-8")
    match = re.search(r"export interface " + name + r"\s*\{(.*?)\n\}", source, re.S)
    assert match
    fields = set(re.findall(r"^\s+(\w+)\??:", match.group(1), re.M))
    assert fields <= set(model.model_json_schema()["properties"]), fields - set(model.model_fields)
