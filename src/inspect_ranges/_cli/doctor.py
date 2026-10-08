import click

from .._doctor import passed, render_fix_script, render_json, render_text, run_checks


@click.command()
@click.option("--json", "as_json", is_flag=True, help="Output results as JSON.")
@click.option(
    "--fix-script",
    "fix_script",
    is_flag=True,
    help="Print a shell script applying the runnable fixes for this machine's failed checks (pipe it to `sudo sh`).",
)
@click.pass_context
def doctor(ctx: click.Context, as_json: bool, fix_script: bool) -> None:
    """Check that this machine can run and develop ranges.

    Exits with status 1 if any check fails (warnings don't fail).

    With `--fix-script`, prints a reviewable shell script of the runnable fixes instead of the report, and exits 0; fixes that need human judgment are included as comments.
    """
    if as_json and fix_script:
        raise click.UsageError("--json and --fix-script are mutually exclusive.")
    results = run_checks()
    if fix_script:
        click.echo(render_fix_script(results), nl=False)
        ctx.exit(0)
    click.echo(render_json(results) if as_json else render_text(results))
    ctx.exit(0 if passed(results) else 1)
