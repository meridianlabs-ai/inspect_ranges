# inspect_ranges – Inspect Ranges

Load a definition with `load_range`, or get complete diagnostics (every error at once, with source positions and hints) from `validate_range`. Typed specs crossing a consumer boundary are re-checked with `revalidate_range`.

## Loading

### load_range

Load and validate a `range.yaml` file.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/381e2b477de3ec92e6e0377f527939bfb5945428/src/inspect_ranges/schema.py#L196)

``` python
def load_range(path: Path) -> RangeSpec
```

`path` Path  
Path to the YAML file.

### validate_range

Validate a `range.yaml` file, reporting every detectable issue at once.

Unlike `load_range`, this never raises on invalid content: YAML syntax errors, structural schema violations, and semantic cross-reference problems all become [Issue](../reference/types.html.md#issue) entries with stable codes, source positions, and hints where available. Field-level structural errors suppress the cross-reference pass (reflected in `ValidationReport.semantic_checked`).

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/381e2b477de3ec92e6e0377f527939bfb5945428/src/inspect_ranges/schema.py#L134)

``` python
def validate_range(path: Path) -> ValidationReport
```

`path` Path  
Path to the YAML file.

### revalidate_range

Re-run full validation on a possibly mutated spec, returning a validated copy.

Spec models are mutable for flexible programmatic construction, so validity at construction is a point-in-time property. Consumer boundaries (the sandbox provider, the compiler) call this at handoff: the spec round-trips through `model_validate`, which catches semantic drift and type-unsafe mutations alike.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/381e2b477de3ec92e6e0377f527939bfb5945428/src/inspect_ranges/schema.py#L219)

``` python
def revalidate_range(spec: RangeSpec) -> RangeSpec
```

`spec` [RangeSpec](../reference/types.html.md#rangespec)  
The spec to re-check (typically one received as sandbox configuration).

## Checks and Schema

### semantic_issues

Run every cross-reference check on a structurally valid spec, collecting all findings.

This is the single implementation of the semantic checks: [RangeSpec](../reference/types.html.md#rangespec) validation calls it (raising if any issue is found, so a freshly constructed spec is always consistent), and `validate_range` calls it via that same validation to report every issue at once.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/381e2b477de3ec92e6e0377f527939bfb5945428/src/inspect_ranges/types.py#L962)

``` python
def semantic_issues(spec: RangeSpec) -> list[Issue]
```

`spec` [RangeSpec](../reference/types.html.md#rangespec)  
A structurally valid range definition.

### range_json_schema

Return the JSON Schema for `range.yaml` v0.1 (aliased field names, e.g. `from`).

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/381e2b477de3ec92e6e0377f527939bfb5945428/src/inspect_ranges/schema.py#L236)

``` python
def range_json_schema() -> dict[str, Any]
```
