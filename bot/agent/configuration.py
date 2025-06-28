"""Define the configurable parameters for the agent."""

import os
import sys
from dataclasses import dataclass, field, fields
from typing import Any, Optional

from langchain_core.runnables import RunnableConfig
from typing_extensions import Annotated

from agent import prompts

# Add the parent directories to the path to import the utils package
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from shared_utils.langchain_openrouter import ChatOpenRouter


@dataclass(kw_only=True)
class Configuration:
    """Configuration for the agent."""

    user_id: str = "default"

    thread_id: str = "default-thread"

    role: str = "user"

    model: Annotated[str, {"__template_metadata__": {"kind": "llm"}}] = field(
        default="google/gemini-2.0-flash-001",  # Your default OpenRouter model
        metadata={"description": "Model name in provider/model-name format."}
    )

    system_prompt: str = prompts.SYSTEM_PROMPT

    use_openrouter: bool = True  # Add your flag

    openrouter_api_key: Optional[str] = None  # Add API key option

    openai_api_key: Optional[str] = None  # Add OpenAI key option

    max_search_results: int = field(
        default=10,
        metadata={
            "description": "The maximum number of search results to return for each search query."
        },
    )

    max_loops: int = field(
        default=6,
        metadata={
            "description": "The maximum number of interaction loops allowed before the agent terminates."
        },
    )



    @classmethod
    def from_runnable_config(cls, config: Optional[RunnableConfig] = None) -> "Configuration":
        """Create a Configuration instance from a RunnableConfig object."""
        configurable = config["configurable"] if config and "configurable" in config else {}
        values = {
            f.name: os.environ.get(f.name.upper(), configurable.get(f.name))
            for f in fields(cls)
            if f.init
        }
        return cls(**{k: v for k, v in values.items() if v})

    def get_llm(self) -> ChatOpenRouter:
        """Return the configured LLM instance."""
        return ChatOpenRouter(
            model_name=self.model,
            use_openrouter=self.use_openrouter,
            openrouter_api_key=self.openrouter_api_key,
            openai_api_key=self.openai_api_key,
        )