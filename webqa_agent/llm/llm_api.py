"""LLM API Wrapper supporting OpenAI, Anthropic Claude, and Google Gemini
models.

This module provides a unified interface for multiple LLM providers:
- OpenAI: Chat Completions API (gpt-4, gpt-4o, o1, o3) and Responses API (gpt-5 family)
- Anthropic: Messages API with Extended Thinking support (Claude 3.5+)
- Gemini: OpenAI-compatible endpoint (Gemini 2.5, 3.x)

Key Features:
- Auto-detection of provider based on model name prefix
- Provider-specific defaults (temperature, base_url, reasoning parameters)
- Defensive response handling for relay service compatibility
- Comprehensive error handling with OpenAI SDK exception types

Responses API (GPT-5 family):
- Format: client.responses.create(model, instructions, input, reasoning, text)
- Parameter constraints vary by model:
  - GPT-5.1: temperature/top_p ONLY with reasoning.effort="none"
  - Other GPT-5 models: NO temperature/top_p support
  - Use reasoning.effort and text.verbosity as alternatives
"""

import logging

import openai
from openai import AsyncOpenAI

# Anthropic SDK - optional dependency
try:
    from anthropic import AsyncAnthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    AsyncAnthropic = None  # Type placeholder


# Extended Thinking effort to budget_tokens mapping
# Anthropic API requirements: min 1024, must be < max_tokens
EXTENDED_THINKING_EFFORT_MAPPING = {
    'minimal': 1024,   # Quick analysis
    'low': 4096,       # Basic reasoning
    'medium': 10000,   # Balanced (recommended)
    'high': 20000,     # Deep analysis
}


class LLMAPI:
    def __init__(self, llm_config) -> None:
        self.llm_config = llm_config
        self.api_type = self.llm_config.get('api')  # Keep for backward compatibility
        self.model = self.llm_config.get('model')
        self.filter_model = self.llm_config.get('filter_model', self.model)  # For two-stage architecture

        # Provider detection based on model name
        self.provider = self._detect_provider(self.model)

        self.client = None

    def _detect_provider(self, model_name: str) -> str:
        """Detect provider based on model name.

        Returns:
            str: 'anthropic' for Claude models, 'gemini' for Gemini models, 'openai' for GPT models

        Raises:
            ImportError: If required library not installed for the model
        """
        if not model_name:
            return 'openai'  # Default to OpenAI

        model_lower = model_name.lower()

        # Claude models (claude-3-*, claude-3.5-*, etc.)
        if model_lower.startswith('claude-'):
            if not ANTHROPIC_AVAILABLE:
                raise ImportError(
                    f"Model '{model_name}' requires 'anthropic' library. "
                    'Install with: pip install anthropic>=0.40.0'
                )
            return 'anthropic'

        # Google Gemini models (gemini-2.5-*, gemini-3-*, etc.)
        # Uses OpenAI SDK for compatibility (no separate library required)
        if model_lower.startswith('gemini-'):
            return 'gemini'

        # OpenAI models (gpt-*, o1-*, o3-*)
        if model_lower.startswith(('gpt-', 'o1-', 'o3-')):
            return 'openai'

        # Default to OpenAI for unknown models
        return 'openai'

    async def initialize(self):
        if self.provider in ('openai', 'gemini'):
            # Unified AsyncOpenAI client for both OpenAI and Gemini models
            self.api_key = self.llm_config.get('api_key')
            if not self.api_key:
                raise ValueError(f'API key is empty. {self.provider.capitalize()} client not initialized.')

            self.base_url = self.llm_config.get('base_url')

            # Set default base_url for Gemini if not explicitly configured
            # Gemini officially supports OpenAI SDK via this compatibility endpoint
            if self.provider == 'gemini' and not self.base_url:
                self.base_url = 'https://generativelanguage.googleapis.com/v1beta/openai/'

            # Use AsyncOpenAI client for async operations
            self.client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url, timeout=360) if self.base_url else AsyncOpenAI(
                api_key=self.api_key, timeout=360)
            logging.debug(
                f'AsyncOpenAI client initialized - provider: {self.provider}, '
                f'model: {self.model}, base_url: {self.base_url}'
            )

        elif self.provider == 'anthropic':
            self.api_key = self.llm_config.get('api_key')
            if not self.api_key:
                raise ValueError('API key is empty. Anthropic client not initialized.')

            # Anthropic client initialization (base_url is optional for custom endpoints)
            self.base_url = self.llm_config.get('base_url')
            if self.base_url:
                self.client = AsyncAnthropic(api_key=self.api_key, base_url=self.base_url, timeout=360.0)
                logging.debug(f'AsyncAnthropic client initialized with API key: {self.api_key}, Model: {self.model} and base URL: {self.base_url}')
            else:
                self.client = AsyncAnthropic(api_key=self.api_key, timeout=360.0)
                logging.debug(f'AsyncAnthropic client initialized with API key: {self.api_key}, Model: {self.model}')

        else:
            raise ValueError(f"Invalid provider '{self.provider}' or missing credentials. LLM client not initialized.")

        return self

    async def get_llm_response(
        self,
        system_prompt,
        prompt,
        images=None,
        temperature=None,
        top_p=None,
        max_tokens=None,
        model_override=None,
        reasoning=None,
        text=None,
    ):
        """Get LLM response with unified interface for OpenAI and Anthropic
        models.

        Args:
            system_prompt: System prompt (used as 'instructions' in Responses API, 'system' in Anthropic)
            prompt: User prompt (used as 'input' in Responses API)
            images: Optional base64 image(s) for vision models
            temperature: Sampling temperature (0-2)
            top_p: Nucleus sampling parameter
            max_tokens: Maximum output tokens (REQUIRED for Claude models)
            model_override: Temporary model override (e.g., for two-stage architecture)
            reasoning: Reasoning effort control. Can be:
                - dict: {"effort": "minimal"|"low"|"medium"|"high"}
                - str: "minimal"|"low"|"medium"|"high"
                - None: Uses config or defaults
                For OpenAI GPT-5: Auto-calculated reasoning budget
                For Claude: Maps to thinking.budget_tokens (minimal=1024, low=4096, medium=10000, high=20000)
            text: Output verbosity control for GPT-5 models. Can be:
                - dict: {"verbosity": "low"|"medium"|"high"}
                - str: "low"|"medium"|"high"
                - None: Uses config or defaults to "medium"

        Returns:
            str: Model response content

        Note:
            - Claude models (claude-*) use Anthropic Messages API
            - GPT-5 family models (gpt-5*) use OpenAI Responses API
            - Other models use OpenAI Chat Completions API
        """
        # Allow temporary model override for two-stage architecture
        actual_model = model_override or self.model

        # Detect provider for the actual model being used
        actual_provider = self._detect_provider(actual_model)

        # Initialize client if not already initialized
        if self.client is None:
            await self.initialize()

        # Auto-read reasoning from config if not explicitly passed
        if reasoning is None:
            reasoning = self.llm_config.get('reasoning')

        try:
            # Resolve common parameters
            resolved_max_tokens = max_tokens if max_tokens is not None else self.llm_config.get('max_tokens')

            # Route to appropriate API based on provider
            if actual_provider == 'anthropic':
                # Claude models -> Anthropic Messages API
                # Temperature defaults to 1.0 for Claude (Anthropic best practice)
                resolved_temperature = temperature if temperature is not None else self.llm_config.get('temperature', 1.0)
                resolved_top_p = top_p if top_p is not None else self.llm_config.get('top_p')

                result = await self._call_anthropic_api(
                    system_prompt=system_prompt,
                    prompt=prompt,
                    images=images,
                    temperature=resolved_temperature,
                    top_p=resolved_top_p,
                    max_tokens=resolved_max_tokens,
                    model=actual_model,
                    reasoning=reasoning,
                    text=text,
                )

            elif actual_provider in ('openai', 'gemini'):
                # Unified OpenAI SDK path for both OpenAI and Gemini models
                # Uses AsyncOpenAI client (raw OpenAI SDK, not LangChain wrapper)
                # Gemini officially supports OpenAI compatibility: generativelanguage.googleapis.com/v1beta/openai/

                # Determine which OpenAI API to use based on model
                use_responses_api = self._use_responses_api(actual_model)

                if use_responses_api:
                    # GPT-5 models -> Responses API
                    # Note: temperature/top_p only supported with GPT-5.1 + effort="none"
                    # Only pass if explicitly configured (no default)
                    resolved_temperature = temperature if temperature is not None else self.llm_config.get('temperature')
                    resolved_top_p = top_p if top_p is not None else self.llm_config.get('top_p')

                    result = await self._call_responses_api(
                        system_prompt=system_prompt,
                        prompt=prompt,
                        images=images,
                        temperature=resolved_temperature,
                        top_p=resolved_top_p,
                        max_tokens=resolved_max_tokens,
                        model=actual_model,
                        reasoning=reasoning,
                        text=text,
                    )
                else:
                    # Non-GPT-5 models -> Chat Completions API
                    # Provider-specific temperature defaults: Gemini=1.0, OpenAI=0.1
                    if actual_provider == 'gemini':
                        default_temp = 1.0  # Gemini best practice
                    else:
                        default_temp = 0.1  # OpenAI default for deterministic output

                    resolved_temperature = temperature if temperature is not None else self.llm_config.get('temperature', default_temp)
                    resolved_top_p = top_p if top_p is not None else self.llm_config.get('top_p')

                    result = await self._call_chat_completions_api(
                        system_prompt=system_prompt,
                        prompt=prompt,
                        images=images,
                        temperature=resolved_temperature,
                        top_p=resolved_top_p,
                        max_tokens=resolved_max_tokens,
                        model=actual_model,
                        reasoning=reasoning,
                    )

            else:
                raise ValueError(f"Unknown provider '{actual_provider}' for model '{actual_model}'")

            return result
        except Exception as e:
            logging.error(f'LLMAPI.get_llm_response encountered error: {e}')
            raise

    def _use_responses_api(self, model_name: str) -> bool:
        """Determine whether to use the Responses API for the given model.

        Responses API is used for all GPT-5 family models:
        - gpt-5 (default reasoning effort: medium)
        - gpt-5.1 (default reasoning effort: none for low-latency)
        - gpt-5-mini
        - gpt-5-nano

        All GPT-5 models support reasoning.effort and text.verbosity parameters.
        """
        if not model_name:
            return False
        model_lower = model_name.lower()
        return model_lower.startswith('gpt-5')

    def _resolve_reasoning_params(self, model: str, reasoning, text):
        """Resolve reasoning and text parameters for GPT-5 models.

        All GPT-5 family models support:
        - reasoning.effort: "none" | "low" | "medium" | "high"
        - text.verbosity: "low" | "medium" | "high"

        Defaults:
        - GPT-5.1: reasoning effort = "none" (low-latency), verbosity = "medium"
        - GPT-5/GPT-5-mini/GPT-5-nano: reasoning effort = "medium", verbosity = "medium"
        """
        model_lower = model.lower() if model else ''
        is_gpt51 = model_lower.startswith('gpt-5.1')

        # GPT-5.1 defaults to "none" (low-latency), GPT-5/mini/nano defaults to "medium"
        default_reasoning = 'none' if is_gpt51 else 'medium'

        # Resolve reasoning effort
        resolved_effort = self._resolve_param(reasoning, 'reasoning', 'effort', default_reasoning)

        # Resolve text verbosity (all GPT-5 models default to "medium")
        resolved_verbosity = self._resolve_param(text, 'text', 'verbosity', 'medium')

        return resolved_effort, resolved_verbosity

    def _resolve_param(self, override, config_key, sub_key, default):
        """Generic parameter resolver: override > config[key][sub_key] > default."""
        # Check override (supports dict with sub_key or direct value)
        if override is not None:
            if isinstance(override, dict):
                value = override.get(sub_key)
                if value:
                    return value
            else:
                return override

        # Check config nested structure (e.g., config.reasoning.effort)
        config_obj = self.llm_config.get(config_key)
        if isinstance(config_obj, dict):
            value = config_obj.get(sub_key)
            if value:
                return value

        return default

    async def _call_responses_api(
        self,
        system_prompt: str,
        prompt: str,
        images=None,
        temperature=None,
        top_p=None,
        max_tokens=None,
        model=None,
        reasoning=None,
        text=None,
    ):
        """Call OpenAI Responses API for GPT-5/GPT-5.1 models.

        See module docstring for detailed Responses API format and parameter
        compatibility.
        """
        try:
            actual_model = model or self.llm_config.get('model')
            model_lower = actual_model.lower() if actual_model else ''

            # Resolve reasoning parameters
            resolved_effort, resolved_verbosity = self._resolve_reasoning_params(actual_model, reasoning, text)

            # Check if temperature/top_p are allowed
            # ONLY GPT-5.1 with reasoning.effort="none" supports temperature/top_p
            is_gpt51 = model_lower.startswith('gpt-5.1')
            supports_sampling_params = is_gpt51 and resolved_effort == 'none'

            if not supports_sampling_params and (temperature is not None or top_p is not None):
                if is_gpt51:
                    # GPT-5.1 design: reasoning and sampling are mutually exclusive
                    # When reasoning is active (effort != "none"), model uses internal reasoning process
                    # that doesn't support external sampling control (temperature/top_p)
                    logging.debug(
                        "GPT-5.1 with reasoning.effort='%s': temperature/top_p not supported (only allowed with effort='none'). "
                        'Reasoning models use internal sampling that cannot be externally controlled.',
                        resolved_effort
                    )
                else:
                    # Other GPT-5 models don't support temperature/top_p at all
                    # Use reasoning.effort and text.verbosity for output control instead
                    logging.debug(
                        "Model '%s' does not support temperature/top_p. Use reasoning.effort/text.verbosity instead.",
                        actual_model
                    )

            # Build request kwargs
            create_kwargs = {
                'model': actual_model,
                'instructions': system_prompt,  # System prompt as instructions
                'timeout': 360,
            }

            # Build input - can be simple string or structured with images
            if images:
                # With images, use structured input format
                input_content = [{'type': 'input_text', 'text': prompt}]
                self._append_images_to_content(input_content, images)
                create_kwargs['input'] = [{'role': 'user', 'content': input_content}]
            else:
                # Simple string input
                create_kwargs['input'] = prompt

            # Add temperature/top_p ONLY for GPT-5.1 with reasoning.effort="none"
            if supports_sampling_params:
                if temperature is not None:
                    create_kwargs['temperature'] = temperature
                if top_p is not None:
                    create_kwargs['top_p'] = top_p

            # max_output_tokens is always supported for all GPT-5 models
            if max_tokens is not None:
                create_kwargs['max_output_tokens'] = max_tokens

            # Add reasoning and text parameters (all GPT-5 models support these)
            if resolved_effort is not None:
                create_kwargs['reasoning'] = {'effort': resolved_effort}
            if resolved_verbosity is not None:
                create_kwargs['text'] = {'verbosity': resolved_verbosity}

            logging.debug(
                'Responses API request - model: %s, temperature: %s, max_output_tokens: %s, reasoning: %s, text: %s',
                actual_model,
                create_kwargs.get('temperature'),
                create_kwargs.get('max_output_tokens'),
                create_kwargs.get('reasoning'),
                create_kwargs.get('text'),
            )

            response = await self.client.responses.create(**create_kwargs)

            # Extract output text from response
            content = getattr(response, 'output_text', None)
            logging.debug(f'Responses API response: {content}')
            if not content:
                # Fallback: try to extract from output array
                if hasattr(response, 'output') and response.output:
                    for item in response.output:
                        if getattr(item, 'type', None) == 'message':
                            if hasattr(item, 'content') and item.content:
                                for c in item.content:
                                    if getattr(c, 'type', None) == 'output_text':
                                        content = getattr(c, 'text', None)
                                        break
                            break
            if not content:
                content = str(response)

            # logging.debug(f"Responses API response received, length: {len(content) if content else 0}")
            content = self._clean_response(content)
            return content

        except Exception as e:
            error_msg = f"Responses API request failed for model '{model}': {str(e)}"
            logging.error(error_msg)
            raise ValueError(error_msg)

    async def _call_chat_completions_api(
        self,
        system_prompt: str,
        prompt: str,
        images=None,
        temperature=None,
        top_p=None,
        max_tokens=None,
        model=None,
        reasoning=None,
    ):
        """Call OpenAI Chat Completions API for non-GPT-5 models.

        Supports reasoning_effort parameter for:
        - OpenAI o1/o3 models
        - Gemini models (via OpenAI compatibility endpoint)
        """
        try:
            actual_model = model or self.llm_config.get('model')

            # Build messages
            messages = [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': [{'type': 'text', 'text': prompt}]},
            ]

            # Add images if provided
            if images:
                self._append_images_to_messages(messages, images)

            create_kwargs = {
                'model': actual_model,
                'messages': messages,
                'timeout': 360,
            }

            if temperature is not None:
                create_kwargs['temperature'] = temperature
            if top_p is not None:
                create_kwargs['top_p'] = top_p
            if max_tokens is not None:
                create_kwargs['max_tokens'] = max_tokens

            # Add reasoning_effort if reasoning config is provided
            # Works for both OpenAI o1/o3 and Gemini models
            if reasoning and isinstance(reasoning, dict):
                effort = reasoning.get('effort')
                if effort:
                    # Map effort levels to reasoning_effort parameter
                    # Supports: minimal, low, medium, high (OpenAI/Gemini compatible)
                    effort_mapping = {
                        'minimal': 'low',
                        'low': 'low',
                        'medium': 'medium',
                        'high': 'high',
                    }
                    reasoning_effort = effort_mapping.get(effort.lower())
                    if reasoning_effort:
                        create_kwargs['reasoning_effort'] = reasoning_effort
                        logging.debug(f"Using reasoning_effort='{reasoning_effort}' for model '{actual_model}'")

            logging.debug(
                'Chat Completions API request - model: %s, temperature: %s, max_tokens: %s',
                actual_model,
                create_kwargs.get('temperature'),
                create_kwargs.get('max_tokens'),
            )

            completion = await self.client.chat.completions.create(**create_kwargs)

            # Defensive response extraction - handles both ChatCompletion objects and string responses
            content = None

            # Try standard ChatCompletion object structure
            if hasattr(completion, 'choices') and completion.choices:
                content = completion.choices[0].message.content
                logging.debug(f'Chat Completions API response received (ChatCompletion object), length: {len(content) if content else 0}')

            # Fallback: Handle relay services that return plain strings
            # Some relay services (particularly third-party Gemini relays) return strings
            # instead of ChatCompletion objects when using reasoning_effort parameter
            elif isinstance(completion, str):
                content = completion
                if 'reasoning_effort' in create_kwargs:
                    # Warn about potential relay service incompatibility with reasoning features
                    logging.warning(
                        f"Relay service at '{self.base_url}' returned plain string instead of ChatCompletion object. "
                        f'This may indicate incompatibility with reasoning_effort parameter. '
                        f'Consider using official Gemini endpoint or disabling reasoning configuration.'
                    )
                logging.debug(f'Chat Completions API response received (string fallback), length: {len(content)}')

            # Handle unexpected response types
            else:
                response_type = type(completion).__name__
                raise ValueError(
                    f"Unexpected response type '{response_type}' from Chat Completions API. "
                    f'Expected ChatCompletion object or string. '
                    f'Base URL: {self.base_url}, Model: {actual_model}'
                )

            content = self._clean_response(content)
            return content

        # Official OpenAI SDK error handling patterns
        except openai.APIConnectionError as e:
            error_msg = f"Chat Completions API connection failed for model '{model}': {str(e)}"
            logging.error(error_msg)
            logging.debug(f'Underlying cause: {e.__cause__}')
            raise ValueError(error_msg)

        except openai.RateLimitError as e:
            error_msg = f"Rate limit exceeded for model '{model}' (429 status)"
            logging.error(error_msg)
            logging.debug(f"Request ID: {e.request_id if hasattr(e, 'request_id') else 'N/A'}")
            raise ValueError(error_msg)

        except openai.APIStatusError as e:
            # This catches relay service errors and other API issues
            error_msg = f"Chat Completions API error for model '{model}': Status {e.status_code}"
            logging.error(error_msg)
            logging.debug(f'Response: {e.response}')
            logging.debug(f"Request ID: {e.request_id if hasattr(e, 'request_id') else 'N/A'}")
            raise ValueError(error_msg)

        except AttributeError as e:
            # Catch response attribute access errors (e.g., str has no 'choices')
            error_msg = (
                f"Invalid response format from Chat Completions API for model '{model}': {str(e)}. "
                f'This may indicate relay service incompatibility with reasoning_effort parameter. '
                f'Base URL: {self.base_url}'
            )
            logging.error(error_msg)
            raise ValueError(error_msg)

        except Exception as e:
            # General fallback for unexpected errors
            error_msg = f"Chat Completions API request failed for model '{model}': {str(e)}"
            logging.error(error_msg)
            raise ValueError(error_msg)

    async def _call_anthropic_api(
        self,
        system_prompt: str,
        prompt: str,
        images=None,
        temperature=None,
        top_p=None,
        max_tokens=None,
        model=None,
        reasoning=None,
        text=None,
    ):
        """Call Anthropic Messages API for Claude models.

        Anthropic Messages API format:
            response = client.messages.create(
                model="claude-3-5-sonnet-20241022",
                system="System prompt here",
                messages=[{"role": "user", "content": "User input"}],
                max_tokens=1024,  # REQUIRED
                temperature=1.0,  # Optional, defaults to 1.0
                thinking={         # Optional, for extended thinking
                    "type": "enabled",
                    "budget_tokens": 10000
                }
            )

        Parameter differences from OpenAI:
            - system: Separate parameter (not in messages array)
            - max_tokens: REQUIRED (API fails without it)
            - temperature: Defaults to 1.0 (not 0.1 like OpenAI)
            - thinking: Manual token budget allocation based on reasoning.effort
        """
        try:
            actual_model = model or self.llm_config.get('model')

            # max_tokens is REQUIRED for Claude API
            if max_tokens is None:
                max_tokens = self.llm_config.get('max_tokens')
                if max_tokens is None:
                    # Default to 4096 if not specified (Claude's safe default)
                    max_tokens = 4096
                    logging.debug(f'max_tokens not specified, using default: {max_tokens}')

            # Build messages array (system is separate in Anthropic API)
            messages = []
            user_content = []

            # Add text content
            user_content.append({'type': 'text', 'text': prompt})

            # Add images if provided (base64 format)
            if images:
                self._append_images_to_anthropic_content(user_content, images)

            messages.append({'role': 'user', 'content': user_content})

            # Build request kwargs
            create_kwargs = {
                'model': actual_model,
                'system': system_prompt,  # Separate parameter in Anthropic API
                'messages': messages,
                'max_tokens': max_tokens,  # REQUIRED
                'timeout': 360.0,
            }

            # Temperature defaults to 1.0 for Claude (Anthropic best practice)
            resolved_temperature = temperature if temperature is not None else self.llm_config.get('temperature', 1.0)
            create_kwargs['temperature'] = resolved_temperature

            # top_p is optional
            if top_p is not None:
                create_kwargs['top_p'] = top_p

            # Handle reasoning.effort → thinking.budget_tokens mapping
            if reasoning is not None:
                thinking_config = self._map_effort_to_thinking(
                    reasoning,
                    actual_model,
                    max_tokens=create_kwargs.get('max_tokens')
                )
                if thinking_config:
                    create_kwargs['thinking'] = thinking_config
                    logging.debug(f'Extended thinking enabled: {thinking_config}')

                    # Extended Thinking requires temperature=1 for Anthropic API
                    if resolved_temperature != 1:
                        logging.warning(
                            f'Extended Thinking requires temperature=1 for Claude models. '
                            f'Overriding configured temperature {resolved_temperature} to 1.0'
                        )
                        resolved_temperature = 1
                        create_kwargs['temperature'] = resolved_temperature

            logging.debug(
                'Anthropic Messages API request - model: %s, temperature: %s, max_tokens: %s, thinking: %s',
                actual_model,
                create_kwargs.get('temperature'),
                create_kwargs.get('max_tokens'),
                create_kwargs.get('thinking'),
            )

            response = await self.client.messages.create(**create_kwargs)

            # Extract content from response
            content = ''
            for block in response.content:
                if hasattr(block, 'type') and block.type == 'text':
                    content += block.text

            if not content:
                content = str(response)

            logging.debug(f'Anthropic Messages API response received, length: {len(content) if content else 0}')
            content = self._clean_response(content)
            return content

        # Catch-all exception handler for Anthropic Messages API
        # Converts all exceptions to ValueError for consistent error handling across providers
        # Logs original exception message for debugging before re-raising as ValueError
        except Exception as e:
            error_str = str(e)

            # Add specific guidance for Extended Thinking errors
            if 'budget' in error_str.lower() and 'tokens' in error_str.lower():
                thinking_config = create_kwargs.get('thinking', {})
                budget = thinking_config.get('budget_tokens', 'N/A')
                max_tok = create_kwargs.get('max_tokens', 'N/A')

                error_msg = (
                    f'Anthropic API error: {error_str}\n'
                    f'💡 Extended Thinking config: budget_tokens={budget}, max_tokens={max_tok}\n'
                    f'   Fix: Increase max_tokens or reduce reasoning.effort in config'
                )
            else:
                error_msg = f"Anthropic Messages API request failed for model '{model}': {error_str}"

            logging.error(error_msg)
            raise ValueError(error_msg)

    def _map_effort_to_thinking(self, reasoning, model: str, max_tokens: int = None) -> dict:
        """Map reasoning.effort to Anthropic thinking configuration with
        validation.

        Reasoning effort to budget_tokens mapping (Anthropic API requirement: min 1024):
            - minimal: 1024 tokens  (quick, low-cost reasoning)
            - low: 4096 tokens      (basic analysis)
            - medium: 10000 tokens  (balanced, recommended for testing)
            - high: 20000 tokens    (deep analysis, complex scenarios)

        Validation: budget_tokens must be < max_tokens (Anthropic API requirement)

        Args:
            reasoning: Can be dict {"effort": "medium"} or str "medium"
            model: Model name for logging
            max_tokens: Maximum output tokens for validation

        Returns:
            dict: {"type": "enabled", "budget_tokens": N} or None if effort is None
        """
        effort = None

        # Extract effort from reasoning parameter
        if isinstance(reasoning, dict):
            effort = reasoning.get('effort')
        elif isinstance(reasoning, str):
            effort = reasoning
        else:
            # Check config
            config_reasoning = self.llm_config.get('reasoning')
            if isinstance(config_reasoning, dict):
                effort = config_reasoning.get('effort')

        if not effort:
            return None  # No thinking configuration

        # Use shared effort mapping constant
        budget_tokens = EXTENDED_THINKING_EFFORT_MAPPING.get(effort.lower())
        if not budget_tokens:
            logging.warning(f"Unknown reasoning effort '{effort}' for model '{model}', skipping thinking configuration")
            return None

        # Validate: budget_tokens must be < max_tokens (Anthropic API requirement)
        if max_tokens and budget_tokens >= max_tokens:
            # Calculate recommended max_tokens (budget should be 40-60% of max)
            recommended_max = int(budget_tokens / 0.5)  # 50% ratio as middle ground

            logging.warning(
                f'Extended Thinking: budget_tokens ({budget_tokens}) >= max_tokens ({max_tokens}). '
                f'Auto-adjusting budget to {max_tokens - 1}. '
                f'Recommended: Set max_tokens={recommended_max} for effort={effort}'
            )

            budget_tokens = max_tokens - 1

        return {'type': 'enabled', 'budget_tokens': budget_tokens}

    def _append_images_to_anthropic_content(self, content: list, images):
        """Append images to Anthropic Messages API content array.

        Format for Anthropic Messages API:
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": "base64_string_without_prefix"
                }
            }

        Note: Anthropic expects base64 data WITHOUT the "data:image/jpeg;base64," prefix
        """
        try:
            if isinstance(images, str):
                content.append(self._format_anthropic_image(images))
            elif isinstance(images, list):
                for image_base64 in images:
                    content.append(self._format_anthropic_image(image_base64))
            else:
                raise ValueError("Invalid type for 'images'. Expected a base64 string or a list of base64 strings.")
        except Exception as e:
            logging.error(f'Error appending images to Anthropic Messages content: {e}')
            raise

    def _format_anthropic_image(self, image_base64: str) -> dict:
        """Format a base64 image for Anthropic Messages API.

        Args:
            image_base64: Base64 image string (may include "data:image/...;base64," prefix)

        Returns:
            dict: Anthropic image content block
        """
        # Remove data URL prefix if present
        if 'base64,' in image_base64:
            # Extract media type and data
            prefix, data = image_base64.split('base64,', 1)
            # Extract media type from prefix (e.g., "data:image/jpeg;")
            media_type = prefix.replace('data:', '').replace(';', '').strip()
            if not media_type:
                media_type = 'image/jpeg'  # Default
        else:
            # No prefix, assume raw base64 data
            media_type = 'image/jpeg'
            data = image_base64

        return {
            'type': 'image',
            'source': {'type': 'base64', 'media_type': media_type, 'data': data},
        }

    def _append_images_to_content(self, content: list, images):
        """Append images to Responses API content array.

        Format for Responses API:
            {"type": "input_image", "image_url": "data:image/..."}
        """
        try:
            if isinstance(images, str):
                content.append({
                    'type': 'input_image',
                    'image_url': images,
                })
            elif isinstance(images, list):
                for image_base64 in images:
                    content.append({
                        'type': 'input_image',
                        'image_url': image_base64,
                    })
            else:
                raise ValueError("Invalid type for 'images'. Expected a base64 string or a list of base64 strings.")
        except Exception as e:
            logging.error(f'Error appending images to Responses API content: {e}')
            raise

    def _append_images_to_messages(self, messages: list, images):
        """Append images to Chat Completions API messages.

        Format for Chat Completions API:
            {"type": "image_url", "image_url": {"url": "data:image/...", "detail": "low"}}
        """
        try:
            user_content = messages[1]['content']

            if isinstance(images, str):
                user_content.append({
                    'type': 'image_url',
                    'image_url': {'url': images, 'detail': 'low'}
                })
            elif isinstance(images, list):
                for image_base64 in images:
                    user_content.append({
                        'type': 'image_url',
                        'image_url': {'url': image_base64, 'detail': 'low'}
                    })
            else:
                raise ValueError("Invalid type for 'images'. Expected a base64 string or a list of base64 strings.")
        except Exception as e:
            logging.error(f'Error appending images to Chat Completions messages: {e}')
            raise

    def _clean_response(self, response):
        """Remove JSON code block markers from the response if present."""
        try:
            if response and isinstance(response, str):
                # Check if response starts with ```json and ends with ```
                if response.startswith('```json') and response.endswith('```'):
                    logging.debug('Cleaning response: Removing ```json``` markers')
                    return response[7:-3].strip()
                # Check if it just has ``` without json specification
                elif response.startswith('```') and response.endswith('```'):
                    logging.debug('Cleaning response: Removing ``` markers')
                    return response[3:-3].strip()

                # Encode response as UTF-8
                response = response.encode('utf-8').decode('utf-8')
            return response
        except Exception as e:
            logging.error(f'Error while cleaning response: {e}')
            logging.error(f'Original response: {response}')
            return response

    async def close(self):
        if self.client:
            await self.client.close()
            self.client = None
