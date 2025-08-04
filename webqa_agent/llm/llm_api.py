from openai import OpenAI, AsyncOpenAI
import httpx
import asyncio
from webqa_agent.utils.get_log import GetLog
import logging


class LLMAPI:
    def __init__(self, llm_config) -> None:
        self.llm_config = llm_config
        self.api_type = self.llm_config.get("api")
        self.model = self.llm_config.get("model")
        self.client = None
        self._client = None  # httpx client
        
    async def initialize(self):
        if self.api_type == "openai":
            self.api_key = self.llm_config.get("api_key")
            if not self.api_key:
                raise ValueError("API key is empty. OpenAI client not initialized.")
            self.base_url = self.llm_config.get("base_url")
            # Use AsyncOpenAI client for async operations
            self.client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url) if self.base_url else AsyncOpenAI(
                api_key=self.api_key)
            logging.info(f"AsyncOpenAI client initialized with API key: {self.api_key}, Model: {self.model} and base URL: {self.base_url}")
        else:
            raise ValueError(
                "Invalid API type or missing credentials. LLM client not initialized.")
        
        return self

    async def _get_client(self):
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=60.0)
        return self._client

    async def get_llm_response(self, system_prompt, prompt, images=None, images_path=None):
        model_input = {
            "model": self.model,
            "api_type": self.api_type
        }
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
                result = await self._call_openai(messages)
            
            return result
        except Exception as e:
            logging.error(f"LLMAPI.get_llm_response encountered error: {e}")
            raise

    def _create_messages(self, system_prompt, prompt):
        if self.api_type == "openai":
            return [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": [{"type": "text", "text": prompt}]}
            ]
        else:
            raise ValueError("Invalid api_type. Choose 'openai'.")

    def _handle_images_openai(self, messages, images):
        """Helper to append image data to messages for OpenAI."""
        try:
            if isinstance(images, str):
                if images.startswith('data:image'):
                    image_message = {"type": "image_url", "image_url": {"url": f"{images}", "detail": "low"}}
                    messages[1]["content"].append(image_message)
            elif isinstance(images, list):
                for image_base64 in images:
                    image_message = {"type": "image_url",
                                     "image_url": {"url": f"{image_base64}", "detail": "low"}}
                    messages[1]["content"].append(image_message)
            else:
                raise ValueError("Invalid type for 'images'. Expected a base64 string or a list of base64 strings.")
        except Exception as e:
            logging.error(f"Error while handling images for OpenAI: {e}")
            raise ValueError(f"Failed to process images for OpenAI. Error: {e}")

    async def _call_openai(self, messages):
        try:
            completion = await self.client.chat.completions.create(
                model=self.llm_config.get("model"),
                messages=messages,
                timeout=60,  # adjustable
                temperature=0.0
            )
            content = completion.choices[0].message.content
            # Clean response if it's wrapped in JSON code blocks
            content = self._clean_response(content)
            return content
        except Exception as e:
            logging.error(f"Error while calling OpenAI API: {e}")
            raise ValueError(f"{str(e)}")

    def _clean_response(self, response):
        """Remove JSON code block markers from the response if present."""
        try:
            if response and isinstance(response, str):
                # Check if response starts with ```json and ends with ```
                if response.startswith("```json") and response.endswith("```"):
                    # Remove the markers and return the content
                    logging.info(f"Cleaning response: Removing ```json``` markers")
                    return response[7:-3].strip()
                # Check if it just has ``` without json specification
                elif response.startswith("```") and response.endswith("```"):
                    logging.info(f"Cleaning response: Removing ``` markers")
                    return response[3:-3].strip()
                
                # Encode response as UTF-8
                response = response.encode('utf-8').decode('utf-8')
            return response
        except Exception as e:
            logging.error(f"Error while cleaning response: {e}")
            logging.error(f"Original response: {response}")
            return response
    
    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
