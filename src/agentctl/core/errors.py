"""Define Curator-specific exceptions for explicit failure boundaries."""


class CuratorError(Exception):
    """Represent the base class for explicit Curator failures."""


class CuratorPathError(CuratorError):
    """Represent an invalid Curator filesystem path boundary."""


class CuratorStateError(CuratorError):
    """Represent a failure while reading or writing Curator state."""


AgentctlError = CuratorError
AgentctlPathError = CuratorPathError
AgentctlStateError = CuratorStateError
