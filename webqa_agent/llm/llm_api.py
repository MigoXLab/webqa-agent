import logging

import httpx
from openai import AsyncOpenAI


class LLMAPI:
    def __init__(self, llm_config) -> None:
        self.llm_config = llm_config
        self.api_type = self.llm_config.get("api")
        self.model = self.llm_config.get("model")
        self.filter_model = self.llm_config.get("filter_model", self.model)  # For two-stage architecture
        self.client = None
        self._client = None  # httpx client

    async def initialize(self):
        if self.api_type == "openai":
            self.api_key = self.llm_config.get("api_key")
            if not self.api_key:
                raise ValueError("API key is empty. OpenAI client not initialized.")
            self.base_url = self.llm_config.get("base_url")
            # Use AsyncOpenAI client for async operations
            self.client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url, timeout=60) if self.base_url else AsyncOpenAI(
                api_key=self.api_key, timeout=360)
            logging.debug(f"AsyncOpenAI client initialized with API key: {self.api_key}, Model: {self.model} and base URL: {self.base_url}")
        else:
            raise ValueError("Invalid API type or missing credentials. LLM client not initialized.")

        return self

    async def _get_client(self):
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=60.0)
        return self._client

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
        """Get LLM response with support for GPT-5 reasoning parameters.
        
        Args:
            system_prompt: System prompt for the model
            prompt: User prompt
            images: Optional base64 image(s) for vision models
            temperature: Sampling temperature (0-2). Note: Only supported with GPT-5.1 when reasoning_effort="none"
            top_p: Nucleus sampling parameter. Note: Only supported with GPT-5.1 when reasoning_effort="none"
            max_tokens: Maximum output tokens
            model_override: Temporary model override (e.g., for two-stage architecture)
            reasoning: Reasoning effort control. Can be:
                - dict: {"effort": "none"|"low"|"medium"|"high"}
                - str: "none"|"low"|"medium"|"high"
                - None: Uses config or defaults ("none" for gpt-5.1, "low" for others)
            text: Output verbosity control. Can be:
                - dict: {"verbosity": "low"|"medium"|"high"}
                - str: "low"|"medium"|"high"
                - None: Uses config or defaults to "medium"
        
        Returns:
            str: Model response content
            
        Note:
            - GPT-5.1 supports reasoning_effort="none" for low-latency responses
            - Other reasoning models (o3, o4, etc.) default to "low" and support low/medium/high
            - Temperature/top_p are automatically disabled for GPT-5.1 when reasoning_effort != "none"
        """
        # Allow temporary model override for two-stage architecture (e.g., lightweight model for filtering)
        actual_model = model_override or self.model
        model_input = {"model": actual_model, "api_type": self.api_type}
        if self.api_type == "openai" and self.client is None:
            await self.initialize()

        try:
            messages = self._create_messages(system_prompt, prompt)
            # Handle images
            if images and self.api_type == "openai":
                self._handle_images_openai(messages, images)
                model_input["images"] = "included"
            # Choose and call API
            if self.api_type == "openai":
                # Resolve parameters: method args > config > defaults
                resolved_temperature = temperature if temperature is not None else self.llm_config.get("temperature", 0.1)
                resolved_top_p = top_p if top_p is not None else self.llm_config.get("top_p")
                resolved_max_tokens = max_tokens if max_tokens is not None else self.llm_config.get("max_tokens")
                
                # Resolve GPT-5 parameters (only for gpt-5/gpt-5.1 series)
                model_lower = actual_model.lower() if actual_model else ""
                is_gpt5_family = model_lower.startswith("gpt-5")
                is_gpt51 = model_lower.startswith("gpt-5.1")
                
                # Only apply reasoning/verbosity for GPT-5 family models
                resolved_reasoning_effort = None
                resolved_verbosity = None
                
                if is_gpt5_family:
                    # GPT-5.1 defaults to "none" (low-latency), GPT-5 defaults to "low"
                    default_reasoning = "none" if is_gpt51 else "low"
                    resolved_reasoning_effort = self._resolve_param(reasoning, "reasoning", "effort", default_reasoning)
                    resolved_verbosity = self._resolve_param(text, "text", "verbosity", "medium")

                    # GPT-5.1 compatibility: temperature/top_p only allowed when reasoning_effort=none
                    if is_gpt51 and resolved_reasoning_effort not in ["none", None]:
                        if resolved_temperature is not None or resolved_top_p is not None:
                            logging.warning(
                                "GPT-5.1 with reasoning_effort=%s: removing temperature/top_p (only allowed with 'none')",
                                resolved_reasoning_effort
                            )
                            resolved_temperature = None
                            resolved_top_p = None

                logging.debug(
                    "Resolved params - temperature: %s, top_p: %s, max_tokens: %s, reasoning_effort: %s, verbosity: %s",
                    resolved_temperature, resolved_top_p, resolved_max_tokens,
                    resolved_reasoning_effort, resolved_verbosity
                )
                
                result = await self._call_openai(
                    messages,
                    temperature=resolved_temperature,
                    top_p=resolved_top_p,
                    max_tokens=resolved_max_tokens,
                    model=actual_model,
                    reasoning_effort=resolved_reasoning_effort,
                    verbosity=resolved_verbosity,
                )

            return result
        except Exception as e:
            logging.error(f"LLMAPI.get_llm_response encountered error: {e}")
            raise

    def _create_messages(self, system_prompt, prompt):
        if self.api_type == "openai":
            return [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": [{"type": "text", "text": prompt}]},
            ]
        else:
            raise ValueError("Invalid api_type. Choose 'openai'.")

    def _handle_images_openai(self, messages, images):
        """Helper to append image data to messages for OpenAI."""
        try:
            if isinstance(images, str):
                if images.startswith("data:image"):
                    image_message = {"type": "image_url", "image_url": {"url": f"{images}", "detail": "low"}}
                    messages[1]["content"].append(image_message)
            elif isinstance(images, list):
                for image_base64 in images:
                    image_message = {"type": "image_url", "image_url": {"url": f"{image_base64}", "detail": "low"}}
                    messages[1]["content"].append(image_message)
            else:
                raise ValueError("Invalid type for 'images'. Expected a base64 string or a list of base64 strings.")
        except Exception as e:
            logging.error(f"Error while handling images for OpenAI: {e}")
            raise ValueError(f"Failed to process images for OpenAI. Error: {e}")

    def _resolve_param(self, override, config_key, sub_key, default):
        """Generic parameter resolver: override > config[key][sub_key] > config[sub_key] > default."""
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
        
        # Check config flat key (e.g., config.reasoning_effort)
        flat_key = f"{config_key}_{sub_key}" if config_key != sub_key else sub_key
        value = self.llm_config.get(flat_key)
        if value:
            return value
        
        return default

    async def _call_openai(
        self,
        messages,
        temperature=None,
        top_p=None,
        max_tokens=None,
        model=None,
        reasoning_effort=None,
        verbosity=None,
    ):
        try:
            # Use provided model or fallback to config model
            actual_model = model or self.llm_config.get("model")

            create_kwargs = {
                "model": actual_model,
                "messages": messages,
                "timeout": 360,
            }
            # Always send user/configured temperature when provided (default handled upstream)
            if temperature is not None:
                create_kwargs["temperature"] = temperature
            if top_p is not None:
                create_kwargs["top_p"] = top_p
            if max_tokens is not None:
                create_kwargs["max_tokens"] = max_tokens
            if reasoning_effort is not None:
                create_kwargs["reasoning_effort"] = reasoning_effort
            if verbosity is not None:
                create_kwargs["verbosity"] = verbosity

            # Log all request parameters for debugging
            logging.debug(
                "LLM API request - model: %s, temperature: %s, top_p: %s, max_tokens: %s, reasoning_effort: %s, verbosity: %s",
                actual_model,
                create_kwargs.get("temperature"),
                create_kwargs.get("top_p"),
                create_kwargs.get("max_tokens"),
                create_kwargs.get("reasoning_effort"),
                create_kwargs.get("verbosity")
            )

            completion = await self.client.chat.completions.create(**create_kwargs)
            content = completion.choices[0].message.content
            logging.debug(f"LLM API response: {content}")
            # Clean response if it's wrapped in JSON code blocks
            content = self._clean_response(content)
            return content
        except Exception as e:
            error_msg = f"LLM API request failed for model '{actual_model}' {str(e)}"
            logging.error(error_msg)
            logging.error(f"Request parameters: {create_kwargs.get('model')}, temperature={create_kwargs.get('temperature')}, reasoning_effort={create_kwargs.get('reasoning_effort')}, verbosity={create_kwargs.get('verbosity')}")
            raise ValueError(error_msg)

    def _clean_response(self, response):
        """Remove JSON code block markers from the response if present."""
        try:
            if response and isinstance(response, str):
                # Check if response starts with ```json and ends with ```
                if response.startswith("```json") and response.endswith("```"):
                    # Remove the markers and return the content
                    logging.debug("Cleaning response: Removing ```json``` markers")
                    return response[7:-3].strip()
                # Check if it just has ``` without json specification
                elif response.startswith("```") and response.endswith("```"):
                    logging.debug("Cleaning response: Removing ``` markers")
                    return response[3:-3].strip()

                # Encode response as UTF-8
                response = response.encode("utf-8").decode("utf-8")
            return response
        except Exception as e:
            logging.error(f"Error while cleaning response: {e}")
            logging.error(f"Original response: {response}")
            return response

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
