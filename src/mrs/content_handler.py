from pathlib import Path

from mrs.errors import ContentResolutionError
from mrs.models.sync_spec import ContentSpec
from mrs.providers.base import DesiredFile, GitProvider


def _destination_for(dest_path: str, source_root: str, source_file_path: str) -> str:
    """
    Re-root a source file onto the destination path, preserving its sub-path below source_root:

    ```
    dest_path        = '.github/workflows'
    source_root      = 'ci-templates'
    source_file_path = 'ci-templates/lint.yaml'
    ```

    yields `.github/workflows/lint.yaml`.
    
    When source_root is a single file
    (source_file_path == source_root), it maps directly onto dest_path.
    """

    # Single files map directly to the destination path
    if source_file_path == source_root:
        return dest_path

    # Folders might have nesting so we need to preserve the relative paths inside them
    relative_path = source_file_path[len(source_root):].lstrip("/")
    destination = f"{dest_path.rstrip('/')}/{relative_path}"
    return destination


def _resolve_remote_spec(spec: ContentSpec, source_repo: str, provider: GitProvider) -> list[DesiredFile]:
    source_file_paths = provider.list_source_files(source_repo, spec.path, spec.source_ref)
    if not source_file_paths:
        raise ContentResolutionError(f"no files found at {source_repo}:{spec.path}")

    desired_files: list[DesiredFile] = []
    for source_file_path in source_file_paths:
        content_bytes = provider.read_source_file(source_repo, source_file_path, spec.source_ref)
        destination = _destination_for(spec.dest_path, spec.path, source_file_path)
        desired_files.append(DesiredFile(path=destination, content_bytes=content_bytes))

    return desired_files


def _resolve_local_spec(spec: ContentSpec) -> list[DesiredFile]:
    local_path = Path(spec.path)
    if not local_path.exists():
        raise ContentResolutionError(f"local path does not exist: {local_path}")

    if local_path.is_file():
        desired = DesiredFile(path=spec.dest_path, content_bytes=local_path.read_bytes())
        return [desired]

    desired_files: list[DesiredFile] = []
    for child in sorted(local_path.rglob("*")):
        if not child.is_file():
            continue

        relative = child.relative_to(local_path).as_posix()
        destination = f"{spec.dest_path.rstrip('/')}/{relative}"
        desired_files.append(DesiredFile(path=destination, content_bytes=child.read_bytes()))

    if not desired_files:
        raise ContentResolutionError(f"local directory has no files: {local_path}")

    return desired_files


def resolve_content(content_specs: list[ContentSpec], provider: GitProvider) -> list[DesiredFile]:
    # Keys are destination paths so a later spec overriding the same target wins deterministically.
    content_by_path: dict[str, DesiredFile] = {}
    for spec in content_specs:
        if spec.source_repo is None:
            resolved = _resolve_local_spec(spec)
        else:
            resolved = _resolve_remote_spec(spec, spec.source_repo, provider)

        for desired in resolved:
            content_by_path[desired.path] = desired

    desired_files = list(content_by_path.values())
    return desired_files
