import pytest
from pydantic import ValidationError

from inference.schema import OutputSchema


def test_validates_output_json() -> None:
    output = OutputSchema.model_validate_json('{"text":"hello"}')

    assert output.text == "hello"


@pytest.mark.parametrize(
    "content",
    [
        "{}",
        '{"text":1}',
        '{"text":"hello","extra":"not allowed"}',
        "not json",
    ],
)
def test_rejects_invalid_output_json(content: str) -> None:
    with pytest.raises(ValidationError):
        OutputSchema.model_validate_json(content)


def test_generates_json_schema_for_text_only() -> None:
    schema = OutputSchema.model_json_schema()

    assert schema["type"] == "object"
    assert schema["required"] == ["text"]
    assert schema["properties"]["text"]["type"] == "string"
    assert schema["properties"]["text"]["description"] == "Assistant response text"
    assert schema["additionalProperties"] is False
