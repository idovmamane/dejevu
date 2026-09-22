"""One look, one call, one action. The model names an observed element; code owns execution."""

from .agent import Agent, Loop
from .browser import StalePage, Tab
from .cdp import Chrome
from .policy import LLMPolicy, TypeSafePolicy
from .types import Decision, PolicyError

__version__ = "0.1.0"
__all__ = ["Agent", "Loop", "Tab", "Chrome", "StalePage", "LLMPolicy", "TypeSafePolicy", "Decision", "PolicyError", "__version__"]
