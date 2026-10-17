from collections import Counter
from dataclasses import dataclass

from mrs import content_handler, discovery_handler, strategy_handler
from mrs.errors import ProviderError
from mrs.logger import logger
from mrs.models.report import (
    FileResult,
    RuleReport,
    SyncReport,
    TargetResult,
)
from mrs.models.sync_spec import Strategy, SyncConfig, SyncRule
from mrs.providers.base import DesiredFile, GitProvider, TargetRepository


@dataclass(frozen=True, slots=True)
class TargetEvaluation:
    file_results: list[FileResult]
    files_to_write: list[DesiredFile]


def _summarize_outcomes(result: TargetResult) -> str:
    if not result.files:
        return "no files"

    counts = Counter(file_result.outcome.value for file_result in result.files)
    summary = ", ".join(f"{count} {outcome}" for outcome, count in sorted(counts.items()))
    return summary


def _log_target_result(result: TargetResult, dry_run: bool):
    if result.error:
        logger.error(f"{result.repository}: {result.error}")
        return

    prefix = "would sync" if dry_run else "synced"
    detail = _summarize_outcomes(result)

    if result.pull_request_url:
        detail = f"{detail} -> {result.pull_request_url}"

    logger.info(f"{result.repository}: {prefix} ({detail})")


def _generate_branch_name(rule: SyncRule) -> str:
    branch = rule.branch_name or f"mrs/sync-{rule.name}"
    return branch


def _generate_commit_message(rule: SyncRule) -> str:
    message = rule.commit_message or f"mrs: sync '{rule.name}'"
    return message


def _deliver(
    repository: TargetRepository,
    evaluation: TargetEvaluation,
    rule: SyncRule,
    provider: GitProvider,
) -> TargetResult:
    message = _generate_commit_message(rule)
    if rule.strategy is Strategy.PUSH:
        commit_sha = provider.apply_push(repository, evaluation.files_to_write, message)
        result = TargetResult(
            repository=repository.full_name,
            strategy=rule.strategy,
            files=evaluation.file_results,
            commit_sha=commit_sha,
        )
        return result

    branch_name = _generate_branch_name(rule)
    title = rule.pull_request_title or f"mrs: sync '{rule.name}'"
    body = rule.pull_request_body or "Automated multi-repo sync by mrs."
    applied_pr = provider.apply_pull_request(
        repository,
        evaluation.files_to_write,
        message,
        branch_name,
        title,
        body,
    )

    result = TargetResult(
        repository=repository.full_name,
        strategy=rule.strategy,
        files=evaluation.file_results,
        commit_sha=applied_pr.commit_sha,
        pull_request_url=applied_pr.pull_request_url,
    )
    return result


def _evaluate_target(
    repository: TargetRepository,
    desired_files: list[DesiredFile],
    rule: SyncRule,
    provider: GitProvider,
) -> TargetEvaluation:
    file_results: list[FileResult] = []
    files_to_write: list[DesiredFile] = []
    for desired in desired_files:
        existing = provider.get_target_file(repository, desired.path)
        decision = strategy_handler.decide_file_outcome(desired, existing, rule.conflict_policy)
        file_results.append(FileResult(path=desired.path, outcome=decision.outcome))
        if decision.should_write:
            files_to_write.append(desired)

    evaluation = TargetEvaluation(file_results=file_results, files_to_write=files_to_write)
    return evaluation


def _sync_target(
    repository: TargetRepository,
    desired_files: list[DesiredFile],
    rule: SyncRule,
    dry_run: bool,
    provider: GitProvider,
) -> TargetResult:
    evaluation = _evaluate_target(repository, desired_files, rule, provider)

    if dry_run or not evaluation.files_to_write:
        result = TargetResult(
            repository=repository.full_name,
            strategy=rule.strategy,
            files=evaluation.file_results,
        )
        return result

    result = _deliver(repository, evaluation, rule, provider)
    return result


def _run_rule(rule: SyncRule, owner: str, dry_run: bool, provider: GitProvider) -> RuleReport:
    logger.debug(f"rule '{rule.name}': resolving targets and content")
    discovery = discovery_handler.discover_targets(rule.targets, owner, provider)
    desired_files = content_handler.resolve_content(rule.content, provider)
    logger.info(
        f"rule '{rule.name}': {len(discovery.included)} target(s), "
        f"{len(discovery.excluded)} excluded, {len(desired_files)} file(s) to sync"
    )

    target_results: list[TargetResult] = []
    for repository in discovery.included:
        try:
            result = _sync_target(repository, desired_files, rule, dry_run, provider)
        except ProviderError as error:
            result = TargetResult(
                repository=repository.full_name,
                strategy=rule.strategy,
                files=[],
                error=str(error),
            )

        target_results.append(result)
        _log_target_result(result, dry_run)

    rule_report = RuleReport(
        rule_name=rule.name,
        dry_run=dry_run,
        targets=target_results,
        excluded=discovery.excluded,
    )
    return rule_report


def run_sync(sync_config: SyncConfig, dry_run: bool, provider: GitProvider) -> SyncReport:
    if dry_run:
        logger.warning("dry-run mode: no changes will be written to any repository")

    rule_reports: list[RuleReport] = []
    for rule in sync_config.rules:
        rule_report = _run_rule(rule, sync_config.owner, dry_run, provider)
        rule_reports.append(rule_report)

    report = SyncReport(dry_run=dry_run, rules=rule_reports)
    return report
