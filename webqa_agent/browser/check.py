import json
from datetime import datetime

from playwright.async_api import Page


class NetworkCheck:
    def __init__(self, page: Page):
        self.page = page
        self.network_messages = {"failed_requests": [], "responses": [], "requests": []}
        self._response_callback = self._handle_response()
        self._request_callback = self._handle_request()
        self._requestfinished_callback = self._handle_request_finished()
        self._setup_listeners()

    def _setup_listeners(self):
        # 1. listen to request
        self.page.on("request", self._request_callback)
        # 2. listen to response
        self.page.on("response", self._response_callback)
        # 3. listen to request finished
        self.page.on("requestfinished", self._requestfinished_callback)

    def _handle_request(self):
        async def request_callback(request):
            request_data = {
                "url": request.url,
                "method": request.method,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
                "has_response": False,
                "completed": False,
                "failed": False,
                "is_sse": False,
                "sse_messages": [],  # list for storing SSE messages
            }
            self.network_messages["requests"].append(request_data)

        return request_callback

    def _handle_response(self):
        async def response_callback(response):
            response_url = response.url
            try:
                current_request = None
                for request in self.network_messages["requests"]:
                    if request["url"] == response_url:
                        request["has_response"] = True
                        current_request = request
                        break

                if not current_request:
                    return

                # Get response headers
                try:
                    headers = await response.all_headers()
                    content_type = headers.get("content-type", "")
                except Exception:
                    # logging.warning(f"Unable to get headers for {response_url}: {str(e)}")
                    content_type = ""
                    headers = {}

                # Create response data structure
                response_data = {
                    "url": response_url,
                    "status": response.status,
                    "method": response.request.method,
                    "content_type": content_type,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
                    "headers": headers,  # 保存响应头信息
                    "sse_messages": [],
                }

                if response.status >= 400:
                    response_data["error"] = f"HTTP {response.status}"
                    self.network_messages["responses"].append(response_data)
                    return

                if "text/event-stream" in content_type:
                    current_request["is_sse"] = True
                    response_data["is_sse"] = True

                    try:
                        response_data["sse_pending"] = True
                    except Exception as e:
                        response_data["error"] = str(e)

                else:
                    try:
                        if any(
                            bin_type in content_type.lower()
                            for bin_type in [
                                "image/",
                                "audio/",
                                "video/",
                                "application/pdf",
                                "application/octet-stream",
                                "font/",
                                "application/x-font",
                            ]
                        ):
                            response_data["body"] = f"<{content_type} binary data>"
                            response_data["size"] = len(await response.body())

                        elif "application/json" in content_type:
                            try:
                                body = await response.json()
                                response_data["body"] = body
                            except Exception as e:
                                response_data["error"] = f"JSON parse error: {str(e)}"

                        elif any(
                            text_type in content_type.lower()
                            for text_type in [
                                "text/",
                                "application/javascript",
                                "application/xml",
                                "application/x-www-form-urlencoded",
                            ]
                        ):
                            try:
                                text_body = await response.text()
                                response_data["body"] = text_body
                            except Exception as e:
                                response_data["error"] = f"Text decode error: {str(e)}"

                        else:
                            response_data["body"] = f"<{content_type} data>"
                            response_data["size"] = len(await response.body())

                    except Exception as e:
                        response_data["error"] = str(e)

                self.network_messages["responses"].append(response_data)

            except Exception:
                pass

        return response_callback

    def _parse_sse_chunk(self, chunk):
        """Parse SSE data chunk."""
        messages = []
        current_message = {}

        for line in chunk.split("\n"):
            line = line.strip()
            if not line:
                if current_message:
                    messages.append(current_message)
                    current_message = {}
                continue

            if line.startswith("data:"):
                data = line[5:].strip()
                try:
                    # try to parse JSON data
                    json_data = json.loads(data)
                    if "data" not in current_message:
                        current_message["data"] = json_data
                    else:
                        # if there is data, append new data to existing data
                        if isinstance(current_message["data"], list):
                            current_message["data"].append(json_data)
                        else:
                            current_message["data"] = [current_message["data"], json_data]
                except json.JSONDecodeError:
                    if "data" not in current_message:
                        current_message["data"] = data
                    else:
                        current_message["data"] += "\n" + data
        if current_message:
            messages.append(current_message)

        return messages

    def _handle_request_finished(self):
        async def request_finished_callback(request):
            try:
                response = await request.response()
                if not response:
                    # logging.warning(f"No response object for request: {request.url}")
                    return
                # logging.debug(f"Response object for request: {request.url}")
                for req in self.network_messages["requests"]:
                    if req["url"] == request.url:
                        req["completed"] = True

                        if req.get("is_sse"):
                            try:
                                body = await response.body()
                                text = body.decode("utf-8", errors="replace")

                                # handle SSE messages
                                messages = []

                                # process SSE data by line
                                for line in text.split("\n"):
                                    if not line:
                                        continue

                                    if not line.startswith("data:"):
                                        continue

                                    # extract data content
                                    sse_data = line[5:].strip()  # remove 'data:' prefix
                                    if not sse_data:
                                        continue

                                    try:
                                        # parse JSON data
                                        json_data = json.loads(sse_data)
                                        messages.append(
                                            {
                                                "data": json_data,
                                            }
                                        )
                                    except json.JSONDecodeError:
                                        # if not JSON, store original text
                                        messages.append(
                                            {
                                                "data": sse_data,
                                            }
                                        )

                                req["sse_messages"] = messages

                                for resp in self.network_messages["responses"]:
                                    if resp["url"] == request.url:
                                        resp["sse_messages"] = messages
                                        resp["sse_completed"] = True
                                        break

                            except Exception:
                                pass
                        break

            except Exception:
                pass

        return request_finished_callback

    def get_messages(self):
        return self.network_messages

    def _on_request_failed(self, request):
        # find and update request status
        for req in self.network_messages["requests"]:
            if req["url"] == request.url:
                req["failed"] = True
                break

        error_data = {"url": request.url, "error": request.failure}
        self.network_messages["failed_requests"].append(error_data)

    def remove_listeners(self):
        # Prefer Playwright's off() which understands internal wrapper mapping
        listeners = [
            ("request", self._request_callback),
            ("response", self._response_callback),
            ("requestfinished", self._requestfinished_callback),
        ]
        for event_name, handler in listeners:
            try:
                if hasattr(self.page, "off"):
                    self.page.off(event_name, handler)
                else:
                    # Fallback for environments exposing remove_listener
                    self.page.remove_listener(event_name, handler)
            except Exception:
                # Silently ignore if already removed or not found
                pass


class ConsoleCheck:
    def __init__(self, page):
        self.page = page
        self.console_messages = []
        self._setup_listeners()

    def _setup_listeners(self):
        self.page.on("console", self._handle_console)

    def _handle_console(self, msg):
        if msg.type == "error":
            error_message = msg.text
            error_location = getattr(msg, "location", None)
            self.console_messages.append({"msg": error_message, "location": error_location})

    def get_messages(self):
        return self.console_messages

    def remove_listeners(self):
        try:
            if hasattr(self.page, "off"):
                self.page.off("console", self._handle_console)
            else:
                self.page.remove_listener("console", self._handle_console)
        except Exception:
            pass
