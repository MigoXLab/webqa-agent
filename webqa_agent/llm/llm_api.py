import logging

from openai import AsyncOpenAI


class LLMAPI:
    def __init__(self, llm_config) -> None:
        self.llm_config = llm_config
        self.api_type = self.llm_config.get('api')
        self.model = self.llm_config.get('model')
        self.filter_model = self.llm_config.get('filter_model', self.model)  # For two-stage architecture
        self.client = None

    async def initialize(self):
        if self.api_type == 'openai':
            self.api_key = self.llm_config.get('api_key')
            if not self.api_key:
                raise ValueError('API key is empty. OpenAI client not initialized.')
            self.base_url = self.llm_config.get('base_url')
            # Use AsyncOpenAI client for async operations
            self.client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url, timeout=60) if self.base_url else AsyncOpenAI(
                api_key=self.api_key, timeout=360)
            logging.debug(f'AsyncOpenAI client initialized with Model: {self.model} and base URL: {self.base_url}')
        else:
            raise ValueError('Invalid API type or missing credentials. LLM client not initialized.')

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
        """Get LLM response with support for GPT-5 Responses API.

        Args:
            system_prompt: System prompt (used as 'instructions' in Responses API)
            prompt: User prompt (used as 'input' in Responses API)
            images: Optional base64 image(s) for vision models
            temperature: Sampling temperature (0-2)
            top_p: Nucleus sampling parameter
            max_tokens: Maximum output tokens
            model_override: Temporary model override (e.g., for two-stage architecture)
            reasoning: Reasoning effort control for GPT-5 models. Can be:
                - dict: {"effort": "none"|"low"|"medium"|"high"}
                - str: "none"|"low"|"medium"|"high"
                - None: Uses config or defaults ("none" for gpt-5.1, "medium" for gpt-5/mini/nano)
            text: Output verbosity control for GPT-5 models. Can be:
                - dict: {"verbosity": "low"|"medium"|"high"}
                - str: "low"|"medium"|"high"
                - None: Uses config or defaults to "medium"

        Returns:
            str: Model response content

        Note:
            - All GPT-5 family models (gpt-5, gpt-5.1, gpt-5-mini, gpt-5-nano) use Responses API
            - Other models use Chat Completions API
        """
        # Allow temporary model override for two-stage architecture
        actual_model = model_override or self.model
        if self.api_type == 'openai' and self.client is None:
            await self.initialize()

        # Determine which API to use based on model
        use_responses_api = self._use_responses_api(actual_model)

        try:
            # Resolve common parameters
            resolved_max_tokens = max_tokens if max_tokens is not None else self.llm_config.get('max_tokens')

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
                # Default temperature to 0.1 for Chat Completions
                resolved_temperature = temperature if temperature is not None else self.llm_config.get('temperature', 0.1)
                resolved_top_p = top_p if top_p is not None else self.llm_config.get('top_p')

                result = await self._call_chat_completions_api(
                    system_prompt=system_prompt,
                    prompt=prompt,
                    images=images,
                    temperature=resolved_temperature,
                    top_p=resolved_top_p,
                    max_tokens=resolved_max_tokens,
                    model=actual_model,
                )

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

        Responses API format:
            response = client.responses.create(
                model="gpt-5.1",
                instructions="System prompt here",
                input="User input here" or [{"role": "user", "content": [...]}],
                reasoning={"effort": "low"},
                text={"verbosity": "medium"},
            )

        Parameter compatibility:
            - temperature, top_p, logprobs: ONLY supported with GPT-5.1 + reasoning.effort="none"
            - Other GPT-5 models (gpt-5, gpt-5-mini, gpt-5-nano) do NOT support these parameters
            - Use reasoning.effort, text.verbosity, max_output_tokens as alternatives
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
                    logging.debug(
                        "GPT-5.1 with reasoning.effort='%s': temperature/top_p not supported (only allowed with effort='none').",
                        resolved_effort
                    )
                else:
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
    ):
        """Call OpenAI Chat Completions API for non-GPT-5 models.

        Note: This API does NOT support reasoning/text parameters.
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

            logging.debug(
                'Chat Completions API request - model: %s, temperature: %s, max_tokens: %s',
                actual_model,
                create_kwargs.get('temperature'),
                create_kwargs.get('max_tokens'),
            )

            completion = await self.client.chat.completions.create(**create_kwargs)
            content = completion.choices[0].message.content

            logging.debug(f'Chat Completions API response received, length: {len(content) if content else 0}')
            content = self._clean_response(content)
            return content

        except Exception as e:
            error_msg = f"Chat Completions API request failed for model '{model}': {str(e)}"
            logging.error(error_msg)
            raise ValueError(error_msg)

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
            await self.client.aclose()
            self.client = None
