import subprocess
from functools import lru_cache
from typing import Annotated

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from mrs.errors import ConfigurationError


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MRS_", frozen=True)

    # Accepts MRS_GITHUB_TOKEN, or the standard GITHUB_TOKEN / GH_TOKEN.
    github_token: Annotated[
        str | None,
        Field(validation_alias=AliasChoices("MRS_GITHUB_TOKEN", "GITHUB_TOKEN", "GH_TOKEN")),
    ] = None
    github_api_base_url: str = "https://api.github.com"
    request_timeout_seconds: Annotated[int, Field(ge=1)] = 30


def _resolve_github_token_from_cli() -> str:
    try:
        completed = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            check=True,
        )

    except FileNotFoundError as error:
        raise ConfigurationError(
            "no GitHub token configured (set MRS_GITHUB_TOKEN/GITHUB_TOKEN/GH_TOKEN) "
            "and the gh CLI is not installed"
        ) from error

    except subprocess.CalledProcessError as error:
        raise ConfigurationError(
            "no GitHub token configured and `gh auth token` failed; run `gh auth login`"
        ) from error

    token = completed.stdout.strip()
    if not token:
        raise ConfigurationError("`gh auth token` returned an empty token")

    return token


@lru_cache(maxsize=1)
def get_config() -> Config:
    config = Config()
    if config.github_token is not None:
        return config

    token = _resolve_github_token_from_cli()
    resolved_config = config.model_copy(update={"github_token": token})
    return resolved_config
