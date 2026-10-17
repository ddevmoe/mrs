from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ConfigDict, computed_field


@dataclass(frozen=True, slots=True)
class DesiredFile:
    path: str
    """Destination path inside the target repository"""

    content_bytes: bytes


class TargetRepository(BaseModel):
    model_config = ConfigDict(use_attribute_docstrings=True)

    owner: str
    """Owner login (organization or user)"""

    name: str
    """Repository name, without the owner prefix"""

    default_branch: str
    topics: list[str]
    archived: bool
    fork: bool

    @computed_field
    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"


class ExistingFile(BaseModel):
    path: str
    content_bytes: bytes
    blob_sha: str


@dataclass(frozen=True, slots=True)
class AppliedPullRequest:
    commit_sha: str
    pull_request_url: str


class GitProvider(Protocol):
    """
    The interface between mrs and a git-hosting provider.
    Implementations should mask provider-specific exceptions and use MRS ones.
    """

    def list_repositories(self, owner: str) -> list[TargetRepository]:
        """Return every repository under `owner` the credential can see, for discovery to
        filter client-side. Must paginate fully; order is not significant."""
        ...

    def get_repository(self, full_name: str) -> TargetRepository:
        """Fetch a single repository by "owner/name". Raises ResourceNotFoundError when it
        does not exist or the credential cannot see it."""
        ...

    def list_source_files(self, full_name: str, path: str, ref: str | None) -> list[str]:
        """List the file paths under `path` in a source repo. A file `path` yields a
        single-element list; a directory is walked recursively to every nested file.
        `ref` is a branch/tag/SHA, defaulting to the repo's default branch when None."""
        ...

    def read_source_file(self, full_name: str, path: str, ref: str | None) -> bytes:
        """Read the raw bytes of one source file (the content to propagate). `ref` defaults
        to the repo's default branch when None. Raises ResourceNotFoundError if absent —
        the source is expected to exist."""
        ...

    def get_target_file(self, repository: TargetRepository, path: str) -> ExistingFile | None:
        """Read `path` from the target's default branch so a conflict can be detected.
        Returns None when the file does not exist there (the normal "create" case) rather
        than raising."""
        ...

    def apply_push(
        self,
        repository: TargetRepository,
        files: list[DesiredFile],
        message: str,
    ) -> str:
        """Commit `files` directly onto the target's default branch in one commit, built on
        the branch's current tree so untouched files are preserved. Returns the new commit
        SHA. Raises WriteError when the branch rejects the push (e.g. branch protection)."""
        ...

    def apply_pull_request(
        self,
        repository: TargetRepository,
        files: list[DesiredFile],
        message: str,
        branch_name: str,
        title: str,
        body: str,
    ) -> AppliedPullRequest:
        """Commit `files` onto `branch_name` (created from, and reset to, the default branch)
        and open a pull request back into the default branch. An existing open PR for the
        same branch is reused rather than duplicated."""
        ...
