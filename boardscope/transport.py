"""Errors that distinguish connection checks from uncertain physical actions."""
class HostTrustError(RuntimeError):
    pass


class ActionUncertain(RuntimeError):
    """An action may have executed; do not replay it or continue the run."""


class ActionRejected(RuntimeError):
    """The board explicitly rejected the requested action."""
