"""Errors that distinguish connection checks from uncertain physical actions."""
class HostTrustError(RuntimeError):
    pass


class ActionUncertain(RuntimeError):
    """An action may have executed; do not replay it or continue the run."""


class ActionRejected(RuntimeError):
    """The board explicitly rejected the requested action."""


class AuthenticationError(RuntimeError):
    """Credentials are missing or were rejected; not a test assertion failure."""


class ResourceError(RuntimeError):
    """A local communication resource is unavailable."""


class ResourceBusy(ResourceError):
    """A host communication resource is reserved by another owner."""


class ProtocolError(RuntimeError):
    """Transport delivered no trustworthy command completion evidence."""


class ActionNotDispatched(RuntimeError):
    """Preflight failed before the physical-action request was sent."""
