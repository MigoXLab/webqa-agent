"""Content and DOM extraction utilities.

Provides functions for extracting JSON from LLM responses, text content from
provider-specific message formats, and DOM diff information from tool output.
"""

__all__ = [
    'extract_json_from_response',
    'extract_text_content',
    'safe_get_intermediate_step',
    'extract_dom_diff_from_output',
    'format_elements_for_llm',
]

import json
import logging
import re

logger = logging.getLogger(__name__)

# Attribute whitelist for format_elements_for_llm: attributes that are
# meaningful for LLM understanding of DOM elements.
_IMPORTANT_ATTRS: frozenset[str] = frozenset({
    # Identity
    'class', 'id',
    # Navigation
    'href', 'target', 'rel', 'download',
    # Form
    'type', 'placeholder', 'value', 'name', 'required', 'disabled',
    # Semantic / ARIA
    'role', 'aria-label', 'aria-describedby', 'aria-expanded',
})


def extract_json_from_response(response_text: str) -> str:
    """Extract JSON content from markdown-formatted or plain text response.

    Args:
        response_text: Raw response text from LLM that may contain JSON in markdown blocks

    Returns:
        Extracted JSON string ready for parsing
    """
    if not response_text:
        return ''

    # Check for ```json...``` pattern
    json_match = re.search(r'```json\s*(.*?)\s*```', response_text, re.DOTALL)
    if json_match:
        return json_match.group(1).strip()

    # Check for ```...``` without json marker
    code_match = re.search(r'```\s*(.*?)\s*```', response_text, re.DOTALL)
    if code_match:
        potential_json = code_match.group(1).strip()
        # Basic check if it looks like JSON
        if potential_json.startswith(('[', '{')):
            return potential_json

    # Return as-is if no code blocks found
    return response_text.strip()


def extract_text_content(content: str | list | None) -> str:
    """Extract plain text content from AIMessage or ToolMessage content field.

    Handles provider-specific format differences:
    - ChatOpenAI: content is typically a string
    - ChatAnthropic: content is a list containing {'type': 'text', 'text': '...'} blocks
    - Others: None or other formats

    Args:
        content: AIMessage.content or ToolMessage.content

    Returns:
        str: Extracted plain text content, or empty string if extraction fails

    Examples:
        >>> extract_text_content("Hello")
        'Hello'

        >>> extract_text_content([{'type': 'text', 'text': 'Hello'}, {'type': 'tool_use', ...}])
        'Hello'

        >>> extract_text_content(None)
        ''
    """
    # Case 1: Already a string (OpenAI traditional format)
    if isinstance(content, str):
        return content

    # Case 2: None or empty value
    if content is None:
        return ''

    # Case 3: List format (Anthropic format or OpenAI new format)
    if isinstance(content, list):
        text_parts = []
        for block in content:
            # Handle dictionary-formatted blocks
            if isinstance(block, dict):
                # Anthropic format: {'type': 'text', 'text': '...'}
                if block.get('type') == 'text' and 'text' in block:
                    text_parts.append(block['text'])
                # Some providers might use 'content' key directly
                elif 'content' in block:
                    text_parts.append(str(block['content']))
                # Direct 'text' key without type
                elif 'text' in block:
                    text_parts.append(block['text'])
            # Handle string elements (some edge cases)
            elif isinstance(block, str):
                text_parts.append(block)

        return '\n'.join(text_parts)

    # Case 4: Other types (convert to string)
    try:
        return str(content)
    except Exception:
        logger.warning(f'Failed to extract text from content type: {type(content)}')
        return ''


def safe_get_intermediate_step(
    result: dict, index: int = 0, subindex: int = 1, default: str = ''
) -> str:
    """Safely extract intermediate_steps observation from AgentExecutor result.

    Modified to use extract_text_content for provider compatibility:
    - Original version directly returned step[subindex], which could be a list (Anthropic) or string (OpenAI)
    - Now uses extract_text_content to ensure consistent string output

    Args:
        result: Return value from AgentExecutor.ainvoke()
        index: Index of intermediate_steps (default: 0, i.e., first step)
        subindex: Index within step tuple (default: 1, i.e., observation part)
        default: Default value if extraction fails

    Returns:
        str: Extracted observation text, guaranteed to be a string
    """
    steps = result.get('intermediate_steps', [])
    if isinstance(steps, list) and len(steps) > index:
        step = steps[index]
        if isinstance(step, (list, tuple)) and len(step) > subindex:
            observation = step[subindex]
            # Use extract_text_content to ensure string output
            return extract_text_content(observation)
    return default


def extract_dom_diff_from_output(tool_output: str) -> dict:
    """Extract DOM diff information from tool output."""
    try:
        # Find DOM_DIFF_DETECTED marker (case-insensitive)
        if 'dom_diff_detected:' not in tool_output.lower():
            return {}

        # Extract JSON portion (case-insensitive search)
        tool_output_lower = tool_output.lower()
        marker_idx = tool_output_lower.find('dom_diff_detected:')
        start_idx = marker_idx + len('dom_diff_detected:')
        # Find next line or end of text
        end_idx = tool_output.find('\n\n', start_idx)
        if end_idx == -1:
            json_str = tool_output[start_idx:].strip()
        else:
            json_str = tool_output[start_idx:end_idx].strip()

        return json.loads(json_str)
    except Exception as e:
        logger.debug(f'Failed to extract DOM diff from tool output: {e}')
        return {}


def format_elements_for_llm(dom_diff: dict) -> list[dict]:
    """Format DOM diff information, extracting key information for LLM
    understanding."""
    formatted = []
    for elem_id, elem_data in dom_diff.items():
        # Get key element information
        tag_name = elem_data.get('tagName', '').lower()
        inner_text = elem_data.get('innerText', '')
        attributes = elem_data.get('attributes', {})

        # Build simplified element description
        formatted_elem = {
            'id': elem_id,
            'type': tag_name,
            'text': inner_text[:100] if inner_text else '',  # Limit text length
            'position': {
                'x': elem_data.get('center_x'),
                'y': elem_data.get('center_y'),
            },
        }

        # Add important attribute information
        important_attrs = {}
        if attributes:
            for key, value in attributes.items():
                if key in _IMPORTANT_ATTRS:
                    important_attrs[key] = value
                elif key.startswith('data-'):
                    # Limit length to prevent token explosion
                    important_attrs[key] = (
                        value[:200]
                        if isinstance(value, str) and len(value) > 200
                        else value
                    )
                elif (
                    key == 'style'
                    and isinstance(value, str)
                    and ('display' in value or 'visibility' in value)
                ):
                    important_attrs[key] = (
                        value[:200] + '...' if len(value) > 200 else value
                    )

        if important_attrs:
            formatted_elem['attributes'] = important_attrs

        formatted.append(formatted_elem)

    return formatted
