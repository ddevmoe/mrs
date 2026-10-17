class MrsErrorBase(Exception):
    """Base for all errors raised by mrs."""


class ConfigurationError(MrsErrorBase):
    """Invalid or missing configuration (token, config file, selectors)."""


class DiscoveryError(MrsErrorBase):
    """A target could not be discovered or resolved."""


class ContentResolutionError(MrsErrorBase):
    """Source content (local or remote) could not be resolved."""


class ConflictAbortError(MrsErrorBase):
    """A file conflict was hit while the conflict policy is `abort`."""


class ProviderError(MrsErrorBase):
    """Base for errors returned by a git provider's API."""


class AuthorizationError(ProviderError):
    """The token is missing a scope/permission for the requested operation."""


class ResourceNotFoundError(ProviderError):
    """The requested repository, ref, or path does not exist."""


class WriteError(ProviderError):
    """A write (push / ref update / pull request) was rejected by the provider."""
