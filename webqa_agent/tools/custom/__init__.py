"""Custom tools package for WebQA Agent.

This package contains optional custom tools that extend WebQA Agent's testing
capabilities beyond the core functionality (UI actions, assertions, UX verification).

Architecture:
    - Custom tools are OPTIONAL and must be explicitly enabled via configuration
    - Each tool uses @register_tool decorator for automatic registration
    - Registry filters tools based on enabled_custom_tools configuration
    - Tools can declare dependencies (e.g., lighthouse, nuclei)
    - Missing dependencies prevent tool registration (graceful degradation)

Configuration Example:
    test_config:
      custom_tools:
        enabled:
          - lighthouse                        # Lighthouse performance analysis
          - detect_dynamic_links              # Dynamic link detection and validation
          - traverse_clickable_elements       # Clickable element traversal
          - nuclei                            # Nuclei security scanning

Available Custom Tools:

1. Link Check Tool
   - File: link_check_tool.py
   - Class: LinkCheckTool
   - Tool name: detect_dynamic_links
   - Step type: detect_dynamic_links
   - Dependencies: None (always available)
   - Purpose: Detects and validates dynamically loaded links after user interactions

2. Button Check Tool
   - File: button_check_tool.py
   - Class: ButtonCheckTool
   - Tool name: traverse_clickable_elements
   - Step type: traverse_clickable_elements
   - Dependencies: None (always available)
   - Purpose: Comprehensive clickable element traversal and testing

3. Lighthouse Tool
   - File: lighthouse_tool.py
   - Class: LighthouseTool
   - Tool name: execute_lighthouse_test
   - Step type: lighthouse
   - Dependencies: lighthouse (npm install -g lighthouse)
   - Purpose: Google Lighthouse performance analysis and Core Web Vitals

4. Nuclei Tool
   - File: nuclei_tool.py
   - Class: NucleiTool
   - Tool name: execute_nuclei_scan
   - Step type: nuclei
   - Dependencies: nuclei (download from GitHub)
   - Purpose: Nuclei-based security vulnerability scanning

Tool Registration Flow:
    1. Parent package (tools/__init__.py) imports custom tool modules
    2. @register_tool decorator executes on class definition
    3. Tool registers with global ToolRegistry
    4. Registry checks dependencies (missing deps → skip registration)
    5. Registry filters by enabled_custom_tools configuration
    6. Filtered tools returned to agent for use in test execution

Development Guide:
    See docs/CUSTOM_TOOL_DEVELOPMENT_AI.md for guidelines on creating new custom tools.

Note on __all__:
    We intentionally keep __all__ empty because:
    - Tools register themselves via decorator (not via explicit imports)
    - Parent package (tools/__init__.py) imports modules (not classes)
    - Registry discovers tools via decorator, not via package exports
    - This prevents circular import issues and maintains clean architecture
"""

# Tools are registered via @register_tool decorator when modules are imported
# by the parent package (tools/__init__.py). No explicit exports needed here.
__all__ = []
