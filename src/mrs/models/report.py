from enum import StrEnum

from pydantic import BaseModel

from mrs.models.sync_spec import Strategy


class Outcome(StrEnum):
    CREATED = "created"
    IN_SYNC = "in_sync"
    OVERRODE_CONFLICT = "overrode_conflict"
    SKIPPED_CONFLICT = "skipped_conflict"
    ERROR = "error"


class FileResult(BaseModel):
    path: str
    outcome: Outcome
    detail: str | None = None


class ExcludedRepository(BaseModel):
    repository: str
    reason: str


class TargetResult(BaseModel):
    repository: str
    strategy: Strategy
    files: list[FileResult]
    commit_sha: str | None = None
    pull_request_url: str | None = None
    error: str | None = None


class RuleReport(BaseModel):
    rule_name: str
    dry_run: bool
    targets: list[TargetResult]
    excluded: list[ExcludedRepository]


class SyncReport(BaseModel):
    dry_run: bool
    rules: list[RuleReport]
