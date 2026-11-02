"""Shared failure with redacted reason codes and optional verifier blockers."""
import re


class WorkflowError(Exception):
    """Never include upstream exception text, message contents or codes."""

    def __init__(self, reason: str, *, blockers=()):
        safe = re.fullmatch(r'[a-z_]{1,96}', reason) if isinstance(reason, str) else None
        super().__init__(reason if safe else 'workflow_failed')
        self.blockers = sorted({value for value in blockers if isinstance(value, str)
                                and re.fullmatch(r'[a-z_]{1,96}', value)})
