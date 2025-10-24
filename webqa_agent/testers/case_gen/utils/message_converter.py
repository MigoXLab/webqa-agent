"""Utility functions for converting intermediate steps to messages format."""

import logging
from typing import List, Tuple, Any
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage


def convert_intermediate_steps_to_messages(
        intermediate_steps: List[Tuple[Any, str]]
) -> List[BaseMessage]:
    """Convert intermediate steps from AgentExecutor to proper message format.

    Args:
        intermediate_steps: List of (ToolAgentAction, observation) tuples

    Returns:
        List of BaseMessage objects (AIMessage with tool_calls + ToolMessage pairs)
    """
    messages = []

    for action, observation in intermediate_steps:
        try:
            # Extract AIMessage with tool_calls from the action
            if hasattr(action, 'message_log') and action.message_log:
                # The message_log contains the AIMessageChunk with tool_calls
                ai_msg_chunk = action.message_log[0]

                # Convert AIMessageChunk to proper AIMessage with tool_calls
                if hasattr(ai_msg_chunk, 'tool_calls') and ai_msg_chunk.tool_calls:
                    ai_message = AIMessage(
                        content=ai_msg_chunk.content or "",
                        tool_calls=ai_msg_chunk.tool_calls
                    )
                    messages.append(ai_message)

                    # Add the corresponding ToolMessage
                    tool_call_id = ai_msg_chunk.tool_calls[0].get('id') if ai_msg_chunk.tool_calls else None
                    if tool_call_id:
                        # Ensure observation is a string, not a list
                        if isinstance(observation, list):
                            observation_content = str(observation) if observation else "No response"
                        elif observation is None:
                            observation_content = "No response"
                        else:
                            observation_content = str(observation)

                        tool_message = ToolMessage(
                            content=observation_content,
                            tool_call_id=tool_call_id
                        )
                        messages.append(tool_message)
                    else:
                        logging.warning(f"No tool_call_id found for action: {action}")

            elif hasattr(action, 'tool_call_id'):
                # Fallback: If action has tool_call_id directly
                # Create a simplified AIMessage with tool info
                tool_calls = [{
                    'id': action.tool_call_id,
                    'name': action.tool if hasattr(action, 'tool') else 'unknown',
                    'args': action.tool_input if hasattr(action, 'tool_input') else {},
                    'type': 'tool_call'
                }]

                ai_message = AIMessage(
                    content="",
                    tool_calls=tool_calls
                )
                messages.append(ai_message)

                # Add the corresponding ToolMessage
                # Ensure observation is a string, not a list
                if isinstance(observation, list):
                    observation_content = str(observation) if observation else "No response"
                elif observation is None:
                    observation_content = "No response"
                else:
                    observation_content = str(observation)

                tool_message = ToolMessage(
                    content=observation_content,
                    tool_call_id=action.tool_call_id
                )
                messages.append(tool_message)
            else:
                logging.debug(f"Skipping action without proper tool call structure: {type(action)}")

        except Exception as e:
            logging.error(f"Error converting intermediate step to messages: {str(e)}")
            # Continue processing other steps even if one fails
            continue

    return messages
