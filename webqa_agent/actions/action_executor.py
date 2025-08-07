import asyncio
import logging
from typing import Dict, List, Optional


class ActionExecutor:
    def __init__(self, action_handler):
        self._actions = action_handler
        self._action_map = {
            "Tap": self._execute_tap,
            "Hover": self._execute_hover,
            "Sleep": self._execute_sleep,
            "Input": self._execute_input,
            "Clear": self._execute_clear,
            "Scroll": self._execute_scroll,
            "KeyboardPress": self._execute_keyboard_press,
            "FalsyConditionStatement": self._execute_falsy,
            "Check": self._execute_check,
            "GetNewPage": self._execute_get_new_page,
            "Upload": self._execute_upload,
            "SelectDropdown": self._execute_select_dropdown,
            "Drag": self._execute_drag,
        }

    async def initialize(self):
        return self

    async def execute(self, action):
        try:
            # Validate the action
            action_type = action.get("type")
            if not action_type:
                logging.error("Action type is required")
                return False

            # Get the corresponding execution function
            execute_func = self._action_map.get(action_type)
            if not execute_func:
                logging.error(f"Unknown action type: {action_type}")
                return False

            # Execute the action
            logging.debug(f"Executing action: {action_type}")
            return await execute_func(action)

        except Exception as e:
            logging.error(f"Action execution failed: {str(e)}")
            return {"success": False, "message": f"Action execution failed with an exception: {e}"}

    def _validate_params(self, action, required_params):
        for param in required_params:
            keys = param.split(".")
            value = action
            for key in keys:
                value = value.get(key)
                if value is None:
                    if action["type"] == "Scroll" and key == "distance":
                        continue
                    logging.error(f"Missing required parameter: {param}")
                    return False  # Return False to indicate validation failure
        return True  # Return True if all parameters are present

    # Individual action execution methods - NO SCREENSHOTS
    async def _execute_clear(self, action):
        """Execute clear action on an input field."""
        if not self._validate_params(action, ["locate.id"]):
            return {"success": False, "message": "Missing locate.id for clear action"}
        success = await self._actions.clear(action.get("locate").get("id"))
        if success:
            return {"success": True, "message": "Clear action successful."}
        else:
            return {"success": False, "message": "Clear action failed. The element might not be clearable."}

    async def _execute_tap(self, action):
        """Execute tap/click action."""
        if not self._validate_params(action, ["locate.id"]):
            return {"success": False, "message": "Missing locate.id for tap action"}
        success = await self._actions.click(action.get("locate").get("id"))
        if success:
            return {"success": True, "message": "Tap action successful."}
        else:
            return {"success": False, "message": "Tap action failed. The element might not be clickable."}

    async def _execute_hover(self, action):
        """Execute hover action."""
        if not self._validate_params(action, ["locate.id"]):
            return {"success": False, "message": "Missing locate.id for hover action"}
        success = await self._actions.hover(action.get("locate").get("id"))
        if success:
            return {"success": True, "message": "Hover action successful."}
        else:
            return {"success": False, "message": "Hover action failed. The element might not be hoverable."}

    async def _execute_sleep(self, action):
        """Execute sleep/wait action."""
        if not self._validate_params(action, ["param.timeMs"]):
            return {"success": False, "message": "Missing param.timeMs for sleep action"}
        time_ms = action.get("param").get("timeMs")
        await asyncio.sleep(time_ms / 1000)
        return {"success": True, "message": f"Slept for {time_ms}ms."}

    async def _execute_input(self, action):
        """Execute input/type action."""
        if not self._validate_params(action, ["locate.id", "param.value"]):
            return {"success": False, "message": "Missing locate.id or param.value for input action"}
        try:
            value = action.get("param").get("value")
            clear_before_type = action.get("param").get("clear_before_type", False)  # Default is False
            success = await self._actions.type(
                action.get("locate").get("id"), value, clear_before_type=clear_before_type
            )
            if success:
                return {"success": True, "message": "Input action successful."}
            else:
                return {
                    "success": False,
                    "message": "Input action failed. The element might not be available for typing.",
                }
        except Exception as e:
            logging.error(f"Action '_execute_input' execution failed: {str(e)}")
            return {"success": False, "message": f"Input action failed with an exception: {e}"}

    async def _execute_scroll(self, action):
        """Execute scroll action."""
        if not self._validate_params(action, ["param.direction", "param.scrollType", "param.distance"]):
            return {"success": False, "message": "Missing parameters for scroll action"}
        direction = action.get("param").get("direction", "down")
        scroll_type = action.get("param").get("scrollType", "once")
        distance = action.get("param").get("distance", None)

        success = await self._actions.scroll(direction, scroll_type, distance)
        if success:
            return {"success": True, "message": f"Scrolled {direction} successfully."}
        else:
            return {"success": False, "message": "Scroll action failed."}

    async def _execute_keyboard_press(self, action):
        """Execute keyboard press action."""
        if not self._validate_params(action, ["param.value"]):
            return {"success": False, "message": "Missing param.value for keyboard press action"}
        success = await self._actions.keyboard_press(action.get("param").get("value"))
        if success:
            return {"success": True, "message": "Keyboard press successful."}
        else:
            return {"success": False, "message": "Keyboard press failed."}

    async def _execute_falsy(self, action):
        """Execute falsy condition statement."""
        return {"success": True, "message": "Falsy condition met."}

    async def _execute_check(self, action):
        """Execute check action."""
        return {"success": True, "message": "Check action completed."}

    async def _execute_get_new_page(self, action):
        """Execute get new page action."""
        success = await self._actions.get_new_page()
        if success:
            return {"success": True, "message": "Successfully switched to new page."}
        else:
            return {"success": False, "message": "Failed to get new page."}

    async def _execute_upload(self, action, file_path):
        """Execute upload action."""
        if not self._validate_params(action, ["locate.id"]):
            return {"success": False, "message": "Missing locate.id for upload action"}
        success = await self._actions.upload_file(action.get("locate").get("id"), file_path)
        if success:
            return {"success": True, "message": "File upload successful."}
        else:
            return {"success": False, "message": "File upload failed."}

    async def _execute_select_dropdown(self, action):
        """Execute select dropdown action."""
        locate = action.get("locate", {})
        dropdown_id = locate.get("dropdown_id")
        option_id = locate.get("option_id")
        selection_path_param = action.get("param", {}).get("selection_path")

        if dropdown_id is None or selection_path_param is None:
            logging.error("dropdown_id and selection_path are required for SelectDropdown")
            return {"success": False, "message": "dropdown_id and selection_path are required for SelectDropdown"}

        if isinstance(selection_path_param, str):
            selection_path = [selection_path_param]
        elif isinstance(selection_path_param, list) and selection_path_param:
            selection_path = selection_path_param
        else:
            logging.error("selection_path must be a non-empty string or list")
            return {"success": False, "message": "selection_path must be a non-empty string or list"}

        try:
            # choose option_id directly
            if option_id is not None and len(selection_path) == 1:
                logging.debug(f"Directly clicking option_id {option_id} for dropdown_id {dropdown_id}")
                return await self._actions.select_dropdown_option(dropdown_id, selection_path[0], option_id=option_id)

            # multi-level cascade or no option_id, use original logic
            if len(selection_path) == 1:
                return await self._execute_simple_selection(dropdown_id, selection_path[0])
            else:
                # multi-level cascade
                for level, option_text in enumerate(selection_path):
                    select_result = await self._actions.select_cascade_level(dropdown_id, option_text, level=level)
                    if not select_result.get("success"):
                        logging.error(f"Failed to select level {level} option: {select_result.get('message')}")
                        return {
                            "success": False,
                            "message": f"Failed at cascade level {level}: {select_result.get('message')}",
                        }
                    if level < len(selection_path) - 1:
                        await asyncio.sleep(0.5)
                logging.debug(f"Successfully completed cascade selection: {' -> '.join(selection_path)}")
                return {"success": True, "message": "Cascade selection completed successfully"}

        except Exception as e:
            logging.error(f"Error in dropdown selection: {str(e)}")
            return {"success": False, "message": f"An exception occurred during dropdown selection: {str(e)}"}

    async def _execute_simple_selection(self, element_id, option_text):
        """Execute simple single-level dropdown selection."""
        try:
            # get all options of dropdown
            logging.debug(f"Getting dropdown options for element {element_id}")
            options_result = await self._actions.get_dropdown_options(element_id)

            if not options_result.get("success"):
                logging.error(f"Failed to get dropdown options: {options_result.get('message')}")
                return {"success": False, "message": f"Failed to get dropdown options: {options_result.get('message')}"}

            options = options_result.get("options", [])
            if not options:
                logging.error("No options found in dropdown")
                return {"success": False, "message": "No options found in dropdown"}

            logging.debug(f"Found {len(options)} options in dropdown")

            # use default simple decision logic
            def _default_selection_logic(options: List[Dict], criteria: str) -> Optional[str]:
                criteria_lower = criteria.lower()

                for option in options:
                    if option["text"].lower() == criteria_lower:
                        logging.debug(f"Found exact match: {option['text']}")
                        return option["text"]

                for option in options:
                    if criteria_lower in option["text"].lower():
                        logging.debug(f"Found contains match: {option['text']}")
                        return option["text"]

                for option in options:
                    if option["text"].lower() in criteria_lower:
                        logging.debug(f"Found partial match: {option['text']}")
                        return option["text"]

                # if no match, return None
                logging.warning(f"No match found for criteria: {criteria}")
                return None

            selected_option = _default_selection_logic(options, option_text)

            if not selected_option:
                logging.error(f"Could not decide which option to select based on criteria: {option_text}")
                available_options = [opt["text"] for opt in options]
                logging.debug(f"Available options: {available_options}")
                return {"success": False, "message": "No matching option found", "available_options": available_options}

            logging.debug(f"Selected option: {selected_option}")

            # execute select operation
            select_result = await self._actions.select_dropdown_option(element_id, selected_option)

            if select_result.get("success"):
                logging.debug(f"Successfully completed dropdown selection: {selected_option}")
                return {"success": True, "message": "Option selected successfully"}
            else:
                logging.error(f"Failed to select option: {selected_option}")
                return {"success": False, "message": f"Failed to select option: {select_result.get('message')}"}

        except Exception as e:
            logging.error(f"Error in simple dropdown selection: {str(e)}")
            return {"success": False, "message": f"An exception occurred: {str(e)}"}

    async def _execute_drag(self, action):
        """Execute drag action."""
        if not self._validate_params(action, ["param.sourceCoordinates", "param.targetCoordinates"]):
            return {"success": False, "message": "Missing coordinates for drag action"}
        success = await self._actions.drag(
            action.get("param").get("sourceCoordinates"), action.get("param").get("targetCoordinates")
        )
        if success:
            return {"success": True, "message": "Drag action successful."}
        else:
            return {"success": False, "message": "Drag action failed."}
