"""
OpenRouter integration for LangChain.

This module provides a wrapper around ChatOpenAI that can be used with either
OpenRouter or OpenAI directly.

Example usage:

llm = ChatOpenRouter(
    # model_name="openai/gpt-4o-mini",
    model_name="google/gemini-2.0-flash-001",
    use_openrouter=True,
)

"""

import os
from typing import Optional
from langchain_openai import ChatOpenAI
from langchain_core.utils.utils import secret_from_env
from pydantic import Field, SecretStr


class ChatOpenRouter(ChatOpenAI):
    """
    A wrapper around ChatOpenAI that can be used with either OpenRouter or OpenAI directly.
    
    This class allows you to choose between using OpenRouter's API (which provides access to
    various models including those from OpenAI) or using OpenAI's API directly.
    """
    
    openai_api_key: Optional[SecretStr] = Field(
        alias="api_key",
        default_factory=secret_from_env("OPENROUTER_API_KEY", default=None),
    )
    
    @property
    def lc_secrets(self) -> dict[str, str]:
        """Return the secrets mapping for LangChain."""
        return {"openai_api_key": "OPENROUTER_API_KEY"}

    def __init__(self,
                 openai_api_key: Optional[str] = None,
                 openrouter_api_key: Optional[str] = None,
                 use_openrouter: bool = True,
                 **kwargs):
        """
        Initialize the chat model with either OpenRouter or OpenAI.
        
        Args:
            openai_api_key: OpenAI API key (if use_openrouter=False)
            openrouter_api_key: OpenRouter API key (if use_openrouter=True)
            use_openrouter: Whether to use OpenRouter (True) or OpenAI (False)
            **kwargs: Additional arguments to pass to the parent class
        """
        if use_openrouter:
            # Use OpenRouter
            api_key = openrouter_api_key or os.environ.get("OPENROUTER_API_KEY")
            base_url = "https://openrouter.ai/api/v1"
        else:
            # Use OpenAI directly
            api_key = openai_api_key or os.environ.get("OPENAI_API_KEY")
            base_url = None  # Use the default OpenAI base URL
        
        if not api_key:
            service_name = "OpenRouter" if use_openrouter else "OpenAI"
            raise ValueError(f"No API key provided for {service_name}")
            
        super().__init__(
            base_url=base_url,
            openai_api_key=api_key,
            **kwargs
        ) 