from pathlib import Path
from typing import Annotated

import typer
import yaml

from mrs import discovery_handler, engine
from mrs.config import get_config
from mrs.errors import ConfigurationError, MrsErrorBase
from mrs.logger import configure_logging, logger
from mrs.models.report import SyncReport
from mrs.models.sync_spec import SyncConfig
from mrs.providers.github import GitHubProvider

# Passed to --report-file to write the JSON report to stdout instead of a file.
STDOUT_TARGET = "-"

app = typer.Typer(
    help="Synchronize files across multiple repositories from a single source.",
    no_args_is_help=True,
)


@app.callback()
def _configure(
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Log the start of each action, not just results.")] = False,
):
    configure_logging(verbose=verbose)


def _load_sync_config(config_path: Path) -> SyncConfig:
    if not config_path.exists():
        raise ConfigurationError(f"config file not found: {config_path}")

    raw_data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    sync_config = SyncConfig.model_validate(raw_data)
    return sync_config


def _build_provider() -> GitHubProvider:
    config = get_config()
    if config.github_token is None:
        raise ConfigurationError("no GitHub token resolved")

    provider = GitHubProvider(
        token=config.github_token,
        api_base_url=config.github_api_base_url,
        request_timeout_seconds=config.request_timeout_seconds,
    )
    return provider


def _report_has_errors(report: SyncReport) -> bool:
    has_errors = any(
        target.error is not None
        for rule_report in report.rules
        for target in rule_report.targets
    )
    return has_errors


@app.command()
def sync(
    config_path: Annotated[Path, typer.Option("--config", help="Path to the sync config YAML.")],
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Report changes without writing them.")] = False,
    report_file: Annotated[str | None, typer.Option("--report-file", help="Write the JSON report here; use '-' for stdout.")] = None,
):
    provider = None
    try:
        sync_config = _load_sync_config(config_path)
        provider = _build_provider()
        report = engine.run_sync(sync_config, dry_run, provider)
    except MrsErrorBase as error:
        logger.error(str(error))
        raise typer.Exit(code=1)
    finally:
        if provider is not None:
            provider.close()

    if report_file is not None:
        report_json = report.model_dump_json(indent=2)
        if report_file == STDOUT_TARGET:
            print(report_json)
        else:
            output_path = Path(report_file)
            output_path.write_text(report_json + "\n", encoding="utf-8")
            logger.info(f"wrote JSON report to {output_path}")

    exit_code = 1 if _report_has_errors(report) else 0
    raise typer.Exit(code=exit_code)


@app.command()
def discover(
    config_path: Annotated[Path, typer.Option("--config", help="Path to the sync config YAML.")],
):
    provider = None
    try:
        sync_config = _load_sync_config(config_path)
        provider = _build_provider()
        for rule in sync_config.rules:
            result = discovery_handler.discover_targets(rule.targets, sync_config.owner, provider)
            logger.info(f"rule '{rule.name}': {len(result.included)} target(s)")
            for repository in result.included:
                print(f"  + {repository.full_name}")
            for excluded in result.excluded:
                print(f"  - {excluded.repository} ({excluded.reason})")
    except MrsErrorBase as error:
        logger.error(str(error))
        raise typer.Exit(code=1)
    finally:
        if provider is not None:
            provider.close()


def main():
    app()
