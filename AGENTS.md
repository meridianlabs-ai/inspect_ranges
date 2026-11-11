# AGENTS.md

## Principles

- Shortcuts become someone else's problem; hacks compound into debt
- Patterns get copied—establish good ones
- Flag issues; ask before fixing
- Strict typing required
  - Python: modern syntax (`X | None`, `dict[str, Any]`)
- Error handling: do not use Exceptions gratuitously, unless an error is expected in a context and needs to be computed on it should be allowed to propagate.
- Respect existing patterns
- Before committing, run the appropriate checks for code you touched (lint, typecheck, test)

### Testing
- Test observable behavior, not internal implementation details
- Do not test things that are enforced by the type system
- Test through the narrowest public API that covers the behavior
- Be efficient; avoid duplicate coverage
- Prefer data/table driven tests for maintainability
- Tests must be isolated; no shared mutable state or order dependencies
- Tests must be deterministic; control randomness with seeds
- Prefer real objects over mocks when possible

### Common Pitfalls
- Stay within scope—don't make unrequested changes
- During development, run only implicated tests; run the full suite when the work is complete

## Python

Directory: `src/inspect_ranges/`

### Scripts
| Command | Description |
|---------|-------------|
| `make check` | Run all checks (lint, format, typecheck) |
| `make typecheck` | Run typechecking only |
| `make test` | Run all tests |
| `pytest` | Run all tests |
| `pytest tests/path/to/test.py::test_name -v` | Run single test |
| `ruff format` | Format code |
| `ruff check --fix` | Lint and auto-fix |

### Style
- **Formatting**: Follow Google style convention. Use ruff for formatting
- **Imports**: Use isort order (enforced by ruff)
- **Types**: All functions must have type annotations, including in tests.
- **Naming**: Use snake_case for variables, functions, methods; PascalCase for classes
- **Docstrings**: Google-style docstrings required for public APIs. Use single backtick (`) around symbols. Do not use hard line breaks within paragraphs or list items — each paragraph should be a single unwrapped line, separated by blank lines.
- **Error Handling**: Use appropriate exception types; include context in error messages
- **Testing**: Write tests with pytest; maintain high coverage

### Common Pitfalls
- Use the venv for all Python commands: either reference `.venv/bin/` directly or run `source .venv/bin/activate`
- After you change dependencies in `pyproject.toml`, run `uv lock` and commit `uv.lock`. Don't override the cooldown. Everything else about dependencies is in [DEPENDENCIES.md](https://github.com/meridianlabs-ai/actions/blob/main/DEPENDENCIES.md) in meridianlabs-ai/actions

## Documentation

Docs live in `docs/` (Quarto `.qmd`). They should read like the sibling `inspect_petri` and `inspect_scout` packages: **simple, direct language**. Match that voice when writing or revising any page.

- **One idea per sentence.** Break semicolon-chained compound sentences into separate sentences; prose semicolons should be rare.
- **Cut reflexive counterfactuals.** Drop "X, never Y" when the positive statement already implies it. Keep the negative only when it is a genuine security or scoring-integrity guarantee.
- **State the rule, then stop.** Give the rule and (only if it is unclear without one) a short example. Cut edge cases and single-case caveats, or move a genuinely important one to a short "Current boundaries" callout at the end of the section (see `cli.qmd`). Prefer cutting over callout-ing.
- **No puffery or tics.** Avoid "the worked example/reference", "the asymmetry is deliberate", "one rule governs everything", and similar. Say the thing plainly; show a copy-pasteable example instead of characterizing it.
- **Collapse parentheticals.** Real content becomes its own sentence; minor content is cut. Avoid nested parentheticals.
- **Table cells are phrases, not paragraphs.** Move any detail that needs sentences into prose beneath the table.
- **`llms-description` is one short sentence**, like petri/scout (e.g. "Installation and tutorial on running your first audit."), not a contents dump.
- Keep every page's structure: `## Overview` first, "Learning More" links last, paired YAML+Python and bash+Python examples, and existing tables. Do not change a heading that forms an anchor without updating every inbound `page.qmd#anchor` link.

## Internal References

This is a public repository. Nothing that identifies internal or partner infrastructure may be committed, in any file or in commit message text:

- No infrastructure identifiers: cloud account IDs, bucket/storage names, internal hostnames, IAM role or user names, instance IDs, internal IP addresses, absolute home paths, internal URLs.
- No references to private or partner artifacts that a feature is being built for, in code comments, docs, design records, test names, or commit messages. Motivate features generically (what the capability is, not whose task needs it); the specific mapping lives in the private design store.
- Scripts and records that need an internal value (a bucket, a second host) take it from an environment variable or use a stated placeholder (`SCRATCH-BUCKET`, `devbox-b`), never the literal.

Definition of done: before completing any feature/slice, and before every commit, sweep the full diff (including the commit message) for internal references and eliminate them.

## Reviewing other people's pull requests

Unless a maintainer asked for your review, submit any review on someone else's pull request as a **Comment**, never **Approve** or **Request changes**. In this repository those are maintainer decisions: a non-maintainer's verdict doesn't count toward merging and misleads the author about where their PR stands. Put any confirmation or concern in the comment text, and say that you are an AI agent and not a maintainer. This does not apply to agents acting for project maintainers.
