import re
from dataclasses import dataclass

from mrs.models.report import ExcludedRepository
from mrs.models.sync_spec import TargetSelector
from mrs.providers.base import GitProvider, TargetRepository


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    included: list[TargetRepository]
    excluded: list[ExcludedRepository]


def _exclusion_reason(repository: TargetRepository, selector: TargetSelector) -> str | None:
    if repository.name in selector.exclude_repos or repository.full_name in selector.exclude_repos:
        return "listed in exclude_repos"

    matching_topics = [topic for topic in selector.exclude_topics if topic in repository.topics]
    if matching_topics:
        return f"has excluded topic(s): {', '.join(matching_topics)}"

    if selector.exclude_name_regex and re.search(selector.exclude_name_regex, repository.name):
        return f"name matches exclude_name_regex: {selector.exclude_name_regex}"

    return None


def _satisfies_include_filters(repository: TargetRepository, selector: TargetSelector) -> bool:
    if repository.archived and not selector.include_archived:
        return False

    if repository.fork and not selector.include_forks:
        return False

    if selector.name_regex and not re.search(selector.name_regex, repository.name):
        return False

    if selector.topics:
        has_all_topics = all(topic in repository.topics for topic in selector.topics)
        if not has_all_topics:
            return False

    return True


def _resolve_explicit_repositories(
    repos: list[str],
    owner: str,
    provider: GitProvider,
) -> list[TargetRepository]:
    repositories = []
    for entry in repos:
        full_name = entry if "/" in entry else f"{owner}/{entry}"
        repository = provider.get_repository(full_name)
        repositories.append(repository)
    return repositories


def discover_targets(selector: TargetSelector, owner: str, provider: GitProvider) -> DiscoveryResult:
    # Explicitly named repos are taken as-is; the name/topic/exclude filters only apply when
    # we discover targets by listing the owner's repositories.
    if selector.repos:
        included = _resolve_explicit_repositories(selector.repos, owner, provider)
        result = DiscoveryResult(included=included, excluded=[])
        return result

    included = []
    excluded: list[ExcludedRepository] = []
    candidate_repositories = provider.list_repositories(owner)
    for repository in candidate_repositories:
        if not _satisfies_include_filters(repository, selector):
            continue

        exclusion_reason = _exclusion_reason(repository, selector)
        if exclusion_reason:
            excluded.append(ExcludedRepository(repository=repository.full_name, reason=exclusion_reason))
            continue

        included.append(repository)

    result = DiscoveryResult(included=included, excluded=excluded)
    return result
