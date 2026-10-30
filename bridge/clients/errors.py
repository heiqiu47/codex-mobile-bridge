class BridgeUnavailable(ValueError):
    """The desktop adapter is disconnected or cannot confirm an operation."""


class TaskStateUnavailable(ValueError):
    """No task evidence; distinct from known busy tasks or ambiguous processes."""


class ResumePreflightBlocked(BridgeUnavailable):
    """A native operation was rejected before dispatch or process startup."""
