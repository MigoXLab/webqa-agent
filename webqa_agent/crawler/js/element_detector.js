// This file is modified from:
// https://github.com/browser-use/browser-use/browser_use/dom/dom_tree/index.js
//
// Copyright (c) 2024 Gregor Zunic
//
// Licensed under the MIT License

/**
 * DOM Element Detection and Highlighting System
 *
 * This module provides comprehensive functionality for detecting, analyzing, and highlighting
 * interactive elements and meaningful text content within web pages. It includes:
 *
 * - Interactive element detection with heuristic analysis
 * - Text element validation and extraction
 * - Visual highlighting with overlay rendering
 * - DOM tree construction with filtering capabilities
 * - Viewport-aware element processing
 * - Event listener detection and cursor analysis
 *
 * Key Features:
 * - Supports both interactive element and text content highlighting modes
 * - Handles nested elements with distinct interaction boundary detection
 * - Provides robust visibility and top-element checking
 * - Includes performance optimizations with caching mechanisms
 * - Supports iframe and Shadow DOM contexts
 */

(function () {
        window._highlight = window._highlight ?? true;                          // Master highlight rendering switch
        window._filterText = window._filterText ?? false;                       // Text element filter for highlighting
        window._viewportOnly = window._viewportOnly ?? false;                   // Viewport-only detection filter
        window._filterMedia = window._filterMedia ?? false;                     // Media element filter for highlighting
        let idCounter = 1;
        // let highlightIndex = 1;
        let highlightIndex = (typeof window.__highlightBase__ === 'number' ? window.__highlightBase__ : 0) + 1;
        const elementToId = new WeakMap();
        const highlightMap = new WeakMap();
        let highlightIdMap = new WeakMap();
        const styleCache = new WeakMap();
        const _elementHighlightColorMap = new WeakMap();
        const INTERACTIVE_TAGS = new Set(['a', 'button', 'input', 'select', 'textarea', 'summary', 'details', 'label', 'option']);
        const INTERACTIVE_ROLES = new Set(['button', 'link', 'menuitem', 'menuitemradio', 'menuitemcheckbox', 'radio', 'checkbox', 'tab', 'switch', 'slider', 'spinbutton', 'combobox', 'searchbox', 'textbox', 'listbox', 'option', 'scrollbar']);
        const MEDIA_TAGS = new Set(['img', 'svg']);  // extended media tags: 'canvas', 'video', 'audio', 'embed'
        const palette = ['#e6194b', '#3cb44b', '#ffe119', '#4363d8', '#f58231', '#911eb4', '#46f0f0', '#f032e6', '#bcf60c', '#fabebe', '#008080', '#e6beff'];  // highlighting colors
        const overlayContainer = document.getElementById('__marker_container__') || (() => {  // highlight container
            const c = document.createElement('div');
            c.id = '__marker_container__';
            Object.assign(c.style, {
                position: 'fixed',
                top: '0',
                left: '0',
                width: '100vw',
                height: '100vh',
                pointerEvents: 'none',
                zIndex: '2147483647'
            });
            document.body.appendChild(c);
            return c;
        })();

        // ============================= Element Information Extraction =============================
        /**
         * Retrieves a unique identifier for a given HTML element.
         *
         * If the element does not already have a 'id' attribute, this function assigns a new,
         * auto-incrementing ID to it. This ensures that every element can be uniquely identified
         * during the crawling process.
         *
         * @param {HTMLElement} elem The HTML element for which to get the ID.
         * @returns {number} The unique integer ID of the element.
         */
        function getElementId(elem) {
            if (!elementToId.has(elem)) elementToId.set(elem, idCounter++);
            return elementToId.get(elem);
        }

        /**
         * Retrieves the computed CSS style for an element, using a cache to avoid redundant calculations.
         *
         * This function fetches the `CSSStyleDeclaration` object for an element. To optimize performance,
         * it caches the result based on the element's unique ID. Subsequent calls for the same element
         * will return the cached style object, reducing layout reflows.
         *
         * @param {HTMLElement} elem The HTML element to get the style for.
         * @returns {CSSStyleDeclaration} The computed style object.
         */
        function getCachedStyle(elem) {
            if (!styleCache.has(elem)) {
                styleCache.set(elem, window.getComputedStyle(elem));
            }
            return styleCache.get(elem);
        }

        /**
         * Return a compact subset of computed styles for model consumption
         */
        function getStyleSubset(elem) {
            if (!window._includeStyles) return null;
            try {
                const s = getCachedStyle(elem);
                return {
                    display: s.display,
                    visibility: s.visibility,
                    opacity: s.opacity,
                    position: s.position,
                    zIndex: s.zIndex,
                    overflowX: s.overflowX,
                    overflowY: s.overflowY,
                    textOverflow: s.textOverflow,
                    whiteSpace: s.whiteSpace,
                    wordBreak: s.wordBreak,
                    wordWrap: s.wordWrap,
                    fontSize: s.fontSize,
                    fontWeight: s.fontWeight,
                    lineHeight: s.lineHeight,
                    color: s.color,
                    backgroundColor: s.backgroundColor,
                    pointerEvents: s.pointerEvents,
                    cursor: s.cursor,
                    // Layout related
                    width: s.width,
                    height: s.height,
                    maxWidth: s.maxWidth,
                    maxHeight: s.maxHeight,
                    margin: s.margin,
                    padding: s.padding,
                    // Alignment related
                    textAlign: s.textAlign,
                    verticalAlign: s.verticalAlign,
                    justifyContent: s.justifyContent,
                    alignItems: s.alignItems,
                    flexDirection: s.flexDirection,
                    gap: s.gap,
                    // Border and background
                    border: s.border,
                    borderColor: s.borderColor,
                    borderWidth: s.borderWidth,
                    outline: s.outline,
                    hasBackgroundImage: s.backgroundImage && s.backgroundImage !== 'none' && !s.backgroundImage.includes('gradient'),
                    backgroundSize: s.backgroundSize,
                    objectFit: s.objectFit,
                };
            } catch (e) {
                return null;
            }
        }

        /**
         * Determines if an element is heuristically interactive based on various signals.
         *
         * This function uses heuristic analysis to identify elements that may be interactive
         * even if they don't have explicit interactive attributes. It checks for:
         * 1. Interactive attributes (role, tabindex, onclick)
         * 2. Semantic class names suggesting interactivity
         * 3. Placement within known interactive containers
         * 4. Presence of visible children
         * 5. Avoids top-level body children (likely layout containers)
         *
         * @param {HTMLElement} element The element to evaluate for heuristic interactivity.
         * @returns {boolean} `true` if the element appears to be heuristically interactive, otherwise `false`.
         */
        function isHeuristicallyInteractive(element) {
            if (!element || element.nodeType !== Node.ELEMENT_NODE) return false;

            // Skip non-visible elements early for performance
            if (!isVisible(element)) return false;

            // Check for common attributes that often indicate interactivity
            const hasInteractiveAttributes =
                element.hasAttribute('role') ||
                element.hasAttribute('tabindex') ||
                element.hasAttribute('onclick') ||
                typeof element.onclick === 'function';

            // Check for semantic class names suggesting interactivity
            const hasInteractiveClass = /\b(btn|clickable|menu|item|entry|link)\b/i.test(element.className || '');

            // Determine whether the element is inside a known interactive container
            const isInKnownContainer = Boolean(
                element.closest('button,a,[role="button"],.menu,.dropdown,.list,.toolbar')
            );

            // Ensure the element has at least one visible child (to avoid marking empty wrappers)
            const hasVisibleChildren = [...element.children].some(isVisible);

            // Avoid highlighting elements whose parent is <body> (top-level wrappers)
            const isParentBody = element.parentElement && element.parentElement.isSameNode(document.body);

            return (
                (isInteractiveElement(element) || hasInteractiveAttributes || hasInteractiveClass) &&
                hasVisibleChildren &&
                isInKnownContainer &&
                !isParentBody
            );
        }

        /**
         * Determines if an element represents a distinct interaction boundary.
         *
         * An element is considered a distinct interaction boundary if it is interactive itself,
         * but none of its ancestor elements are. This helps identify the outermost interactive
         * element in a nested structure, which is often the primary target for user actions.
         * For example, in `<a><div>Click me</div></a>`, the `<a>` tag is the distinct boundary.
         *
         * @param {HTMLElement} element The element to evaluate.
         * @returns {boolean} `true` if the element is a distinct interaction boundary, otherwise `false`.
         */
        function isElementDistinctInteraction(element) {
            if (!element || element.nodeType !== Node.ELEMENT_NODE) {
                return false;
            }

            const tagName = element.tagName.toLowerCase();
            const role = element.getAttribute('role');

            // Check if it's an iframe - always distinct boundary
            if (tagName === 'iframe') {
                return true;
            }

            // Check tag name
            if (INTERACTIVE_TAGS.has(tagName)) {
                return true;
            }
            // Check interactive roles
            if (role && INTERACTIVE_ROLES.has(role)) {
                return true;
            }
            // Check contenteditable
            if (element.isContentEditable || element.getAttribute('contenteditable') === 'true') {
                return true;
            }
            // Check for common testing/automation attributes
            if (element.hasAttribute('data-testid') || element.hasAttribute('data-cy') || element.hasAttribute('data-test')) {
                return true;
            }
            // Check for explicit onclick handler (attribute or property)
            if (element.hasAttribute('onclick') || typeof element.onclick === 'function') {
                return true;
            }
            // Check for other common interaction event listeners
            try {
                const getEventListenersForNode = element?.ownerDocument?.defaultView?.getEventListenersForNode || window.getEventListenersForNode;
                if (typeof getEventListenersForNode === 'function') {
                    const listeners = getEventListenersForNode(element);
                    const interactionEvents = ['click', 'mousedown', 'mouseup', 'keydown', 'keyup', 'submit', 'change', 'input', 'focus', 'blur'];
                    for (const eventType of interactionEvents) {
                        for (const listener of listeners) {
                            if (listener.type === eventType) {
                                return true; // Found a common interaction listener
                            }
                        }
                    }
                }
                // Fallback: Check common event attributes if getEventListeners is not available (getEventListenersForNode doesn't work in page.evaluate context)
                const commonEventAttrs = ['onmousedown', 'onmouseup', 'onkeydown', 'onkeyup', 'onsubmit', 'onchange', 'oninput', 'onfocus', 'onblur'];
                if (commonEventAttrs.some(attr => element.hasAttribute(attr))) {
                    return true;
                }
            } catch (e) {
                // console.warn(`Could not check event listeners for ${element.tagName}:`, e);
                // If checking listeners fails, rely on other checks
            }

            // if the element is not strictly interactive but appears clickable based on heuristic signals
            if (isHeuristicallyInteractive(element)) {
                return true;
            }
            return false;
        }

        /**
         * Unified media element detection function
         * @param {HTMLElement} element Element to check
         * @returns {object} Media element info {isMedia: boolean, type: string, hasBackground: boolean}
         */
        function detectMediaElement(element) {
            if (!element || element.nodeType !== Node.ELEMENT_NODE) {
                return {isMedia: false, type: null, hasBackground: false};
            }

            const tagName = element.tagName.toLowerCase();

            // Standard media tags
            if (MEDIA_TAGS.has(tagName)) {
                return {isMedia: true, type: 'standard', hasBackground: false};
            }

            // Background image detection
            const backgroundInfo = detectBackgroundImage(element);
            if (backgroundInfo.hasBackground) {
                return {isMedia: true, type: 'background', hasBackground: true};
            }

            // Image container detection
            if (isImageContainer(element)) {
                return {isMedia: true, type: 'container', hasBackground: false};
            }

            return {isMedia: false, type: null, hasBackground: false};
        }

        /**
         * Simplified media element detection entry point
         * @param {HTMLElement} element Element to check
         * @returns {boolean} Whether it is a media element
         */
        function isMediaElement(element) {
            return detectMediaElement(element).isMedia;
        }

        /**
         * Enhanced background image detection function (supports depth detection)
         * @param {HTMLElement} element Element to check
         * @param {number} maxDepth Maximum detection depth
         * @returns {object} Background image info {hasBackground: boolean, hasDeepBackground: boolean, source: string}
         */
        function detectBackgroundImage(element, maxDepth = 0) {
            const style = getComputedStyle(element);
            const backgroundImage = style.backgroundImage;

            // Standard background image
            if (backgroundImage && backgroundImage !== 'none' && !backgroundImage.includes('gradient')) {
                return {hasBackground: true, hasDeepBackground: false, source: 'css'};
            }

            // CSS variables
            const cssVars = ['--background-image', '--bg-image', '--image']
                .map(prop => style.getPropertyValue(prop))
                .find(val => val && val.includes('url('));
            if (cssVars) {
                return {hasBackground: true, hasDeepBackground: false, source: 'variable'};
            }

            // Inline styles
            const inlineStyle = element.getAttribute('style') || '';
            if (inlineStyle.includes('background-image') && inlineStyle.includes('url(')) {
                return {hasBackground: true, hasDeepBackground: false, source: 'inline'};
            }

            // Pseudo elements
            try {
                const pseudoElements = ['::before', '::after'];
                for (const pseudo of pseudoElements) {
                    const pseudoStyle = getComputedStyle(element, pseudo);
                    if (pseudoStyle.backgroundImage && pseudoStyle.backgroundImage !== 'none') {
                        return {hasBackground: true, hasDeepBackground: false, source: 'pseudo'};
                    }
                }
            } catch (e) {
                // Ignore errors
            }

            // Deep detection of child elements
            if (maxDepth > 0) {
                for (const child of element.children) {
                    const childResult = detectBackgroundImage(child, maxDepth - 1);
                    if (childResult.hasBackground || childResult.hasDeepBackground) {
                        return {hasBackground: false, hasDeepBackground: true, source: childResult.source};
                    }
                }
            }

            return {hasBackground: false, hasDeepBackground: false, source: null};
        }

        /**
         * Check if element is an image container
         * @param {HTMLElement} element Element to check
         * @returns {boolean} Whether it is an image container
         */
        function isImageContainer(element) {
            const className = element.className || '';
            const id = element.id || '';

            // Check for image-related keywords in class names and IDs
            const imageKeywords = [
                'image', 'img', 'photo', 'picture', 'pic', 'gallery',
                'hero', 'banner', 'product', 'thumbnail', 'avatar',
                'background', 'bg', 'visual', 'media'
            ];

            const text = (className + ' ' + id).toLowerCase();
            const hasImageKeyword = imageKeywords.some(keyword => text.includes(keyword));

            if (hasImageKeyword) {
                // Use unified detection function
                const backgroundInfo = detectBackgroundImage(element, 2); // Check 2 levels deep
                if (backgroundInfo.hasBackground || backgroundInfo.hasDeepBackground) {
                    return true;
                }

                // Check if it contains img tags
                if (element.querySelector('img')) {
                    return true;
                }
            }

            return false;
        }

        /**
         * Unified media element visibility detection
         * @param {HTMLElement} element Element to check
         * @param {object} mediaInfo Media element information
         * @returns {boolean} Whether it is visible
         */
        function isMediaElementVisible(element, mediaInfo) {
            const style = getComputedStyle(element);

            // Basic visibility check
            if (style?.visibility === "hidden" || style?.display === "none" || parseFloat(style?.opacity || '1') === 0) {
                return false;
            }

            const tagName = element.tagName.toLowerCase();
            const rect = element.getBoundingClientRect();

            // Use different detection strategies based on media type
            switch (mediaInfo.type) {
                case 'standard':
                    if (tagName === 'svg') {
                        return rect.width > 0 || rect.height > 0 ||
                            element.hasAttribute('viewBox') ||
                            element.hasAttribute('width') ||
                            element.hasAttribute('height');
                    }
                    return element.offsetWidth > 0 && element.offsetHeight > 0;

                case 'background':
                    return rect.width > 0 && rect.height > 0 &&
                        style.backgroundSize !== '0px' && style.backgroundSize !== '0';

                case 'container':
                    return rect.width > 0 && rect.height > 0;

                default:
                    return element.offsetWidth > 0 && element.offsetHeight > 0;
            }
        }

        /**
         * Determines if an element is considered interactive.
         *
         * An element is deemed interactive if it meets any of the following criteria:
         * 1. Is an inherently interactive HTML tag (e.g., <a>, <button>, <input>).
         * 2. Has an ARIA role that implies interactivity (e.g., 'button', 'link').
         * 3. Is focusable via a non-negative `tabindex`.
         * 4. Has specific event listeners attached (e.g., 'click', 'keydown').
         * 5. Has a 'pointer' cursor style, suggesting it's clickable.
         * 6. Is content-editable.
         * 7. Is a media element when media highlighting is enabled.
         *
         * @param {HTMLElement} element The element to evaluate.
         * @returns {boolean} `true` if the element is interactive, otherwise `false`.
         */
        function isInteractiveElement(element) {
            if (!element || element.nodeType !== Node.ELEMENT_NODE) {
                return false;
            }

            // Cache the tagName and style lookups
            const tagName = element.tagName.toLowerCase();
            const style = getCachedStyle(element);


            // Define interactive cursors
            const interactiveCursors = new Set([
                'pointer',    // Link/clickable elements
                'move',       // Movable elements
                'text',       // Text selection
                'grab',       // Grabbable elements
                'grabbing',   // Currently grabbing
                'cell',       // Table cell selection
                'copy',       // Copy operation
                'alias',      // Alias creation
                'all-scroll', // Scrollable content
                'col-resize', // Column resize
                'context-menu', // Context menu available
                'crosshair',  // Precise selection
                'e-resize',   // East resize
                'ew-resize',  // East-west resize
                'help',       // Help available
                'n-resize',   // North resize
                'ne-resize',  // Northeast resize
                'nesw-resize', // Northeast-southwest resize
                'ns-resize',  // North-south resize
                'nw-resize',  // Northwest resize
                'nwse-resize', // Northwest-southeast resize
                'row-resize', // Row resize
                's-resize',   // South resize
                'se-resize',  // Southeast resize
                'sw-resize',  // Southwest resize
                'vertical-text', // Vertical text selection
                'w-resize',   // West resize
                'zoom-in',    // Zoom in
                'zoom-out'    // Zoom out
            ]);

            // Define non-interactive cursors
            const nonInteractiveCursors = new Set([
                'not-allowed', // Action not allowed
                'no-drop',     // Drop not allowed
                'wait',        // Processing
                'progress',    // In progress
                'initial',     // Initial value
                'inherit'      // Inherited value
                //? Let's just include all potentially clickable elements that are not specifically blocked
                // 'none',        // No cursor
                // 'default',     // Default cursor
                // 'auto',        // Browser default
            ]);

            function doesElementHaveInteractivePointer(element) {
                if (element.tagName.toLowerCase() === "html") return false;

                if (interactiveCursors.has(style.cursor)) return true;

                return false;
            }

            let isInteractiveCursor = doesElementHaveInteractivePointer(element);

            // Genius fix for almost all interactive elements
            if (isInteractiveCursor) {
                return true;
            }

            const interactiveElements = new Set([
                "a",          // Links
                "button",     // Buttons
                "input",      // All input types (text, checkbox, radio, etc.)
                "select",     // Dropdown menus
                "textarea",   // Text areas
                "details",    // Expandable details
                "summary",    // Summary element (clickable part of details)
                "label",      // Form labels (often clickable)
                "option",     // Select options
                "optgroup",   // Option groups
                "fieldset",   // Form fieldsets (can be interactive with legend)
                "legend",     // Fieldset legends
            ]);

            // Define explicit disable attributes and properties
            const explicitDisableTags = new Set([
                'disabled',           // Standard disabled attribute
                // 'aria-disabled',      // ARIA disabled state
                'readonly',          // Read-only state
                // 'aria-readonly',     // ARIA read-only state
                // 'aria-hidden',       // Hidden from accessibility
                // 'hidden',            // Hidden attribute
                // 'inert',             // Inert attribute
                // 'aria-inert',        // ARIA inert state
                // 'tabindex="-1"',     // Removed from tab order
                // 'aria-hidden="true"' // Hidden from screen readers
            ]);

            // handle inputs, select, checkbox, radio, textarea, button and make sure they are not cursor style disabled/not-allowed
            if (interactiveElements.has(tagName)) {
                // Check for non-interactive cursor
                if (nonInteractiveCursors.has(style.cursor)) {
                    return false;
                }

                // Check for explicit disable attributes
                for (const disableTag of explicitDisableTags) {
                    if (element.hasAttribute(disableTag) ||
                        element.getAttribute(disableTag) === 'true' ||
                        element.getAttribute(disableTag) === '') {
                        return false;
                    }
                }

                // Check for disabled property on form elements
                if (element.disabled) {
                    return false;
                }

                // Check for readonly property on form elements
                if (element.readOnly) {
                    return false;
                }

                // Check for inert property
                if (element.inert) {
                    return false;
                }

                return true;
            }

            const role = element.getAttribute("role");
            const ariaRole = element.getAttribute("aria-role");

            // Check for contenteditable attribute
            if (element.getAttribute("contenteditable") === "true" || element.isContentEditable) {
                return true;
            }

            // Added enhancement to capture dropdown interactive elements
            if (element.classList && (
                element.classList.contains("button") ||
                element.classList.contains('dropdown-toggle') ||
                element.getAttribute('data-index') ||
                element.getAttribute('data-toggle') === 'dropdown' ||
                element.getAttribute('aria-haspopup') === 'true'
            )) {
                return true;
            }

            const interactiveRoles = new Set([
                'button',           // Directly clickable element
                'link',            // Clickable link
                'menu',            // Menu container (ARIA menus)
                'menubar',         // Menu bar container
                'menuitem',        // Clickable menu item
                'menuitemradio',   // Radio-style menu item (selectable)
                'menuitemcheckbox', // Checkbox-style menu item (toggleable)
                'radio',           // Radio button (selectable)
                'checkbox',        // Checkbox (toggleable)
                'tab',             // Tab (clickable to switch content)
                'switch',          // Toggle switch (clickable to change state)
                'slider',          // Slider control (draggable)
                'spinbutton',      // Number input with up/down controls
                'combobox',        // Dropdown with text input
                'searchbox',       // Search input field
                'textbox',         // Text input field
                'listbox',         // Selectable list
                'option',          // Selectable option in a list
                'scrollbar'        // Scrollable control
            ]);

            // Basic role/attribute checks
            const hasInteractiveRole =
                interactiveElements.has(tagName) ||
                (role && interactiveRoles.has(role)) ||
                (ariaRole && interactiveRoles.has(ariaRole));

            if (hasInteractiveRole) return true;


            // check whether element has event listeners by window.getEventListeners
            try {
                if (typeof getEventListeners === 'function') {
                    const listeners = getEventListeners(element);
                    const mouseEvents = ['click', 'mousedown', 'mouseup', 'dblclick'];
                    for (const eventType of mouseEvents) {
                        if (listeners[eventType] && listeners[eventType].length > 0) {
                            return true; // Found a mouse interaction listener
                        }
                    }
                }

                const getEventListenersForNode = element?.ownerDocument?.defaultView?.getEventListenersForNode || window.getEventListenersForNode;
                if (typeof getEventListenersForNode === 'function') {
                    const listeners = getEventListenersForNode(element);
                    const interactionEvents = ['click', 'mousedown', 'mouseup', 'keydown', 'keyup', 'submit', 'change', 'input', 'focus', 'blur'];
                    for (const eventType of interactionEvents) {
                        for (const listener of listeners) {
                            if (listener.type === eventType) {
                                return true; // Found a common interaction listener
                            }
                        }
                    }
                }
                // Fallback: Check common event attributes if getEventListeners is not available (getEventListeners doesn't work in page.evaluate context)
                const commonMouseAttrs = ['onclick', 'onmousedown', 'onmouseup', 'ondblclick'];
                for (const attr of commonMouseAttrs) {
                    if (element.hasAttribute(attr) || typeof element[attr] === 'function') {
                        return true;
                    }
                }
            } catch (e) {
                // console.warn(`Could not check event listeners for ${element.tagName}:`, e);
                // If checking listeners fails, rely on other checks
            }

            return false
        }

        /**
         * Validates if an element is a meaningful text container suitable for extraction.
         *
         * An element is considered a valid text element if it meets all the following conditions:
         * 1. It is visible (i.e., not `display: none` or `visibility: hidden`).
         * 2. It contains non-empty, trimmed text content.
         * 3. It is not a tag typically used for scripting or non-visual content (e.g., <script>, <style>).
         * 4. Its dimensions are not trivially small (e.g., less than 3x3 pixels) and not too large.
         * 5. It is not an interactive element, as those are handled separately.
         *
         * @param {HTMLElement} element The element to validate.
         * @returns {boolean} `true` if the element is a valid text container, otherwise `false`.
         */
        function isValidTextElement(element) {
            if (!element || element.nodeType !== Node.ELEMENT_NODE) {
                return false;
            }

            // Cache tagName and computed style for performance
            const tagName = element.tagName.toLowerCase();
            const style = getCachedStyle(element);

            // 1. Visibility check - element must be visible
            if (
                style.display === 'none' ||
                style.visibility === 'hidden' ||
                parseFloat(style.opacity) === 0
            ) {
                return false;
            }

            // 2. Must contain non-whitespace text content
            const text = (element.innerText || element.textContent || '').trim();
            if (!text) return false;

            // 3. Exclude common structural containers (usually don't display user-relevant text)
            const structuralTags = new Set([
                'html', 'body', 'section', 'header', 'footer', 'main', 'nav', 'article', 'aside', 'template', 'iframe'
            ]);
            if (structuralTags.has(tagName)) {
                return false;
            }

            // 4. Exclude large containers that occupy most of the viewport (likely layout or whitespace areas)
            const rect = element.getBoundingClientRect();
            const vw = window.innerWidth, vh = window.innerHeight;
            const areaRatio = (rect.width * rect.height) / (vw * vh);
            if (areaRatio > 0.6) return false;  // Adjust threshold as needed

            // 5. If element is interactive, let isInteractiveElement handle it to avoid duplicate processing
            // if (isInteractiveElement(element) && !isElementDistinctInteraction(element)) {
            if (isInteractiveElement(element)) return false;

            // 6. Final validation - this is considered a meaningful text information node
            return true;
        }

        /**
         * Checks if an element is the top-most element at its center point.
         *
         * This function determines if the given element is the one that would receive a click
         * at its geometric center. It is useful for filtering out occluded or overlaid elements.
         *
         * @param {HTMLElement} element The element to check.
         * @returns {boolean} `true` if the element is on top, otherwise `false`.
         */
        function isTopElement(element) {
            if (!window._viewportOnly) {
                return true;
            }
            const viewportExpansion = 0;

            const rects = element.getClientRects(element); // Replace element.getClientRects()

            if (!rects || rects.length === 0) {
                return false; // No geometry, cannot be top
            }

            let isAnyRectInViewport = false;
            for (const rect of rects) {
                // Use the same logic as isInExpandedViewport check
                if (rect.width > 0 && rect.height > 0 && !( // Only check non-empty rects
                    rect.bottom < -viewportExpansion ||
                    rect.top > window.innerHeight + viewportExpansion ||
                    rect.right < -viewportExpansion ||
                    rect.left > window.innerWidth + viewportExpansion
                )) {
                    isAnyRectInViewport = true;
                    break;
                }
            }

            if (!isAnyRectInViewport) {
                return false; // All rects are outside the viewport area
            }


            // Find the correct document context and root element
            let doc = element.ownerDocument;

            // If we're in an iframe, elements are considered top by default
            if (doc !== window.document) {
                return true;
            }

            // For shadow DOM, we need to check within its own root context
            const shadowRoot = element.getRootNode();
            if (shadowRoot instanceof ShadowRoot) {
                const centerX = rects[Math.floor(rects.length / 2)].left + rects[Math.floor(rects.length / 2)].width / 2;
                const centerY = rects[Math.floor(rects.length / 2)].top + rects[Math.floor(rects.length / 2)].height / 2;

                try {
                    const topEl = shadowRoot.elementFromPoint(centerX, centerY);
                    if (!topEl) return false;

                    let current = topEl;
                    while (current && current !== shadowRoot) {
                        if (current === element) return true;
                        current = current.parentElement;
                    }
                    return false;
                } catch (e) {
                    return true;
                }
            }

            const margin = 10
            const rect = rects[Math.floor(rects.length / 2)];

            // For elements in viewport, check if they're topmost. Do the check in the
            // center of the element and at the corners to ensure we catch more cases.
            const checkPoints = [
                // Initially only this was used, but it was not enough
                {x: rect.left + rect.width / 2, y: rect.top + rect.height / 2},
                {x: rect.left + margin, y: rect.top + margin},        // top left
                {x: rect.right - margin, y: rect.top + margin},    // top right
                {x: rect.left + margin, y: rect.bottom - margin},  // bottom left
                {x: rect.right - margin, y: rect.bottom - margin},    // bottom right
            ];

            return checkPoints.some(({x, y}) => {
                try {
                    const topEl = document.elementFromPoint(x, y);
                    if (!topEl) return false;

                    let current = topEl;
                    while (current && current !== document.documentElement) {
                        if (current === element) return true;
                        current = current.parentElement;
                    }
                    return false;
                } catch (e) {
                    return true;
                }
            });
        }

        /**
         * Simplified visibility detection entry point
         * @param {HTMLElement} element Element to check
         * @returns {boolean} Whether it is visible
         */
        function isVisible(element) {
            const mediaInfo = detectMediaElement(element);

            if (mediaInfo.isMedia) {
                return isMediaElementVisible(element, mediaInfo);
            }

            // Standard element visibility detection
            const style = getComputedStyle(element);
            return (
                element.offsetWidth > 0 &&
                element.offsetHeight > 0 &&
                style?.visibility !== "hidden" &&
                style?.display !== "none"
            );
        }

        /**
         * Generates a simplified CSS selector for an element.
         *
         * This function creates a selector based on the element's tag name, ID (if available),
         * and class names. It is not guaranteed to be unique but is useful for providing
         * a human-readable identifier.
         *
         * @param {HTMLElement} elem The element for which to generate a selector.
         * @returns {string | null} A CSS selector string, or `null` if the element is invalid.
         */
        function generateSelector(elem) {
            if (!elem) return null;

            let sel = elem.tagName.toLowerCase();

            // use id first
            if (elem.id) {
                sel += `#${elem.id}`;
                return sel;
            }

            // try to get class from classList, fallback to getAttribute if not existed
            let classes = [];
            if (elem.classList && elem.classList.length > 0) {
                classes = Array.from(elem.classList);
            } else {
                const raw = elem.getAttribute('class') || '';
                classes = raw.trim().split(/\s+/).filter(Boolean);
            }

            if (classes.length > 0) {
                sel += `.${classes.join('.')}`;
            }

            return sel;
        }

        /**
         * Generates a robust XPath for an element.
         *
         * This function constructs an XPath by traversing up the DOM tree from the element.
         * It prefers using an ID if available, otherwise it builds a path based on tag names
         * and sibling indices, making the XPath stable and unique.
         *
         * @param {HTMLElement} elem The element for which to generate the XPath.
         * @returns {string} The generated XPath string.
         */
        function generateXPath(elem) {
            if (!(elem instanceof Element)) return '';
            if (elem.id) return `//*[@id=\"${elem.id}\"]`;
            const parts = [];
            while (elem && elem.nodeType === Node.ELEMENT_NODE) {
                let idx = 1;
                let sib = elem.previousElementSibling;
                while (sib) {
                    if (sib.nodeName === elem.nodeName) idx++;
                    sib = sib.previousElementSibling;
                }
                parts.unshift(elem.nodeName.toLowerCase() + `[${idx}]`);
                elem = elem.parentElement;
            }
            return '/' + parts.join('/');
        }

         /**
         * Retrieves all child container elements from the specified node
         *
         * This function is used to get child elements when traversing the DOM tree,
         * supporting multiple container types:
         * - Child elements of regular DOM elements
         * - Child elements of Shadow DOM
         * - Body element of iframe internal documents
         *
         * @param {Node|ShadowRoot} node - The node to get child containers from, can be a regular DOM node or Shadow Root
         * @returns {Array<Element>} Returns an array containing all child container elements
         */
        function getChildContainers(node) {
            const out = [];

            // Handle Shadow Root nodes
            if (node instanceof ShadowRoot) {
                out.push(...Array.from(node.children));
            }
            // Handle regular DOM element nodes
            else if (node && node.nodeType === Node.ELEMENT_NODE) {
                // Add all direct child elements
                out.push(...Array.from(node.children));

                // If the element has a Shadow Root, add it to the container list
                if (node.shadowRoot instanceof ShadowRoot) out.push(node.shadowRoot);

                // Special handling for iframe elements, attempt to get the body of their internal document
                if (node.tagName?.toLowerCase() === 'iframe') {
                    try {
                        const doc = node.contentDocument;
                        if (doc?.body) out.push(doc.body);
                    } catch (_) {
                        /* Ignore errors when cross-origin iframe access is blocked */
                    }
                }
            }

            return out;
        }

        /**
         * Clean and optimize element attributes to reduce token consumption
         * @param {HTMLElement} elem The element to process
         * @returns {Array} Cleaned attributes array
         */
        function getCleanedAttributes(elem) {
            // Configuration constants
            const CONFIG = {
                excludedAttrs: ['data-zr-dom-id', 'data-reactid', 'data-react-checksum', 'data-react-root', 'data-testid'],
                maxLengths: {
                    style: 500,
                    srcHref: 200,
                    other: 300
                },
                truncateLengths: {
                    style: 200,
                    srcHref: 100,
                    other: 150
                },
                importantStyleProps: ['position', 'display', 'width', 'height', 'left', 'top', 'z-index', 'opacity']
            };

            /**
             * Clean style attribute value
             * @param {string} styleValue Original style value
             * @returns {string} Cleaned style value
             */
            function cleanStyleValue(styleValue) {
                // Unified processing of all background image URLs
                let cleaned = styleValue
                    // Base64 images with comments
                    .replace(/background-image:\s*\/\*[^*]*original URL:\s*`([^`]+)`[^*]*\*\/\s*url\(data:image\/[^)]+\)/gi,
                        'background-image:url([base64 from: $1])')
                    // Regular base64 images
                    .replace(/background-image:\s*url\(data:image\/([^;)]+);base64,[^)]+\)/gi,
                        'background-image:url(data:image/$1;base64,[data]...)')
                    // Long URLs
                    .replace(/background-image:\s*url\(([^)]{50,})\)/gi,
                        (match, url) => `background-image:url(${url.substring(0, 50)}...)`);

                // If still too long, keep important attributes
                if (cleaned.length > CONFIG.maxLengths.style) {
                    const styles = cleaned.split(';').map(s => s.trim()).filter(s => s);
                    const important = styles.filter(style => {
                        const prop = style.split(':')[0].trim();
                        return CONFIG.importantStyleProps.some(p => prop.includes(p)) ||
                            style.includes('background-image');
                    });

                    cleaned = important.length > 0
                        ? important.join('; ') + '; /* [truncated] */'
                        : cleaned.substring(0, CONFIG.truncateLengths.style) + '...[truncated]';
                }

                return cleaned;
            }

            /**
             * Clean data URL attributes
             * @param {string} value Original attribute value
             * @param {string} attrName Attribute name
             * @returns {string} Cleaned attribute value
             */
            function cleanDataUrl(value, attrName) {
                if (value.startsWith('data:image/') && value.includes('base64,')) {
                    const [header] = value.split('base64,');
                    return `${header}base64,[data]...`;
                }

                if (value.length > CONFIG.maxLengths.srcHref) {
                    return value.substring(0, CONFIG.truncateLengths.srcHref) + '...[truncated]';
                }

                return value;
            }

            /**
             * Process single attribute
             * @param {Object} attr Attribute object with name and value
             * @returns {Object|null} Processed attribute or null if excluded
             */
            function processAttribute(attr) {
                // Exclude unimportant attributes
                if (CONFIG.excludedAttrs.includes(attr.name)) {
                    return null;
                }

                let value = attr.value;

                // Process based on attribute type
                switch (attr.name) {
                    case 'style':
                        value = cleanStyleValue(value);
                        break;

                    case 'src':
                    case 'href':
                        value = cleanDataUrl(value, attr.name);
                        break;

                    default:
                        // General length limitation
                        if (value && value.length > CONFIG.maxLengths.other) {
                            value = value.substring(0, CONFIG.truncateLengths.other) + '...[truncated]';
                        }
                }

                return {name: attr.name, value};
            }

            // Main processing logic
            return Array.from(elem.attributes)
                .map(a => ({name: a.name, value: a.value}))
                .map(processAttribute)
                .filter(attr => attr !== null);
        }

        /**
         * Retrieves all child container elements from the specified node
         *
         * This function is used to get child elements when traversing the DOM tree,
         * supporting multiple container types:
         * - Child elements of regular DOM elements
         * - Child elements of Shadow DOM
         * - Body element of iframe internal documents
         *
         * @param {Node|ShadowRoot} node - The node to get child containers from, can be a regular DOM node or Shadow Root
         * @returns {Array<Element>} Returns an array containing all child container elements
         */
        function getChildContainers(node) {
            const out = [];

            // Handle Shadow Root nodes
            if (node instanceof ShadowRoot) {
                out.push(...Array.from(node.children));
            }
            // Handle regular DOM element nodes
            else if (node && node.nodeType === Node.ELEMENT_NODE) {
                // Add all direct child elements
                out.push(...Array.from(node.children));

                // If the element has a Shadow Root, add it to the container list
                if (node.shadowRoot instanceof ShadowRoot) out.push(node.shadowRoot);

                // Special handling for iframe elements, attempt to get the body of their internal document
                if (node.tagName?.toLowerCase() === 'iframe') {
                    try {
                        const doc = node.contentDocument;
                        if (doc?.body) out.push(doc.body);
                    } catch (_) {
                        /* Ignore errors when cross-origin iframe access is blocked */
                    }
                }
            }

            return out;
        }

        /**
         * Gathers comprehensive information about a DOM element.
         *
         * This function collects a wide range of properties for an element, including its identity,
         * attributes, layout, visibility, interactivity, and position. This data is used to
         * build the DOM tree and determine which elements to highlight.
         *
         * @param {HTMLElement} elem The element to gather information from.
         * @param {boolean} isParentHighlighted A flag indicating if an ancestor of this element is highlighted.
         * @returns {object} An object containing detailed information about the element.
         */
        function getElementInfo(elem, isParentHighlighted) {
            const r = elem.getBoundingClientRect();
            const sx = window.pageXOffset || document.documentElement.scrollLeft;
            const sy = window.pageYOffset || document.documentElement.scrollTop;
            let txt = '';

            elem.childNodes.forEach(c => {
                if (c.nodeType === Node.TEXT_NODE) txt += c.textContent.trim();
            });

            return {
                // id: getElementId(elem),
                node: elem,
                tagName: elem.tagName.toLowerCase(),
                className: elem.getAttribute('class') || null,
                type: elem.getAttribute('type') || null, placeholder: elem.getAttribute('placeholder') || null,
                innerText: txt || (elem.innerText || elem.value || '').trim(),
                attributes: getCleanedAttributes(elem),

                viewport: {x: r.left + sx, y: r.top + sy, width: r.width, height: r.height},
                center_x: r.left + r.width / 2 + sx,
                center_y: r.top + r.height / 2 + sy,

                isVisible: isVisible(elem),
                isInteractive: isInteractiveElement(elem),
                isValidText: isValidTextElement(elem),
                isMediaElement: isMediaElement(elem),
                isTopElement: isTopElement(elem),
                isInViewport: !(r.bottom < 0 || r.top > window.innerHeight || r.right < 0 || r.left > window.innerWidth),

                isParentHighlighted: isParentHighlighted,
                xpath: generateXPath(elem),
                selector: generateSelector(elem),
                styles: getStyleSubset(elem)
            };
        }

        // ============================= Highlight Element =============================
        /**
         * Selects a random color from a predefined palette.
         *
         * @returns {string} A hexadecimal color string.
         */
        function randomColor() {
            return palette[Math.floor(Math.random() * palette.length)];
        }

        /**
         * Determines whether an element should be highlighted based on current settings and its properties.
         *
         * This function applies a set of rules to decide if an element qualifies for highlighting.
         * It checks for visibility, viewport presence, interactivity, and text content based on
         * the global `_viewportOnly` and `_highlightText` flags. It also prevents highlighting
         * nested non-distinct elements if a parent is already highlighted.
         *
         * @param {object} elemInfo The information object for the element, from `getElementInfo`.
         * @param {HTMLElement} elemObj The actual DOM element.
         * @param {boolean} isParentHighlighted `true` if an ancestor of this element is already highlighted.
         * @returns {boolean} `true` if the element should be highlighted, otherwise `false`.
         */
        function handleHighlighting(elemInfo, elemObj, isParentHighlighted) {
            function shouldHighlightElem(nodeInfo) {
                // Media element highlighting mode
                if (window._filterMedia) {
                    return nodeInfo.isMediaElement && nodeInfo.isVisible && nodeInfo.isTopElement;
                }

                // Special handling for menu containers
                const role = elemObj.getAttribute('role');
                if (['menu', 'menubar', 'listbox'].includes(role)) return true;

                // Text highlighting mode
                if (window._filterText) {
                    return nodeInfo.isVisible && nodeInfo.isTopElement && nodeInfo.isValidText;
                }

                // Interactive element highlighting mode (default)
                return nodeInfo.isVisible && nodeInfo.isTopElement && nodeInfo.isInteractive;
            }

            // 1) Basic filter
            if (!shouldHighlightElem(elemInfo)) return false;

            // 2) Nested filtering logic
            // Media element mode: skip if parent is highlighted and current is not distinct interaction boundary
            if (window._filterText) {
                if (isParentHighlighted && !elemInfo.isInteractive) return false;
            } else {
                if (!window._filterMedia) {
                    if (isParentHighlighted && !isElementDistinctInteraction(elemObj)) return false;
                }
            }

            if (highlightMap.has(elemObj)) {
                elemInfo.highlightIndex = highlightMap.get(elemObj);
            } else {
                elemInfo.highlightIndex = highlightIndex;
                highlightMap.set(elemObj, highlightIndex);
                highlightIndex += 1;
            }

            return true;
        }

        /**
         * Renders visual highlights for elements in the processed DOM tree.
         *
         * This function iterates through the tree and draws colored boxes and labels on an overlay
         * for each element that has been marked for highlighting. It clears and redraws the
         * highlights, making it suitable for dynamic updates on scroll or resize.
         *
         * @param {object} tree The root of the element tree to render.
         */
        function renderHighlights(tree) {
            overlayContainer.textContent = '';
            (function walk(node) {
                if (!node) return;

                if (node.node) {
                    const info = node.node;
                    const elem = info.node;
                    const rects = Array.from(elem.getClientRects()).filter(r => r.width >= 2 && r.height >= 2);
                    if (rects.length === 0) return;

                    // 1. Color: assign a fixed color for each element
                    let color = _elementHighlightColorMap.get(elem);
                    if (!color) {
                        color = randomColor();
                        _elementHighlightColorMap.set(elem, color);
                    }

                    // 2. Draw box for each rect (maintain visual consistency for multi-line/multi-rect elements)
                    rects.forEach(r => {
                        const box = document.createElement('div');
                        Object.assign(box.style, {
                            position: 'fixed',
                            top: `${r.top}px`,
                            left: `${r.left}px`,
                            width: `${r.width}px`,
                            height: `${r.height}px`,
                            outline: `2px dashed ${color}`,
                            boxSizing: 'border-box',
                            pointerEvents: 'none'
                        });
                        overlayContainer.appendChild(box);
                    });

                    // 3. Calculate union rect as fallback and external positioning reference
                    const union = rects.reduce((acc, r) => {
                        if (!acc) {
                            return {
                                top: r.top,
                                left: r.left,
                                right: r.right,
                                bottom: r.bottom
                            };
                        }
                        return {
                            top: Math.min(acc.top, r.top),
                            left: Math.min(acc.left, r.left),
                            right: Math.max(acc.right, r.right),
                            bottom: Math.max(acc.bottom, r.bottom)
                        };
                    }, null);
                    if (!union) return;

                    // 4. Create label (hidden first for measurement)
                    const label = document.createElement('div');
                    label.textContent = info.highlightIndex;
                    Object.assign(label.style, {
                        position: 'fixed',
                        backgroundColor: color,
                        color: '#fff',
                        fontSize: '10px',
                        padding: '1px 2px',
                        borderRadius: '3px',
                        pointerEvents: 'none',
                        visibility: 'hidden',
                        whiteSpace: 'nowrap',
                        boxSizing: 'border-box'
                    });
                    overlayContainer.appendChild(label);
                    const labelRect = label.getBoundingClientRect();

                    // 5. Positioning: prioritize placing in the top-right corner of the first rect, with fallback logic from index.js
                    const firstRect = rects[0];
                    let labelTop = firstRect.top + 2; // slightly below the internal top
                    let labelLeft = firstRect.left + firstRect.width - labelRect.width - 2; // right-aligned

                    // If it doesn't fit (first rect is too small), place above the rect, right-aligned
                    if (firstRect.width < labelRect.width + 4 || firstRect.height < labelRect.height + 4) {
                        labelTop = firstRect.top - labelRect.height - 2;
                        labelLeft = firstRect.left + firstRect.width - labelRect.width - 2;
                    }

                    // Final fallback: if still overflowing or in very crowded scenarios, fallback to union's top-left interior
                    if (labelLeft < 0 || labelTop < 0 || labelLeft + labelRect.width > window.innerWidth) {
                        // Inside union's top-left
                        labelLeft = union.left + 2;
                        labelTop = union.top + 2;
                    }

                    // Clamp to viewport
                    labelTop = Math.max(0, Math.min(labelTop, window.innerHeight - labelRect.height));
                    labelLeft = Math.max(0, Math.min(labelLeft, window.innerWidth - labelRect.width));

                    label.style.left = `${labelLeft}px`;
                    label.style.top = `${labelTop}px`;
                    label.style.visibility = 'visible';
                }

                node.children.forEach(walk);
            })(tree, false);
        }

        // ============================= Build Dom Tree =============================
        /**
         * Recursively builds a structured tree representing the DOM.
         *
         * This is the core function for crawling the DOM. It starts from a given element (usually the body),
         * gathers information for each node, determines if it should be highlighted, and recursively
         * processes its children. The resulting tree contains only the elements that are either
         * highlighted themselves or contain highlighted descendants.
         *
         * @param {HTMLElement} elemObj The DOM element to start building the tree from.
         * @param {boolean} [wasParentHighlighted=false] A flag passed during recursion to indicate if an ancestor was highlighted.
         * @returns {object | null} A tree node object, or `null` if the element and its descendants are not relevant.
         */
        function buildTree(elemObj, wasParentHighlighted = false) {
            // If it is a ShadowRoot, use host as element info; otherwise use the element itself
            const infoTarget = (elemObj instanceof ShadowRoot) ? elemObj.host : elemObj;

            // get element info
            const elemInfo = getElementInfo(infoTarget, wasParentHighlighted);

            // Highlight check
            const isCurNodeHighlighted = elemInfo ? handleHighlighting(elemInfo, infoTarget, wasParentHighlighted) : false;
            const isParentHighlighted = wasParentHighlighted || isCurNodeHighlighted;

            // Recursively process “container” child nodes: Element children, shadowRoot, and same-origin iframe
            const children = [];
            for (const child of getChildContainers(elemObj)) {
                const subtree = buildTree(child, isParentHighlighted);
                if (subtree) children.push(subtree);
            }

            // highlight filter
            if (isCurNodeHighlighted) {
                highlightIdMap[elemInfo.highlightIndex] = elemInfo;  // map highlightIndex to element info
                return {node: elemInfo, children};
            } else if (children.length > 0) {
                return {node: null, children};                       // child node is highlightable
            }
            return null;
        }

        // ============================= Main Function =============================
        /**
         * The main entry point for building and processing the element tree.
         *
         * This function initializes the process, calls `buildTree` to construct the DOM representation,
         * and optionally triggers the rendering of highlights. It also sets up event listeners
         * to re-render highlights on scroll and resize events to keep them in sync with the layout.
         *
         * @returns {[object, object]} A tuple containing the generated DOM tree and the map of highlight indices to element info.
         */
        window.buildElementTree = function () {
            highlightIdMap = {};
            const tree = buildTree(document.body);

            if (window._highlight) {
                renderHighlights(tree);
                window.addEventListener('scroll', () => renderHighlights(tree), {passive: true, capture: true});
                window.addEventListener('resize', () => renderHighlights(tree));
            }
            return [tree, highlightIdMap];
        }
    }
)();
