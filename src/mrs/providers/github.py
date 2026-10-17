import base64

import httpx

from mrs.errors import (
    AuthorizationError,
    ProviderError,
    ResourceNotFoundError,
    WriteError,
)
from mrs.providers.base import (
    AppliedPullRequest,
    DesiredFile,
    ExistingFile,
    GitProvider,
    TargetRepository,
)

GITHUB_API_VERSION = "2022-11-28"
REPOS_PER_PAGE = 100
BLOB_FILE_MODE = "100644"


def _parse_next_link(link_header: str | None) -> str | None:
    if not link_header:
        return None

    for part in link_header.split(","):
        segments = part.split(";")
        if len(segments) < 2:
            continue
        url_segment = segments[0].strip().strip("<>")
        is_next = any(segment.strip() == 'rel="next"' for segment in segments[1:])
        if is_next:
            return url_segment
    return None


def _to_target_repository(raw: dict) -> TargetRepository:
    repository = TargetRepository(
        owner=raw["owner"]["login"],
        name=raw["name"],
        default_branch=raw["default_branch"],
        topics=raw.get("topics", []),
        archived=raw.get("archived", False),
        fork=raw.get("fork", False),
    )
    return repository


class GitHubProvider(GitProvider):
    def __init__(self, token: str, api_base_url: str, request_timeout_seconds: int):
        self._client = httpx.Client(
            base_url=api_base_url,
            timeout=request_timeout_seconds,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": GITHUB_API_VERSION,
            },
        )

    def close(self):
        self._client.close()

    #region HTTP plumbing

    def _request(
        self,
        method: str,
        path: str,
        json: dict | None = None,
        params: dict | None = None,
    ) -> httpx.Response:
        try:
            response = self._client.request(method, path, json=json, params=params)
        except httpx.RequestError as error:
            raise ProviderError(f"network error on {method} {path}: {error}") from error

        if response.status_code == 404:
            raise ResourceNotFoundError(f"{method} {path} -> 404 not found")

        if response.status_code in (401, 403):
            rate_limit_remaining = response.headers.get("X-RateLimit-Remaining")
            if rate_limit_remaining == "0":
                raise ProviderError(f"{method} {path} -> rate limited (primary rate limit exhausted)")
            raise AuthorizationError(f"{method} {path} -> {response.status_code}: {response.text[:200]}")

        if response.status_code >= 400:
            raise ProviderError(f"{method} {path} -> {response.status_code}: {response.text[:200]}")

        return response

    def _paginate(self, path: str) -> list[dict]:
        collected: list[dict] = []
        next_path = path
        next_params: dict | None = {"per_page": REPOS_PER_PAGE}
        while next_path is not None:
            response = self._request("GET", next_path, params=next_params)
            collected.extend(response.json())
            # Subsequent pages come as fully-qualified URLs in the Link header.
            next_path = _parse_next_link(response.headers.get("Link"))
            next_params = None
        return collected

    #endregion

    #region Reads

    def list_repositories(self, owner: str) -> list[TargetRepository]:
        try:
            raw_repositories = self._paginate(f"/orgs/{owner}/repos")
        except ResourceNotFoundError:
            # Not an org: fall back to every repo the token can see, filtered to this owner,
            # which includes the authenticated user's private repositories.
            all_accessible = self._paginate("/user/repos")
            raw_repositories = [
                raw for raw in all_accessible if raw["owner"]["login"].lower() == owner.lower()
            ]
        repositories = [_to_target_repository(raw) for raw in raw_repositories]
        return repositories

    def get_repository(self, full_name: str) -> TargetRepository:
        response = self._request("GET", f"/repos/{full_name}")
        repository = _to_target_repository(response.json())
        return repository

    def _get_contents(self, full_name: str, path: str, ref: str | None):
        params = {"ref": ref} if ref is not None else None
        response = self._request("GET", f"/repos/{full_name}/contents/{path}", params=params)
        payload = response.json()
        return payload

    def _read_blob_content(self, full_name: str, file_entry: dict) -> bytes:
        # The Contents API inlines base64 content only up to ~1 MiB; larger files come back
        # with an empty content field and must be fetched through the blobs API.
        encoded_content = file_entry.get("content", "")
        if encoded_content:
            content_bytes = base64.b64decode(encoded_content)
            return content_bytes

        blob_response = self._request("GET", f"/repos/{full_name}/git/blobs/{file_entry['sha']}")
        blob_bytes = base64.b64decode(blob_response.json()["content"])
        return blob_bytes

    def _resolve_ref(self, full_name: str, ref: str | None) -> str:
        if ref is not None:
            return ref
        repository = self.get_repository(full_name)
        return repository.default_branch

    def _list_tree_blob_paths(self, full_name: str, directory_path: str, ref: str | None) -> list[str]:
        branch = self._resolve_ref(full_name, ref)
        _, tree_sha = self._get_branch_head(full_name, branch)
        response = self._request(
            "GET",
            f"/repos/{full_name}/git/trees/{tree_sha}",
            params={"recursive": "1"},
        )
        prefix = directory_path.rstrip("/") + "/"
        file_paths = [
            entry["path"]
            for entry in response.json().get("tree", [])
            if entry["type"] == "blob" and entry["path"].startswith(prefix)
        ]
        return file_paths

    def list_source_files(self, full_name: str, path: str, ref: str | None) -> list[str]:
        payload = self._get_contents(full_name, path, ref)
        if isinstance(payload, dict):
            return [payload["path"]]
        # A list payload means `path` is a directory; the Contents listing is shallow, so
        # recurse through the git tree to collect every nested file.
        file_paths = self._list_tree_blob_paths(full_name, path, ref)
        return file_paths

    def read_source_file(self, full_name: str, path: str, ref: str | None) -> bytes:
        payload = self._get_contents(full_name, path, ref)
        content_bytes = self._read_blob_content(full_name, payload)
        return content_bytes

    def get_target_file(self, repository: TargetRepository, path: str) -> ExistingFile | None:
        try:
            payload = self._get_contents(repository.full_name, path, repository.default_branch)
        except ResourceNotFoundError:
            return None

        content_bytes = self._read_blob_content(repository.full_name, payload)
        existing = ExistingFile(path=path, content_bytes=content_bytes, blob_sha=payload["sha"])
        return existing

    #endregion

    #region Writes

    def _get_branch_head(self, full_name: str, branch: str) -> tuple[str, str]:
        ref_response = self._request("GET", f"/repos/{full_name}/git/ref/heads/{branch}")
        commit_sha = ref_response.json()["object"]["sha"]
        commit_response = self._request("GET", f"/repos/{full_name}/git/commits/{commit_sha}")
        tree_sha = commit_response.json()["tree"]["sha"]
        return commit_sha, tree_sha

    def _create_blob(self, full_name: str, content_bytes: bytes) -> str:
        payload = {
            "content": base64.b64encode(content_bytes).decode("ascii"),
            "encoding": "base64",
        }
        response = self._request("POST", f"/repos/{full_name}/git/blobs", json=payload)
        blob_sha = response.json()["sha"]
        return blob_sha

    def _build_commit(
        self,
        full_name: str,
        parent_commit_sha: str,
        base_tree_sha: str,
        files: list[DesiredFile],
        message: str,
    ) -> str:
        tree_entries = [
            {
                "path": desired.path,
                "mode": BLOB_FILE_MODE,
                "type": "blob",
                "sha": self._create_blob(full_name, desired.content_bytes),
            }
            for desired in files
        ]
        # base_tree carries forward every file we are not touching; omitting it would delete them.
        tree_payload = {"base_tree": base_tree_sha, "tree": tree_entries}
        tree_response = self._request("POST", f"/repos/{full_name}/git/trees", json=tree_payload)
        new_tree_sha = tree_response.json()["sha"]

        commit_payload = {"message": message, "tree": new_tree_sha, "parents": [parent_commit_sha]}
        commit_response = self._request("POST", f"/repos/{full_name}/git/commits", json=commit_payload)
        new_commit_sha = commit_response.json()["sha"]
        return new_commit_sha

    def _ensure_branch(self, full_name: str, branch: str, base_commit_sha: str):
        try:
            self._request("GET", f"/repos/{full_name}/git/ref/heads/{branch}")
        except ResourceNotFoundError:
            create_payload = {"ref": f"refs/heads/{branch}", "sha": base_commit_sha}
            self._request("POST", f"/repos/{full_name}/git/refs", json=create_payload)
            return

        # Reset a pre-existing sync branch to base so the sync commit is the only change on it.
        reset_payload = {"sha": base_commit_sha, "force": True}
        self._request("PATCH", f"/repos/{full_name}/git/refs/heads/{branch}", json=reset_payload)

    def _find_open_pull_request(self, full_name: str, head_branch: str, base_branch: str) -> str | None:
        owner = full_name.split("/")[0]
        params = {"head": f"{owner}:{head_branch}", "base": base_branch, "state": "open"}
        response = self._request("GET", f"/repos/{full_name}/pulls", params=params)
        open_pull_requests = response.json()
        if not open_pull_requests:
            return None
        pull_request_url = open_pull_requests[0]["html_url"]
        return pull_request_url

    def _open_pull_request(
        self,
        full_name: str,
        head_branch: str,
        base_branch: str,
        title: str,
        body: str,
    ) -> str:
        payload = {"title": title, "head": head_branch, "base": base_branch, "body": body}
        try:
            response = self._request("POST", f"/repos/{full_name}/pulls", json=payload)
        except ProviderError as error:
            # A 422 usually means a PR for this head->base already exists; reuse it.
            existing_url = self._find_open_pull_request(full_name, head_branch, base_branch)
            if existing_url is not None:
                return existing_url
            raise WriteError(f"failed to open pull request on {full_name}: {error}") from error

        pull_request_url = response.json()["html_url"]
        return pull_request_url

    def apply_push(self, repository: TargetRepository, files: list[DesiredFile], message: str) -> str:
        branch = repository.default_branch
        parent_commit_sha, base_tree_sha = self._get_branch_head(repository.full_name, branch)
        new_commit_sha = self._build_commit(
            repository.full_name, parent_commit_sha, base_tree_sha, files, message
        )
        try:
            self._request(
                "PATCH",
                f"/repos/{repository.full_name}/git/refs/heads/{branch}",
                json={"sha": new_commit_sha},
            )
        except ProviderError as error:
            raise WriteError(
                f"could not push to {branch} on {repository.full_name}; "
                f"the branch may be protected: {error}"
            ) from error
        return new_commit_sha

    def apply_pull_request(
        self,
        repository: TargetRepository,
        files: list[DesiredFile],
        message: str,
        branch_name: str,
        title: str,
        body: str,
    ) -> AppliedPullRequest:
        base_branch = repository.default_branch
        base_commit_sha, base_tree_sha = self._get_branch_head(repository.full_name, base_branch)
        self._ensure_branch(repository.full_name, branch_name, base_commit_sha)
        new_commit_sha = self._build_commit(
            repository.full_name, base_commit_sha, base_tree_sha, files, message
        )
        self._request(
            "PATCH",
            f"/repos/{repository.full_name}/git/refs/heads/{branch_name}",
            json={"sha": new_commit_sha, "force": True},
        )
        pull_request_url = self._open_pull_request(
            repository.full_name, branch_name, base_branch, title, body
        )
        applied = AppliedPullRequest(commit_sha=new_commit_sha, pull_request_url=pull_request_url)
        return applied

    #endregion
