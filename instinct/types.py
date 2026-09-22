"""Shared contracts: what a policy returns, and how a bad answer is rejected."""

from dataclasses import asdict, dataclass, field


class PolicyError(ValueError):
    """The model gave no usable answer. Nothing is executed."""


OPS = ("CLICK", "TYPE", "SELECT", "PRESS", "SCROLL_DOWN", "SCROLL_UP", "WAIT", "DONE", "BLOCKED")
KEYS = ("Enter", "Escape")
# Spellings models reach for; all map onto the nine operations above.
ALIASES = {
    "TYPE_TEXT": "TYPE",
    "INPUT": "TYPE",
    "FILL": "TYPE",
    "ENTER_TEXT": "TYPE",
    "TYPE_INTO": "TYPE",
    "SELECT_OPTION": "SELECT",
    "SCROLL": "SCROLL_DOWN",
    "KEY": "PRESS",
    "PRESS_KEY": "PRESS",
    "FINISH": "DONE",
    "FINISHED": "DONE",
    "COMPLETE": "DONE",
    "SUCCESS": "DONE",
    "STOP": "BLOCKED",
    "FAIL": "BLOCKED",
    "GIVE_UP": "BLOCKED",
}


@dataclass
class Decision:
    op: str
    target: int | None = None
    text: str | None = None
    option: int | None = None
    key: str | None = None
    # Alternatives for the chosen target, from token logprobs when the endpoint returns them. Empty otherwise.
    probabilities: dict = field(default_factory=dict)
    confidence: float | None = None
    latency_ms: int = 0
    usage: dict = field(default_factory=dict)
    cost: float | None = None
    model: str = ""
    provider: str | None = None
    raw: str = ""
    request_chars: int = 0

    def as_dict(self):
        return asdict(self)
