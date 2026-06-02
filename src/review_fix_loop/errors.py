class ReviewFixLoopError(Exception):
    """Base error for CLI-visible workflow failures."""


class ConfigError(ReviewFixLoopError):
    """Configuration is malformed or internally inconsistent."""


class GitError(ReviewFixLoopError):
    """Git command failed or produced invalid output."""


class WorkflowError(ReviewFixLoopError):
    """The requested review loop operation violates the workflow contract."""

