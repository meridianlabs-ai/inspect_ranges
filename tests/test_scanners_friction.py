"""The friction scanner's answer schema, which is prompt text rather than documentation."""

from typing import Any, cast

import pytest
from inspect_ranges._scanners.friction import CATEGORIES, QUESTION, FrictionReport
from inspect_ranges.scanners import range_friction

Schema = dict[str, Any]


def properties_of(schema: Schema) -> dict[str, Schema]:
    """A schema's own properties, by name."""
    return cast("dict[str, Schema]", schema.get("properties") or {})


def schema_properties(schema: Schema) -> list[tuple[str, Schema]]:
    """Every property in the schema and its definitions, as `(path, property)` pairs."""
    definitions = cast("dict[str, Schema]", schema.get("$defs") or {})
    nested = [
        (f"{name}.{prop}", value)
        for name, definition in definitions.items()
        for prop, value in properties_of(definition).items()
    ]
    return nested + list(properties_of(schema).items())


def test_every_answer_field_carries_a_description() -> None:
    """A property without a description makes the scan refuse to start.

    Scout renders these descriptions into the structured-answer tool the model
    sees, so an undescribed field is a missing instruction, and scout raises
    `PrerequisiteError` before the first transcript rather than scanning
    blindly. Attribute docstrings only reach the schema because the models set
    `use_attribute_docstrings`, which is easy to drop in a refactor.
    """
    missing = [
        path
        for path, prop in schema_properties(FrictionReport.model_json_schema())
        if not prop.get("description")
    ]
    assert not missing, f"answer schema properties with no description: {missing}"


@pytest.mark.parametrize("category", CATEGORIES)
def test_every_category_is_explained_in_the_question(category: str) -> None:
    """A category the model can choose but the prompt never defines invites guesses."""
    assert f"`{category}`" in QUESTION


def test_question_separates_environment_defects_from_task_difficulty() -> None:
    """The scanner's whole value is this distinction, so the prompt must state it.

    Without it the scanner reports every failed sample, which is the same as
    reporting nothing.
    """
    assert "Do NOT report" in QUESTION
    assert "empty findings list" in QUESTION


def test_scanner_constructs() -> None:
    """The factory returns a callable scanner (registration happens at import)."""
    assert callable(range_friction())
