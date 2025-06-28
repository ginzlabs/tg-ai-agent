"""
Text summarization service using LangChain and OpenRouter/OpenAI.

This module provides a service for summarizing text using LLMs.
"""

import os
import sys
import json
import argparse
import time
import asyncio
from typing import Dict, Optional

from config import STT_SUMMARY_TEXTS

# Add the parent directories to the path to import the utils package
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from shared_utils.langchain_openrouter import ChatOpenRouter

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate

from schemas import SummaryOutput


class SummarizationService:
    """Service for text summarization using LLMs via OpenRouter/OpenAI."""
    
    def __init__(
        self,
        model_name: str = "openai/gpt-4o-mini",
        use_openrouter: bool = True,
        temperature: float = 0.2,
        max_tokens: int = 10000,
        timeout: Optional[int] = None,
    ):
        """
        Initialize the summarization service.
        
        Args:
            model_name: The name of the model to use for summarization
            use_openrouter: Whether to use OpenRouter (True) or OpenAI (False)
            temperature: The temperature for generation (0.0-1.0)
            max_tokens: Maximum number of tokens to generate
            timeout: Maximum time in seconds to wait for a response, None for no timeout
        """
        self.llm = ChatOpenRouter(
            model_name=model_name,
            use_openrouter=use_openrouter,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        self.timeout = timeout
        
        # Set up output parser for structured responses
        self.parser = JsonOutputParser(pydantic_object=SummaryOutput)
        
    async def _run_summarization_async(self, chain, inputs):
        """Execute the summarization chain asynchronously."""
        return await chain.ainvoke(inputs)
        
    async def summarize(
        self,
        text: str,
        system_prompt: Optional[str] = None,
    ) -> Dict:
        """
        Summarize the provided text asynchronously.
        
        Args:
            text: The text to summarize
            system_prompt: Optional custom system prompt to guide the summarization
            
        Returns:
            Dict containing the summary, key points, sentiment, and timing information.
            If timeout occurs, returns an empty dict with default values.
        """
        
        if not system_prompt:
            system_prompt = STT_SUMMARY_TEXTS["system_prompt"]
            
        # Format complex words into a readable string
        complex_words = ", ".join(STT_SUMMARY_TEXTS["complex_words"])
        system_prompt = system_prompt.format(complex_words=complex_words)
        
        # Create the prompt template
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "Text to summarize: {text}\n\n{format_instructions}")
        ])
        
        # Set up the chain
        chain = prompt | self.llm | self.parser
        
        inputs = {
            "text": text,
            "format_instructions": self.parser.get_format_instructions()
        }
        
        # Run with timeout if specified
        start_time = time.time()
        if self.timeout:
            try:
                # Use asyncio.wait_for for async timeout
                result = await asyncio.wait_for(
                    self._run_summarization_async(chain, inputs),
                    timeout=self.timeout
                )
                # Add timing information
                elapsed_time = time.time() - start_time
                result["timing"] = {
                    "total_seconds": round(elapsed_time, 2),
                    "timed_out": False
                }
                return result
            except asyncio.TimeoutError:
                # Return empty result if timeout occurs
                elapsed_time = time.time() - start_time
                return {
                    "summary": "",
                    "key_points": [],
                    "sentiment": "neutral",
                    "timing": {
                        "total_seconds": round(elapsed_time, 2),
                        "timed_out": True
                    }
                }
        else:
            # Run without timeout
            result = await chain.ainvoke(inputs)
            # Add timing information
            elapsed_time = time.time() - start_time
            result["timing"] = {
                "total_seconds": round(elapsed_time, 2),
                "timed_out": False
            }
            return result


async def async_main():
    import os
    from dotenv import load_dotenv
    # Load .env file from 2 dirs up
    dot_env_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
    # print(f"Loading .env file from: {dot_env_path}")
    load_dotenv(dotenv_path=dot_env_path)

    """Run the summarization service from the command line asynchronously."""
    parser = argparse.ArgumentParser(description="Summarize text using LLMs")
    parser.add_argument("--file", "-f", help="Path to file containing text to summarize")
    parser.add_argument("--text", "-t", help="Text to summarize")
    parser.add_argument("--model", "-m", default="openai/gpt-4o-mini",
                        help="Model to use for summarization")
    parser.add_argument("--direct", "-d", action="store_true",
                        help="Use OpenAI directly instead of OpenRouter")
    parser.add_argument("--system-prompt", "-s", help="Custom system prompt")
    parser.add_argument("--timeout", type=int, default=None,
                        help="Maximum time in seconds to wait for a response")
    
    args = parser.parse_args()
    
    # Get text from file or command line
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            text = f.read()
    elif args.text:
        text = args.text
    else:
        print("Error: Must provide either --file or --text")
        parser.print_help()
        return
    
    # Create the service
    # Time the creation of the service
    start_time = time.time()
    service = SummarizationService(
        model_name=args.model,
        use_openrouter=not args.direct,
        timeout=args.timeout,
    )
    elapsed_time = time.time() - start_time
    print(f"Time to create service: {elapsed_time} seconds")
    # Summarize the text asynchronously
    print(f"Running summarization with timeout: {args.timeout}")
    result = await service.summarize(text, args.system_prompt)
    
    # Print the result
    print(json.dumps(result, indent=2))


def main():
    """Run the async main function."""
    asyncio.run(async_main())


if __name__ == "__main__":
    main() 