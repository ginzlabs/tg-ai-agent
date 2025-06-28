"""Graphs that extract memories on a schedule."""

from datetime import datetime
from typing import Literal

from langchain_core.runnables import RunnableConfig
from langchain_core.messages import AIMessage, trim_messages, RemoveMessage
from langgraph.graph import END, StateGraph
from langgraph.store.base import BaseStore
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt

from agent.configuration import Configuration
from agent.tools import TOOLS, TOOLS_w_APPROVAL
from agent.state import State
from utils.logger import logger


async def call_model(state: State, config: RunnableConfig, *, store: BaseStore) -> dict:
    """Extract the user's state from the conversation and update the memory."""
    configurable = Configuration.from_runnable_config(config)

    # Retrieve the most recent memories for context
    memories = await store.asearch(
        ("memories", configurable.user_id),
        query=str([m.content for m in state.messages[-3:]]),
        # limit=10,
    )

    # Format memories for inclusion in the prompt
    formatted = "\n".join(f"[{mem.key}]: {mem.value} (similarity: {mem.score})" for mem in memories)
    if formatted:
        formatted = f"""
<memories>
{formatted}
</memories>"""

    # Prepare the system prompt with user memories and current time
    # This helps the model understand the context and temporal relevance
    sys_prompt = configurable.system_prompt.format(
        user_info=formatted,
        time=datetime.now().isoformat(),
        role=configurable.role
    )

    # Invoke the language model with the prepared prompt and tools
    # "bind_tools" gives the LLM the JSON schema for all tools in the list so it knows how
    # to use them.
    # Initialize the LLM with the config (ChatOpenRouter)
    llm = configurable.get_llm()
    model = llm.bind_tools(TOOLS)
    response  = await model.ainvoke(
        [{"role": "system", "content": sys_prompt}, *state.messages],
    )
    return {"messages": [response]}


def tools_approval(state: State, config: RunnableConfig) -> dict:
    """Handle human-in-the-loop approval for tools that require it.
    
    Args:
        state (State): The current state.
        config (RunnableConfig): The runtime configuration.
        
    Returns:
        dict: Updates state with the tool call approvals.
    """
    last_message = state.messages[-1]
    # configurable = Configuration.from_runnable_config(config)

    # Check if the last message contains a tool call that requires approval
    if any(tool_call["name"] in TOOLS_w_APPROVAL for tool_call in last_message.tool_calls):
        is_approved = interrupt({"action": f"Do you approve calling *{last_message.tool_calls[0]['name'].replace('_', ' ')}* (yes/no)?"})
        if is_approved["user_answered"][:1].lower() in ("y", "a"):
            return {"tools_call_approvals": {last_message.tool_calls[0]["name"]: True}}
        else:
            return {"tools_call_approvals": {last_message.tool_calls[0]["name"]: False}}


def route_model_output(state: State, config: RunnableConfig) -> Literal["trimmer", "tools_approval", "too_many_tools"]:
    """Determine the next node based on the model's output.

    This function checks if the model's last message contains tool calls.

    Args:
        state (State): The current state of the conversation.

    Returns:
        str: The name of the next node to call ("trimmer", "tools_approval", "too_many_tools").
    """
    last_message = state.messages[-1]
    configurable = Configuration.from_runnable_config(config)

    # logger.info(f"Last message: {last_message}")

    # Log number of messages in state.messages
    logger.info(f"Number of messages in state.messages: {len(state.messages)}")

    if not isinstance(last_message, AIMessage):
        return "trimmer"
        # raise ValueError(
        #     f"Expected AIMessage in output edges, but got {type(last_message).__name__}"
        # )
    
    # Log number of tool calls in the last message
    logger.info(f"Number of tool calls in the last message: {len(state.messages[-1].tool_calls)}")
    
    # Check if there are too many tool calls
    if len(last_message.tool_calls) > 10:
        logger.warning(f"Too many tool calls detected: {len(last_message.tool_calls)} for user {configurable.user_id}")
        return "too_many_tools"
    
    # If there is no tool call or we have reached the max loops, then we finish
    if not last_message.tool_calls or state.loop_step >= configurable.max_loops:
        return "trimmer"
    
    # Otherwise we execute go to tools_approval and check if the tool call requires approval
    return "tools_approval"

def too_many_tools_handler(state: State, config: RunnableConfig) -> dict:
    """Handle the case where there are too many tool calls.
    
    Removes the tool calls from the last message and adds a new message
    informing the user about the situation.
    """
    # Get the last message (which has too many tool calls)
    last_message = state.messages[-1]
    
    # Create a modified version of the last message without tool calls
    modified_message = AIMessage(
        content=last_message.content or "I was trying to execute multiple operations at once.",
        # Important: we're removing the tool_calls by not including them here
    )
    
    # Create a new message to inform the user
    too_many_tools_message = AIMessage(
        content="I apologize, but I've detected too many tool calls in my last response. "
                "This might indicate I'm trying to do too many things at once. "
                "Let's simplify and try again with a more focused approach."
    )
    
    # Return state update with the modified last message (replacing it) and the new message
    # Use RemoveMessage to remove the last message with too many tool calls
    return {
        "messages": [
            RemoveMessage(id=last_message.id),  # Remove the problematic message
            modified_message,  # Add back the content without tool calls
            too_many_tools_message  # Add explanation message
        ]
    }

def trimmer(state: State):
    """Trim the message history to the last 30 messages, removing excess via RemoveMessage."""
    trimmed_messages = trim_messages(
        state.messages,
        strategy="last",
        token_counter=len,
        max_tokens=30,
        start_on="human",
        # end_on=("ai", "tool"),
        include_system=True
    )
    keep_ids = {msg.id for msg in trimmed_messages if msg.id}
    all_ids = {msg.id for msg in state.messages if msg.id}
    delete_ids = all_ids - keep_ids
    deletions = [RemoveMessage(id=msg_id) for msg_id in delete_ids]
    return {"messages": deletions}


builder = StateGraph(State, config_schema=Configuration)

# Add main nodes
builder.add_node("call_model", call_model)
builder.add_node("tools", ToolNode(TOOLS))
builder.add_node("tools_approval", tools_approval)
builder.add_node("trimmer", trimmer)
builder.add_node("too_many_tools", too_many_tools_handler)

builder.add_edge("__start__", "call_model")
builder.add_conditional_edges("call_model", route_model_output)
builder.add_edge("tools_approval", "tools")
builder.add_edge("tools", "call_model")
builder.add_edge("too_many_tools", "trimmer")
builder.add_edge("trimmer", END)

graph = builder.compile(
    interrupt_before=[],
    interrupt_after=[],
)

graph.name = "TelegramAgent"


__all__ = ["graph"]