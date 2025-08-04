"""
This module provides utility functions for generating parts of agent prompts.
"""

def check_repetition(case: dict) -> str:
    """Checks for repeated actions in the test case history and returns a warning string."""
    if not case.get("test_context"):
        return ""

    warnings = []
    test_context = case["test_context"]

    # Check for repeated element interactions
    for element, data in test_context.get("tested_elements", {}).items():
        if data.get("test_count", 0) >= 2:
            recent_failures = [r for r in data.get("results", [])[-2:] if not r.get("success")]
            if len(recent_failures) >= 2:
                warnings.append(f"⚠️ REPETITION WARNING: Element '{element}' has failed multiple times recently. AVOID interacting with it again.")
            elif data.get("test_count", 0) >= 3:
                warnings.append(f"⚠️ REPETITION WARNING: Element '{element}' has been tested multiple times. Consider a different element or action.")

    # Check for repeated action paths
    test_path = test_context.get("test_path", [])
    if len(test_path) >= 3:
        recent_path = test_path[-3:]
        if len(set(recent_path)) == 1:
            warnings.append(f"⚠️ REPETITION WARNING: You are repeating the exact same action '{recent_path[0]}' three times in a row. You MUST choose a different action.")

    if warnings:
        return "=== REPETITION WARNINGS ===\n" + "\n".join(warnings) + "\n"
    
    return "No repetition detected. Proceed with the next logical step."