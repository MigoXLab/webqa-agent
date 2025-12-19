import asyncio
import inspect
import logging
from typing import Dict, List, Optional

from webqa_agent.actions.action_handler import action_context_var


class ActionExecutor:
    def __init__(self, action_handler):
        self._actions = action_handler
        self._action_map = {
            'Tap': self._execute_tap,
            'Hover': self._execute_hover,
            'Sleep': self._execute_sleep,
            'Input': self._execute_input,
            'Clear': self._execute_clear,
            'Scroll': self._execute_scroll,
            'KeyboardPress': self._execute_keyboard_press,
            'Upload': self._execute_upload,
            'SelectDropdown': self._execute_select_dropdown,
            'Drag': self._execute_drag,
            'GoToPage': self._execute_go_to_page,  # Added missing action
            'GoBack': self._execute_go_back,  # Added browser back navigation
            'Mouse': self._execute_mouse, # Added mouse action
        }

    async def initialize(self):
        return self

    async def execute(self, action):
        try:
            # Validate the action
            action_type = action.get('type')
            if not action_type:
                logging.error('Action type is required')
                return False

            # Get the corresponding execution function
            execute_func = self._action_map.get(action_type)
            if not execute_func:
                logging.error(f'Unknown action type: {action_type}')
                return False

            # Execute the action with introspection to handle different method signatures
            logging.debug(f'Executing action: {action_type}')

            # Use introspection to check if method accepts action parameter
            sig = inspect.signature(execute_func)
            params = list(sig.parameters.keys())

            # If method only has 'self' parameter (no additional params), call without action
            # Note: bound methods don't show 'self' in signature, so empty params means no action param
            if len(params) == 0:
                logging.debug(f'Calling {action_type} without action parameter (method signature has no parameters)')
                return await execute_func()
            else:
                return await execute_func(action)

        except Exception as e:
            logging.error(f'Action execution failed: {str(e)}')
            return {'success': False, 'message': f'Action execution failed with an exception: {e}'}

    def _validate_params(self, action, required_params):
        for param in required_params:
            keys = param.split('.')
            value = action
            for key in keys:
                value = value.get(key)
                if value is None:
                    logging.error(f'Missing required parameter: {param}')
                    return False  # Return False to indicate validation failure
        return True  # Return True if all parameters are present

    # Individual action execution methods - NO SCREENSHOTS
    async def _execute_clear(self, action):
        """Execute clear action on an input field."""
        if not self._validate_params(action, ['locate.id']):
            return {'success': False, 'message': 'Missing locate.id for clear action'}

        success = await self._actions.clear(action.get('locate').get('id'))

        # Read action context for detailed error information
        ctx = action_context_var.get()

        if success:
            return {'success': True, 'message': 'Clear action successful.'}
        else:
            # Enrich error message with context
            base_message = 'Clear action failed.'
            error_details = {}

            if ctx and ctx.error_type:
                error_details = {
                    'error_type': ctx.error_type,
                    'error_reason': ctx.error_reason,
                    'attempted_strategies': ctx.attempted_strategies,
                    'element_info': ctx.element_info,
                    'playwright_error': ctx.playwright_error
                }

                # Make message more specific based on error type
                if ctx.error_type == 'element_not_found':
                    base_message = 'Clear failed: Element not found on page.'
                elif ctx.error_type == 'element_not_typeable':
                    base_message = 'Clear failed: Element cannot be cleared.'
                elif ctx.error_type == 'playwright_error':
                    base_message = 'Clear failed: Browser interaction error.'
            else:
                base_message = 'Clear action failed. The element might not be clearable.'

            return {
                'success': False,
                'message': base_message,
                'error_details': error_details
            }

    async def _execute_tap(self, action):
        """Execute tap/click action."""
        if not self._validate_params(action, ['locate.id']):
            return {'success': False, 'message': 'Missing locate.id for tap action'}

        success = await self._actions.click(action.get('locate').get('id'))

        # Read action context for detailed error information
        ctx = action_context_var.get()

        if success:
            return {'success': True, 'message': 'Tap action successful.'}
        else:
            # Enrich error message with context
            base_message = 'Tap action failed.'
            error_details = {}

            if ctx and ctx.error_type:
                error_details = {
                    'error_type': ctx.error_type,
                    'error_reason': ctx.error_reason,
                    'attempted_strategies': ctx.attempted_strategies,
                    'element_info': ctx.element_info,
                    'playwright_error': ctx.playwright_error
                }

                # Make message more specific based on error type
                if ctx.error_type == 'scroll_failed':
                    base_message = f'Tap failed: Could not scroll element into viewport after {ctx.scroll_attempts} attempts.'
                elif ctx.error_type == 'scroll_timeout_lazy_loading':
                    base_message = f'Tap failed: Element viewport positioning succeeded but page content unstable after {ctx.scroll_attempts} attempts.'
                elif ctx.error_type == 'element_not_found':
                    base_message = f'Tap failed: Element not found on page.'
                elif ctx.error_type == 'element_not_clickable':
                    base_message = f'Tap failed: Element exists but is not clickable.'
                elif ctx.error_type == 'playwright_error':
                    base_message = f'Tap failed: Browser interaction error.'
            else:
                base_message = 'Tap action failed. The element might not be clickable.'

            return {
                'success': False,
                'message': base_message,
                'error_details': error_details  # NEW: additional metadata, won't break existing consumers
            }

    async def _execute_hover(self, action):
        """Execute hover action."""
        if not self._validate_params(action, ['locate.id']):
            return {'success': False, 'message': 'Missing locate.id for hover action'}

        success = await self._actions.hover(action.get('locate').get('id'))

        # Read action context for detailed error information
        ctx = action_context_var.get()

        if success:
            return {'success': True, 'message': 'Hover action successful.'}
        else:
            # Enrich error message with context
            base_message = 'Hover action failed.'
            error_details = {}

            if ctx and ctx.error_type:
                error_details = {
                    'error_type': ctx.error_type,
                    'error_reason': ctx.error_reason,
                    'attempted_strategies': ctx.attempted_strategies,
                    'element_info': ctx.element_info,
                    'playwright_error': ctx.playwright_error
                }

                # Make message more specific based on error type
                if ctx.error_type == 'scroll_failed':
                    base_message = f'Hover failed: Could not scroll element into viewport after {ctx.scroll_attempts} attempts.'
                elif ctx.error_type == 'element_not_found':
                    base_message = f'Hover failed: Element not found on page or missing coordinates.'
                elif ctx.error_type == 'playwright_error':
                    base_message = f'Hover failed: Browser interaction error.'
            else:
                base_message = 'Hover action failed. The element might not be hoverable.'

            return {
                'success': False,
                'message': base_message,
                'error_details': error_details
            }

    async def _execute_sleep(self, action):
        """Execute sleep/wait action."""
        if not self._validate_params(action, ['param.timeMs']):
            return {'success': False, 'message': 'Missing param.timeMs for sleep action'}
        time_ms = action.get('param').get('timeMs')
        await asyncio.sleep(time_ms / 1000)
        return {'success': True, 'message': f'Slept for {time_ms}ms.'}

    async def _execute_input(self, action):
        """Execute input/type action."""
        if not self._validate_params(action, ['locate.id', 'param.value']):
            return {'success': False, 'message': 'Missing locate.id or param.value for input action'}
        try:
            value = action.get('param').get('value')
            clear_before_type = action.get('param').get('clear_before_type', False)  # Default is False
            success = await self._actions.type(
                action.get('locate').get('id'), value, clear_before_type=clear_before_type
            )

            # Read action context for detailed error information
            ctx = action_context_var.get()

            if success:
                return {'success': True, 'message': 'Input action successful.'}
            else:
                # Enrich error message with context
                base_message = 'Input action failed.'
                error_details = {}

                if ctx and ctx.error_type:
                    error_details = {
                        'error_type': ctx.error_type,
                        'error_reason': ctx.error_reason,
                        'attempted_strategies': ctx.attempted_strategies,
                        'element_info': ctx.element_info,
                        'playwright_error': ctx.playwright_error
                    }

                    # Make message more specific based on error type
                    if ctx.error_type == 'scroll_failed':
                        base_message = f'Input failed: Could not scroll element into viewport after {ctx.scroll_attempts} attempts.'
                    elif ctx.error_type == 'element_not_found':
                        base_message = f'Input failed: Element not found on page.'
                    elif ctx.error_type == 'element_not_typeable':
                        base_message = f'Input failed: Element exists but cannot accept text input.'
                    elif ctx.error_type == 'element_not_clickable':
                        base_message = f'Input failed: Could not focus element for typing.'
                    elif ctx.error_type == 'playwright_error':
                        base_message = f'Input failed: Browser interaction error.'
                else:
                    base_message = 'Input action failed. The element might not be available for typing.'

                return {
                    'success': False,
                    'message': base_message,
                    'error_details': error_details
                }
        except Exception as e:
            logging.error(f"Action '_execute_input' execution failed: {str(e)}")
            return {'success': False, 'message': f'Input action failed with an exception: {e}'}

    async def _execute_scroll(self, action):
        """Execute scroll action - scroll to a specific element."""
        if not self._validate_params(action, ['locate.id']):
            return {'success': False, 'message': 'Missing locate.id for scroll action. Scroll requires an element ID to scroll to.'}

        element_id = action.get('locate', {}).get('id')

        success = await self._actions.scroll(element_id)

        # Read action context for detailed error information
        ctx = action_context_var.get()

        if success:
            return {'success': True, 'message': f'Scrolled to element {element_id} successfully.'}
        else:
            # Enrich error message with context
            base_message = f'Scroll to element {element_id} failed.'
            error_details = {}

            if ctx and ctx.error_type:
                error_details = {
                    'error_type': ctx.error_type,
                    'error_reason': ctx.error_reason,
                    'attempted_strategies': ctx.attempted_strategies,
                    'element_info': ctx.element_info,
                    'playwright_error': ctx.playwright_error
                }

            return {
                'success': False,
                'message': base_message,
                'error_details': error_details
            }

    async def _execute_keyboard_press(self, action):
        """Execute keyboard press action."""
        if not self._validate_params(action, ['param.value']):
            return {'success': False, 'message': 'Missing param.value for keyboard press action'}

        success = await self._actions.keyboard_press(action.get('param').get('value'))

        # Read action context for detailed error information
        ctx = action_context_var.get()

        if success:
            return {'success': True, 'message': 'Keyboard press successful.'}
        else:
            # Enrich error message with context
            base_message = 'Keyboard press failed.'
            error_details = {}

            if ctx and ctx.error_type:
                error_details = {
                    'error_type': ctx.error_type,
                    'error_reason': ctx.error_reason,
                    'attempted_strategies': ctx.attempted_strategies,
                    'element_info': ctx.element_info,
                    'playwright_error': ctx.playwright_error
                }

                # Make message more specific based on error type
                if ctx.error_type == 'playwright_error':
                    base_message = 'Keyboard press failed: Browser interaction error.'
            else:
                base_message = 'Keyboard press failed.'

            return {
                'success': False,
                'message': base_message,
                'error_details': error_details
            }


    async def _execute_upload(self, action, file_path):
        """Execute upload action."""
        if not self._validate_params(action, ['locate.id']):
            return {'success': False, 'message': 'Missing locate.id for upload action'}

        success = await self._actions.upload_file(action.get('locate').get('id'), file_path)

        # Read action context for detailed error information
        ctx = action_context_var.get()

        if success:
            return {'success': True, 'message': 'File upload successful.'}
        else:
            # Enrich error message with context
            base_message = 'File upload failed.'
            error_details = {}

            if ctx and ctx.error_type:
                error_details = {
                    'error_type': ctx.error_type,
                    'error_reason': ctx.error_reason,
                    'attempted_strategies': ctx.attempted_strategies,
                    'element_info': ctx.element_info,
                    'playwright_error': ctx.playwright_error
                }

                # Make message more specific based on error type
                if ctx.error_type == 'file_upload_failed':
                    base_message = 'File upload failed: Operation error.'
                elif ctx.error_type == 'element_not_found':
                    base_message = 'File upload failed: No file input element found on page.'
                elif ctx.error_type == 'playwright_error':
                    base_message = 'File upload failed: Browser interaction error.'
            else:
                base_message = 'File upload failed.'

            return {
                'success': False,
                'message': base_message,
                'error_details': error_details
            }

    async def _execute_select_dropdown(self, action):
        """Execute select dropdown action."""
        locate = action.get('locate', {})
        dropdown_id = locate.get('dropdown_id')
        option_id = locate.get('option_id')
        selection_path_param = action.get('param', {}).get('selection_path')

        if dropdown_id is None or selection_path_param is None:
            logging.error('dropdown_id and selection_path are required for SelectDropdown')
            return {'success': False, 'message': 'dropdown_id and selection_path are required for SelectDropdown'}

        if isinstance(selection_path_param, str):
            selection_path = [selection_path_param]
        elif isinstance(selection_path_param, list) and selection_path_param:
            selection_path = selection_path_param
        else:
            logging.error('selection_path must be a non-empty string or list')
            return {'success': False, 'message': 'selection_path must be a non-empty string or list'}

        try:
            # choose option_id directly
            if option_id is not None and len(selection_path) == 1:
                logging.debug(f'Directly clicking option_id {option_id} for dropdown_id {dropdown_id}')
                return await self._actions.select_dropdown_option(dropdown_id, selection_path[0], option_id=option_id)

            # multi-level cascade or no option_id, use original logic
            if len(selection_path) == 1:
                return await self._execute_simple_selection(dropdown_id, selection_path[0])
            else:
                # multi-level cascade
                for level, option_text in enumerate(selection_path):
                    select_result = await self._actions.select_cascade_level(dropdown_id, option_text, level=level)
                    if not select_result.get('success'):
                        logging.error(f"Failed to select level {level} option: {select_result.get('message')}")
                        return {
                            'success': False,
                            'message': f"Failed at cascade level {level}: {select_result.get('message')}",
                        }
                    if level < len(selection_path) - 1:
                        await asyncio.sleep(0.5)
                logging.debug(f"Successfully completed cascade selection: {' -> '.join(selection_path)}")
                return {'success': True, 'message': 'Cascade selection completed successfully'}

        except Exception as e:
            logging.error(f'Error in dropdown selection: {str(e)}')
            return {'success': False, 'message': f'An exception occurred during dropdown selection: {str(e)}'}

    async def _execute_simple_selection(self, element_id, option_text):
        """Execute simple single-level dropdown selection."""
        try:
            # get all options of dropdown
            logging.debug(f'Getting dropdown options for element {element_id}')
            options_result = await self._actions.get_dropdown_options(element_id)

            if not options_result.get('success'):
                logging.error(f"Failed to get dropdown options: {options_result.get('message')}")
                return {'success': False, 'message': f"Failed to get dropdown options: {options_result.get('message')}"}

            options = options_result.get('options', [])
            if not options:
                logging.error('No options found in dropdown')
                return {'success': False, 'message': 'No options found in dropdown'}

            logging.debug(f'Found {len(options)} options in dropdown')

            # use default simple decision logic
            def _default_selection_logic(options: List[Dict], criteria: str) -> Optional[str]:
                criteria_lower = criteria.lower()

                for option in options:
                    if option['text'].lower() == criteria_lower:
                        logging.debug(f"Found exact match: {option['text']}")
                        return option['text']

                for option in options:
                    if criteria_lower in option['text'].lower():
                        logging.debug(f"Found contains match: {option['text']}")
                        return option['text']

                for option in options:
                    if option['text'].lower() in criteria_lower:
                        logging.debug(f"Found partial match: {option['text']}")
                        return option['text']

                # if no match, return None
                logging.warning(f'No match found for criteria: {criteria}')
                return None

            selected_option = _default_selection_logic(options, option_text)

            if not selected_option:
                logging.error(f'Could not decide which option to select based on criteria: {option_text}')
                available_options = [opt['text'] for opt in options]
                logging.debug(f'Available options: {available_options}')
                return {'success': False, 'message': 'No matching option found', 'available_options': available_options}

            logging.debug(f'Selected option: {selected_option}')

            # execute select operation
            select_result = await self._actions.select_dropdown_option(element_id, selected_option)

            if select_result.get('success'):
                logging.debug(f'Successfully completed dropdown selection: {selected_option}')
                return {'success': True, 'message': 'Option selected successfully'}
            else:
                logging.error(f'Failed to select option: {selected_option}')
                return {'success': False, 'message': f"Failed to select option: {select_result.get('message')}"}

        except Exception as e:
            logging.error(f'Error in simple dropdown selection: {str(e)}')
            return {'success': False, 'message': f'An exception occurred: {str(e)}'}

    async def _execute_drag(self, action):
        """Execute drag action."""
        if not self._validate_params(action, ['param.sourceCoordinates', 'param.targetCoordinates']):
            return {'success': False, 'message': 'Missing coordinates for drag action'}
        success = await self._actions.drag(
            action.get('param').get('sourceCoordinates'), action.get('param').get('targetCoordinates')
        )
        if success:
            return {'success': True, 'message': 'Drag action successful.'}
        else:
            return {'success': False, 'message': 'Drag action failed.'}

    async def _execute_go_to_page(self, action):
        """Execute go to page action - the missing navigation action."""
        url = action.get('param', {}).get('url')
        if not url:
            return {'success': False, 'message': 'Missing URL parameter for go to page action'}

        try:
            # Use smart navigation if available
            if hasattr(self._actions, 'smart_navigate_to_page'):
                page = getattr(self._actions, 'page', None)
                if page:
                    navigation_performed = await self._actions.smart_navigate_to_page(page, url)

                    # Read action context for detailed error information
                    ctx = action_context_var.get()

                    if navigation_performed or navigation_performed is None:
                        message = 'Navigated to page' if navigation_performed else 'Already on target page'
                        return {'success': True, 'message': message}
                    else:
                        # Navigation failed, enrich error message with context
                        base_message = 'Navigation to page failed.'
                        error_details = {}

                        if ctx and ctx.error_type:
                            error_details = {
                                'error_type': ctx.error_type,
                                'error_reason': ctx.error_reason,
                                'attempted_strategies': ctx.attempted_strategies,
                                'element_info': ctx.element_info,
                                'playwright_error': ctx.playwright_error
                            }

                            # Make message more specific based on error type
                            if ctx.error_type == 'playwright_error':
                                base_message = f'Navigation failed: Browser interaction error.'
                            else:
                                base_message = f"Navigation failed: {ctx.error_reason or 'Unknown reason'}"

                        return {
                            'success': False,
                            'message': base_message,
                            'error_details': error_details
                        }

            # Fallback to regular navigation
            if hasattr(self._actions, 'go_to_page') and hasattr(self._actions, 'page'):
                await self._actions.go_to_page(self._actions.page, url)

                # Read action context for detailed error information
                ctx = action_context_var.get()

                # Check if navigation succeeded by checking context
                if not ctx or not ctx.error_type:
                    return {'success': True, 'message': 'Successfully navigated to page'}
                else:
                    # Navigation failed, enrich error message with context
                    base_message = 'Navigation to page failed.'
                    error_details = {
                        'error_type': ctx.error_type,
                        'error_reason': ctx.error_reason,
                        'attempted_strategies': ctx.attempted_strategies,
                        'element_info': ctx.element_info,
                        'playwright_error': ctx.playwright_error
                    }

                    if ctx.error_type == 'playwright_error':
                        base_message = f'Navigation failed: Browser interaction error.'
                    else:
                        base_message = f"Navigation failed: {ctx.error_reason or 'Unknown reason'}"

                    return {
                        'success': False,
                        'message': base_message,
                        'error_details': error_details
                    }

            return {'success': False, 'message': 'Navigation method not available'}

        except Exception as e:
            logging.error(f'Go to page action failed: {str(e)}')

            # Read action context for any additional error information
            ctx = action_context_var.get()
            error_details = {}

            if ctx and ctx.error_type:
                error_details = {
                    'error_type': ctx.error_type,
                    'error_reason': ctx.error_reason,
                    'attempted_strategies': ctx.attempted_strategies,
                    'element_info': ctx.element_info,
                    'playwright_error': ctx.playwright_error or str(e)
                }
            else:
                error_details = {
                    'error_type': 'playwright_error',
                    'error_reason': 'Navigation failed with an exception',
                    'attempted_strategies': [],
                    'element_info': {},
                    'playwright_error': str(e)
                }

            return {
                'success': False,
                'message': f'Navigation failed: {str(e)}',
                'error_details': error_details
            }

    async def _execute_go_back(self):
        """Execute browser back navigation action."""
        try:
            if hasattr(self._actions, 'go_back'):
                success = await self._actions.go_back()

                # Read action context for detailed error information
                ctx = action_context_var.get()

                if success:
                    return {'success': True, 'message': 'Successfully navigated back to previous page'}
                else:
                    # Navigation failed, enrich error message with context
                    base_message = 'Go back navigation failed.'
                    error_details = {}

                    if ctx and ctx.error_type:
                        error_details = {
                            'error_type': ctx.error_type,
                            'error_reason': ctx.error_reason,
                            'attempted_strategies': ctx.attempted_strategies,
                            'element_info': ctx.element_info,
                            'playwright_error': ctx.playwright_error
                        }

                        # Make message more specific based on error type
                        if ctx.error_type == 'playwright_error':
                            base_message = f'Go back failed: Browser interaction error.'
                        else:
                            base_message = f"Go back failed: {ctx.error_reason or 'Unknown reason'}"
                    else:
                        base_message = 'Go back navigation failed. No previous page in history or navigation not possible.'

                    return {
                        'success': False,
                        'message': base_message,
                        'error_details': error_details
                    }
            else:
                return {'success': False, 'message': 'Go back action not supported by action handler'}
        except Exception as e:
            logging.error(f'Go back action failed: {str(e)}')

            # Read action context for any additional error information
            ctx = action_context_var.get()
            error_details = {}

            if ctx and ctx.error_type:
                error_details = {
                    'error_type': ctx.error_type,
                    'error_reason': ctx.error_reason,
                    'attempted_strategies': ctx.attempted_strategies,
                    'element_info': ctx.element_info,
                    'playwright_error': ctx.playwright_error or str(e)
                }
            else:
                error_details = {
                    'error_type': 'playwright_error',
                    'error_reason': 'Go back navigation failed with an exception',
                    'attempted_strategies': [],
                    'element_info': {},
                    'playwright_error': str(e)
                }

            return {
                'success': False,
                'message': f'Go back failed: {str(e)}',
                'error_details': error_details
            }

    async def _execute_mouse(self, action):
        """Unified mouse action supporting move and wheel.

        Accepted param formats:
        - { op: "move", x: number, y: number }
        - { op: "wheel", deltaX: number, deltaY: number }
        - Back-compat: if op is omitted, decide by presence of keys
        """
        try:
            param = action.get('param')
            if not param or not isinstance(param, dict):
                return {'success': False, 'message': 'Missing or invalid param for mouse action'}

            op = param.get('op')

            # Auto-detect if op not provided or empty
            if not op:
                if 'x' in param and 'y' in param:
                    op = 'move'
                elif 'deltaX' in param or 'deltaY' in param:
                    op = 'wheel'
                else:
                    return {'success': False, 'message': 'Missing mouse operation parameters (x/y or deltaX/deltaY)'}

            if op == 'move':
                if not self._validate_params(action, ['param.x', 'param.y']):
                    return {'success': False, 'message': 'Missing x or y coordinates for mouse move'}

                x = param.get('x')
                y = param.get('y')

                # Validate coordinates are numbers
                if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
                    return {'success': False, 'message': 'x and y coordinates must be numbers'}

                success = await self._actions.mouse_move(x, y)

                # Read action context for detailed error information
                ctx = action_context_var.get()

                if success:
                    return {'success': True, 'message': f'Mouse moved to ({x}, {y})'}
                else:
                    # Mouse move failed, enrich error message with context
                    base_message = 'Mouse move action failed.'
                    error_details = {}

                    if ctx and ctx.error_type:
                        error_details = {
                            'error_type': ctx.error_type,
                            'error_reason': ctx.error_reason,
                            'attempted_strategies': ctx.attempted_strategies,
                            'element_info': ctx.element_info,
                            'playwright_error': ctx.playwright_error
                        }

                        # Make message more specific based on error type
                        if ctx.error_type == 'playwright_error':
                            base_message = f'Mouse move failed: Browser interaction error.'
                        else:
                            base_message = f"Mouse move failed: {ctx.error_reason or 'Unknown reason'}"
                    else:
                        base_message = f'Mouse move to ({x}, {y}) failed. The operation might not be supported.'

                    return {
                        'success': False,
                        'message': base_message,
                        'error_details': error_details
                    }

            elif op == 'wheel':
                # Default missing keys to 0
                dx = param.get('deltaX', 0)
                dy = param.get('deltaY', 0)

                # Validate deltas are numbers
                if not isinstance(dx, (int, float)) or not isinstance(dy, (int, float)):
                    return {'success': False, 'message': 'deltaX and deltaY must be numbers'}

                success = await self._actions.mouse_wheel(dx, dy)

                # Read action context for detailed error information
                ctx = action_context_var.get()

                if success:
                    return {'success': True, 'message': f'Mouse wheel scrolled (deltaX: {dx}, deltaY: {dy})'}
                else:
                    # Mouse wheel failed, enrich error message with context
                    base_message = 'Mouse wheel action failed.'
                    error_details = {}

                    if ctx and ctx.error_type:
                        error_details = {
                            'error_type': ctx.error_type,
                            'error_reason': ctx.error_reason,
                            'attempted_strategies': ctx.attempted_strategies,
                            'element_info': ctx.element_info,
                            'playwright_error': ctx.playwright_error
                        }

                        # Make message more specific based on error type
                        if ctx.error_type == 'playwright_error':
                            base_message = f'Mouse wheel scroll failed: Browser interaction error.'
                        else:
                            base_message = f"Mouse wheel scroll failed: {ctx.error_reason or 'Unknown reason'}"
                    else:
                        base_message = f'Mouse wheel scroll (deltaX: {dx}, deltaY: {dy}) failed. The operation might not be supported.'

                    return {
                        'success': False,
                        'message': base_message,
                        'error_details': error_details
                    }

            else:
                logging.error(f"Unknown mouse op: {op}. Expected 'move' or 'wheel'.")
                return {'success': False, 'message': f"Unknown mouse operation: {op}. Expected 'move' or 'wheel'"}

        except Exception as e:
            logging.error(f'Mouse action execution failed: {str(e)}')

            # Read action context for any additional error information
            ctx = action_context_var.get()
            error_details = {}

            if ctx and ctx.error_type:
                error_details = {
                    'error_type': ctx.error_type,
                    'error_reason': ctx.error_reason,
                    'attempted_strategies': ctx.attempted_strategies,
                    'element_info': ctx.element_info,
                    'playwright_error': ctx.playwright_error or str(e)
                }
            else:
                error_details = {
                    'error_type': 'playwright_error',
                    'error_reason': 'Mouse action failed with an exception',
                    'attempted_strategies': [],
                    'element_info': {},
                    'playwright_error': str(e)
                }

            return {
                'success': False,
                'message': f'Mouse action failed with an exception: {e}',
                'error_details': error_details
            }
