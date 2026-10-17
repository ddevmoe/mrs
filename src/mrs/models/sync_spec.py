from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Strategy(StrEnum):
    PULL_REQUEST = "pull_request"
    PUSH = "push"


class ConflictPolicy(StrEnum):
    OVERRIDE = "override"
    SKIP = "skip"
    ABORT = "abort"


class TargetSelector(BaseModel):
    model_config = ConfigDict(use_attribute_docstrings=True)

    repos: list[str] = Field(default_factory=list)
    """Explicit repository names. When set, they are taken as-is and bypass all filters; when
    empty, all of the owner's repositories are listed and then filtered."""

    name_regex: str | None = None
    """Include repositories whose name matches this regular expression (use an anchored
    pattern like "^mrs-" for a prefix match)."""

    topics: list[str] = Field(default_factory=list)
    """Include only repositories that carry ALL of these topics."""

    include_archived: bool = False
    """Include archived repositories (excluded by default)."""

    include_forks: bool = False
    """Include forks (excluded by default)."""

    exclude_repos: list[str] = Field(default_factory=list)
    """Exclude these repository names. Exclusions always win over includes."""

    exclude_topics: list[str] = Field(default_factory=list)
    """Exclude any repository carrying ANY of these topics."""

    exclude_name_regex: str | None = None
    """Exclude repositories whose name matches this regular expression."""


class ContentSpec(BaseModel):
    model_config = ConfigDict(use_attribute_docstrings=True)

    path: str
    """Content to sync: a path inside source_repo when it is set, otherwise a local filesystem path."""

    dest_path: str
    """Destination path inside each target repository."""

    source_repo: str | None = None
    """Source repository in "owner/name" form. When unset, path is read from the local filesystem."""

    source_ref: str | None = None
    """Branch, tag, or commit SHA to read from source_repo; defaults to its default branch."""


class SyncRule(BaseModel):
    model_config = ConfigDict(use_attribute_docstrings=True)

    name: str
    """Unique rule name, used in logs and in the default branch/commit/PR text."""

    content: list[ContentSpec]
    """Content to sync into every matched target."""

    targets: TargetSelector
    """How to select the repositories this rule applies to."""

    strategy: Strategy = Strategy.PULL_REQUEST
    """How changes are delivered: open a pull request or push to the default branch."""

    conflict_policy: ConflictPolicy = ConflictPolicy.SKIP
    """What to do when a target file already exists and differs from the desired content."""

    commit_message: str | None = None
    """Override the default commit message."""

    branch_name: str | None = None
    """Override the default sync branch name (pull_request strategy only)."""

    pull_request_title: str | None = None
    """Override the default pull request title (pull_request strategy only)."""

    pull_request_body: str | None = None
    """Override the default pull request body (pull_request strategy only)."""


class SyncConfig(BaseModel):
    model_config = ConfigDict(use_attribute_docstrings=True)

    owner: str
    """GitHub organization or user that owns the target repositories."""

    rules: list[SyncRule]
    """Sync rules to execute in order."""
