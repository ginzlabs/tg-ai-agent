"""Define the shared values."""

from __future__ import annotations

from dataclasses import dataclass, field
import operator

from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages
from typing_extensions import Annotated, Dict


@dataclass(kw_only=True)
class State:
    """Main graph state."""

    """The messages in the conversation."""
    messages: Annotated[list[AnyMessage], add_messages]
    
    """The current loop step."""
    loop_step: Annotated[int, operator.add] = field(default=0)

    """The pending approval for tool calls."""
    tools_call_approvals: Dict[str, bool] = field(default_factory=dict)



__all__ = [
    "State",
]