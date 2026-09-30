import click

from .._doctor import passed, render_json, render_text, run_checks


@click.command()
@click.option("--json", "as_json", is_flag=True, help="Output results as JSON.")
@click.pass_context
def doctor(ctx: click.Context, as_json: bool) -> None:
    """Check that this machine can run and develop ranges.

    Exits with status 1 if any check fails (warnings don't fail).
    """
    results = run_checks()
    click.echo(render_json(results) if as_json else render_text(results))
    ctx.exit(0 if passed(results) else 1)
