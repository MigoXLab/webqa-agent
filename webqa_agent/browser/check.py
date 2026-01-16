import json
import re
from typing import Dict, List, Optional

from playwright.async_api import Page


class IgnoreRuleMatcher:
    """Helper class to match ignore rules with patterns."""

    @staticmethod
    def should_ignore_network(url: str, ignore_rules: Optional[List[Dict]] = None) -> bool:
        """Check if a network request URL should be ignored.

        Args:
            url: The URL to check
            ignore_rules: List of ignore rules with pattern and type

        Returns:
            True if the URL should be ignored, False otherwise
        """
        if not ignore_rules:
            return False

        for rule in ignore_rules:
            pattern = rule.get('pattern', '')
            rule_type = rule.get('type', 'url')

            if not pattern:
                continue

            try:
                if rule_type == 'domain':
                    # Match domain in URL
                    if re.search(pattern, url, re.IGNORECASE):
                        return True
                elif rule_type == 'url':
                    # Match full URL
                    if re.search(pattern, url, re.IGNORECASE):
                        return True
            except re.error:
                # Invalid regex pattern, skip
                continue

        return False

    @staticmethod
    def should_ignore_console(message: str, ignore_rules: Optional[List[Dict]] = None) -> bool:
        """Check if a console error message should be ignored.

        Args:
            message: The console error message to check
            ignore_rules: List of ignore rules with pattern and match_type

        Returns:
            True if the message should be ignored, False otherwise
        """
        if not ignore_rules:
            return False

        for rule in ignore_rules:
            pattern = rule.get('pattern', '')
            match_type = rule.get('match_type', 'contains')

            if not pattern:
                continue

            try:
                if match_type == 'regex':
                    # Use regex matching
                    if re.search(pattern, message, re.IGNORECASE):
                        return True
                elif match_type == 'contains':
                    # Simple substring matching
                    if pattern.lower() in message.lower():
                        return True
            except re.error:
                # Invalid regex pattern, skip
                continue

        return False


class NetworkCheck:
    MAX_BODY_BYTES = 5 * 1024  # 5KB limit for stored bodies

    def __init__(self, page: Page, ignore_rules: Optional[List[Dict]] = None):
        self.page = page
        self.ignore_rules = ignore_rules or []
        self.network_messages = {'failed_requests': [], 'responses': [], 'requests': []}
        self._response_callback = self._handle_response()
        self._request_callback = self._handle_request()
        self._requestfinished_callback = self._handle_request_finished()
        self._setup_listeners()

    def _setup_listeners(self):
        # 1. listen to request
        self.page.on('request', self._request_callback)
        # 2. listen to response
        self.page.on('response', self._response_callback)
        # 3. listen to request finished
        self.page.on('requestfinished', self._requestfinished_callback)

    def _handle_request(self):
        async def request_callback(request):
            # Get request payload
            request_payload = None
            try:
                post_data = request.post_data
                if post_data:
                    # Try to parse as JSON
                    try:
                        request_payload = json.loads(post_data)
                    except:
                        # If not JSON, save as string
                        request_payload = post_data
            except:
                pass

            request_data = {
                'url': request.url,
                'method': request.method,
                'payload': self._truncate_payload(request_payload),
                'completed': False,
                'failed': False,
            }
            self.network_messages['requests'].append(request_data)

        return request_callback

    def _sanitize_content(self, data):
        """Recursively remove large code blocks (```...```) and sanitize
        data."""
        if isinstance(data, str):
            # Regex to match markdown code blocks (```any_lang ... ```)
            # We replace them with a placeholder to save space
            code_block_pattern = r'```[\s\S]*?```'
            if re.search(code_block_pattern, data):
                data = re.sub(code_block_pattern, '<Code block omitted>', data)
            return data
        elif isinstance(data, list):
            return [self._sanitize_content(item) for item in data]
        elif isinstance(data, dict):
            return {k: self._sanitize_content(v) for k, v in data.items()}
        return data

    def _truncate_payload(self, payload):
        """Trim request payload to keep monitoring data lightweight."""
        if payload is None:
            return None
        try:
            if isinstance(payload, (dict, list)):
                text = json.dumps(payload, ensure_ascii=False)[: self.MAX_BODY_BYTES]
                if len(text) >= self.MAX_BODY_BYTES:
                    text += '... [payload truncated]'
                return text
            text = str(payload)
            if len(text) > self.MAX_BODY_BYTES:
                return text[: self.MAX_BODY_BYTES] + '... [payload truncated]'
            return text
        except Exception:
            return '<payload truncated>'

    def _truncate_body(self, body_bytes: bytes, content_type: str) -> str:
        """Trim response body to 5KB and sanitize."""
        if not body_bytes:
            return ''

        max_len = self.MAX_BODY_BYTES
        size = len(body_bytes)
        slice_bytes = body_bytes[:max_len]

        try:
            text = slice_bytes.decode('utf-8', errors='replace')
        except Exception:
            text = str(slice_bytes)

        text = self._sanitize_content(text)
        if size > max_len:
            text += f'\n... [body truncated to {max_len} bytes from {size}]'
        return text

    def _handle_response(self):
        async def response_callback(response):
            response_url = response.url

            # Check if this URL should be ignored
            if IgnoreRuleMatcher.should_ignore_network(response_url, self.ignore_rules):
                return

            try:
                current_request = None
                for request in self.network_messages['requests']:
                    if request['url'] == response_url:
                        current_request = request
                        break

                if not current_request:
                    return

                # Get response headers
                try:
                    headers = await response.all_headers()
                    content_type = headers.get('content-type', '')
                except Exception:
                    # logging.warning(f"Unable to get headers for {response_url}: {str(e)}")
                    content_type = ''
                    headers = {}

                response_data = {
                    'url': response_url,
                    'status': response.status,
                    'method': response.request.method,
                    'content_type': content_type,
                    'payload': current_request.get('payload'),
                }

                if response.status >= 400:
                    response_data['error'] = f'HTTP {response.status}'
                    self.network_messages['responses'].append(response_data)
                    return

                try:
                    ct_lower = content_type.lower()
                    if 'text/event-stream' in ct_lower:
                        response_data['body'] = '<event-stream omitted>'
                    elif any(
                        asset_type in ct_lower
                        for asset_type in [
                            'image/',
                            'audio/',
                            'video/',
                            'application/pdf',
                            'application/octet-stream',
                            'font/',
                            'application/x-font',
                            'application/javascript',
                            'application/x-javascript',
                            'text/javascript',
                            'text/css',
                        ]
                    ):
                        response_data['body'] = f'<{content_type} asset omitted>'
                    else:
                        body_bytes = await response.body()
                        response_data['body'] = self._truncate_body(body_bytes, content_type)
                except Exception as e:
                    response_data['error'] = str(e)

                self.network_messages['responses'].append(response_data)

            except Exception:
                pass

        return response_callback

    def _parse_sse_chunk(self, chunk):
        """Parse SSE data chunk."""
        messages = []
        current_message = {}

        for line in chunk.split('\n'):
            line = line.strip()
            if not line:
                if current_message:
                    messages.append(current_message)
                    current_message = {}
                continue

            if line.startswith('data:'):
                data = line[5:].strip()
                try:
                    # try to parse JSON data
                    json_data = json.loads(data)
                    if 'data' not in current_message:
                        current_message['data'] = json_data
                    else:
                        # if there is data, append new data to existing data
                        if isinstance(current_message['data'], list):
                            current_message['data'].append(json_data)
                        else:
                            current_message['data'] = [current_message['data'], json_data]
                except json.JSONDecodeError:
                    if 'data' not in current_message:
                        current_message['data'] = data
                    else:
                        current_message['data'] += '\n' + data
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
                for req in self.network_messages['requests']:
                    if req['url'] == request.url:
                        req['completed'] = True
                        break

            except Exception:
                pass

        return request_finished_callback

    def get_messages(self):
        return self.network_messages

    def _on_request_failed(self, request):
        # find and update request status
        request_payload = None
        for req in self.network_messages['requests']:
            if req['url'] == request.url:
                req['failed'] = True
                request_payload = req.get('payload')
                break

        error_data = {
            'url': request.url,
            'error': request.failure,
            'method': request.method,
            'payload': request_payload
        }
        self.network_messages['failed_requests'].append(error_data)

    def remove_listeners(self):
        # Prefer Playwright's off() which understands internal wrapper mapping
        listeners = [
            ('request', self._request_callback),
            ('response', self._response_callback),
            ('requestfinished', self._requestfinished_callback),
        ]
        for event_name, handler in listeners:
            try:
                if hasattr(self.page, 'off'):
                    self.page.off(event_name, handler)
                else:
                    # Fallback for environments exposing remove_listener
                    self.page.remove_listener(event_name, handler)
            except Exception:
                # Silently ignore if already removed or not found
                pass


class ConsoleCheck:
    def __init__(self, page, ignore_rules: Optional[List[Dict]] = None):
        self.page = page
        self.ignore_rules = ignore_rules or []
        self.console_messages = []
        self.ignored_console_messages = []
        self._setup_listeners()

    def _setup_listeners(self):
        self.page.on('console', self._handle_console)

    def _handle_console(self, msg):
        if msg.type == 'error':
            error_message = msg.text
            error_location = getattr(msg, 'location', None)

            # Check if this console error should be ignored
            if IgnoreRuleMatcher.should_ignore_console(error_message, self.ignore_rules):
                self.ignored_console_messages.append({
                    'msg': error_message,
                    'location': error_location,
                    'ignored': True
                })
                return

            self.console_messages.append({'msg': error_message, 'location': error_location})

    def get_messages(self):
        return self.console_messages

    def get_ignored_messages(self):
        """Get list of ignored console messages for debugging."""
        return self.ignored_console_messages

    def remove_listeners(self):
        try:
            if hasattr(self.page, 'off'):
                self.page.off('console', self._handle_console)
            else:
                self.page.remove_listener('console', self._handle_console)
        except Exception:
            pass
