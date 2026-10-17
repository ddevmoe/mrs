from dataclasses import dataclass

from mrs.errors import ConflictAbortError
from mrs.models.report import Outcome
from mrs.models.sync_spec import ConflictPolicy
from mrs.providers.base import DesiredFile, ExistingFile


@dataclass(frozen=True, slots=True)
class FileDecision:
    outcome: Outcome
    should_write: bool


def decide_file_outcome(
    desired: DesiredFile,
    existing: ExistingFile | None,
    conflict_policy: ConflictPolicy,
) -> FileDecision:
    if existing is None:
        return FileDecision(outcome=Outcome.CREATED, should_write=True)

    if existing.content_bytes == desired.content_bytes:
        return FileDecision(outcome=Outcome.IN_SYNC, should_write=False)

    # The target file exists and differs from what we want to write: a content conflict.
    if conflict_policy is ConflictPolicy.OVERRIDE:
        return FileDecision(outcome=Outcome.OVERRODE_CONFLICT, should_write=True)

    if conflict_policy is ConflictPolicy.SKIP:
        return FileDecision(outcome=Outcome.SKIPPED_CONFLICT, should_write=False)

    raise ConflictAbortError(
        f"conflict on '{desired.path}' and conflict policy is 'abort'; stopping the run"
    )
