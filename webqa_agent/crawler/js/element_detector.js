// This file is modified from:
// https://github.com/browser-use/browser-use/browser_use/dom/dom_tree/index.js
//
// Copyright (c) 2024 Gregor Zunic
//
// Licensed under the MIT License

(function () {
        window._highlight = window._highlight ?? true;            // RenderHighlight Switch
        window._highlightText = window._highlightText ?? false;   // RenderTextHighlight Switch
        window._viewportOnly = window._viewportOnly ?? false;     // Highlight Viewport Elements
        let idCounter = 1;
        let highlightIndex = 1;
        const elementToId = new WeakMap();
        const highlightMap = new WeakMap();
        let highlightIndexMap = new WeakMap();
        const styleCache = new WeakMap();
        const INTERACTIVE_TAGS = new Set(['a', 'button', 'input', 'select', 'textarea', 'summary', 'details', 'label', 'option']);
        const INTERACTIVE_ROLES = new Set(['button', 'link', 'menuitem', 'menuitemradio', 'menuitemcheckbox', 'radio', 'checkbox', 'tab', 'switch', 'slider', 'spinbutton', 'combobox', 'searchbox', 'textbox', 'listbox', 'option', 'scrollbar']);
        const palette = ['#e6194b', '#3cb44b', '#ffe119', '#4363d8', '#f58231', '#911eb4', '#46f0f0', '#f032e6', '#bcf60c', '#fabebe', '#008080', '#e6beff'];  // highlight colors
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
            if (!elementToId.has(elem)) {
                elementToId.set(elem, idCounter++);
            }
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
         * Determines if an element is considered interactive.
         *
         * An element is deemed interactive if it meets any of the following criteria:
         * 1. Is an inherently interactive HTML tag (e.g., <a>, <button>, <input>).
         * 2. Has an ARIA role that implies interactivity (e.g., 'button', 'link').
         * 3. Is focusable via a non-negative `tabindex`.
         * 4. Has specific event listeners attached (e.g., 'click', 'keydown').
         * 5. Has a 'pointer' cursor style, suggesting it's clickable.
         * 6. Is content-editable.
         *
         * @param {HTMLElement} element The element to evaluate.
         * @returns {boolean} `true` if the element is interactive, otherwise `false`.
         */
        function isInteractiveElement(element) {
            if (!element || element.nodeType !== Node.ELEMENT_NODE) {
                return false;
            }

            const tagName = element.tagName.toLowerCase();
            const style = getCachedStyle(element);
            // const style = window.getComputedStyle(element);

            if (['textarea', 'i', 'span', 'a', 'input', 'button', 'svg', 'img'].includes(tagName)) {
                return true;
            }

            // if (tagName === 'svg' || tagName === 'path' || tagName === 'use') {
            //     return true;
            // }
            //
            // if (element.closest('button, [role="button"]')) {
            //     return true;
            // }

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

                // if (element.hasAttribute('aria-label') || element.hasAttribute('title')) {
                //     return true;
                // }

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
                interactiveRoles.has(role) ||
                interactiveRoles.has(ariaRole);

            if (hasInteractiveRole) return true;

            if (element.onclick !== null ||
                element.getAttribute("onclick") !== null ||
                element.hasAttribute("ng-click") ||
                element.hasAttribute("@click")) {
                return true;
            }


            // check whether element has event listeners
            try {
                if (typeof getEventListeners === 'function') {
                    const listeners = getEventListeners(element);
                    const mouseEvents = ['click', 'mousedown', 'mouseup', 'dblclick'];
                    for (const eventType of mouseEvents) {
                        if (listeners[eventType] && listeners[eventType].length > 0) {
                            return true;
                        }
                    }
                }
            } catch (e) {
                // Ignore errors, as this is a best-effort check.
            }

            return false;
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

            // An iframe is always a distinct boundary.
            if (tagName === 'iframe') {
                return true;
            }

            // Standard interactive elements are distinct.
            if (INTERACTIVE_TAGS.has(tagName) || (role && INTERACTIVE_ROLES.has(role))) {
                return true;
            }

            // Content-editable elements are distinct.
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
                const getEventListeners = window.getEventListenersForNode;
                if (typeof getEventListeners === 'function') {
                    const listeners = getEventListeners(element);
                    const interactionEvents = ['mousedown', 'mouseup', 'keydown', 'keyup', 'submit', 'change', 'input', 'focus', 'blur'];
                    for (const eventType of interactionEvents) {
                        if (listeners[eventType] && listeners[eventType].length > 0) {
                            return true; // Found a common interaction listener
                        }
                    }
                } else {
                    // Fallback: Check common event attributes if getEventListeners is not available
                    const commonEventAttrs = ['onmousedown', 'onmouseup', 'onkeydown', 'onkeyup', 'onsubmit', 'onchange', 'oninput', 'onfocus', 'onblur'];
                    if (commonEventAttrs.some(attr => element.hasAttribute(attr))) {
                        return true;
                    }
                }
            } catch (e) {

            }

            return false;
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

            const style = getCachedStyle(element);
            const tagName = element.tagName.toLowerCase();

            // 1. Check visibility
            if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
                return false;
            }

            // 2. non-empty text
            const text = (element.innerText || element.textContent || '').trim();
            if (!text) return false;

            // 3. structural element
            const structuralTags = new Set([
                'html', 'body', 'section', 'header', 'footer', 'main', 'nav', 'article', 'aside', 'template', 'iframe'
            ]);
            if (structuralTags.has(tagName)) {
                return false;
            }

            // 4. Check the element's area size
            const rect = element.getBoundingClientRect();
            const vw = window.innerWidth, vh = window.innerHeight;
            const areaRatio = (rect.width * rect.height) / (vw * vh);
            if (areaRatio > 0.6) return false;

            // 5. If the element itself is interactive, let isInteractiveElement handle it.
            //    Avoid duplicate processing of text information here.
            if (isInteractiveElement(element)) return false;

            // 6. Final check passed; consider this a meaningful text node.
            return true;
        }

        /**
         * Checks if an element is the top-most element at its center point.
         *
         * This function determines if the given element is the one that would receive a click
         * at its geometric center. It is useful for filtering out occluded or overlaid elements.
         *
         * @param {HTMLElement} elem The element to check.
         * @returns {boolean} `true` if the element is on top, otherwise `false`.
         */
        function isTopElement(elem) {
            const rect = elem.getBoundingClientRect();
            if (rect.right < 0 || rect.left > window.innerWidth || rect.bottom < 0 || rect.top > window.innerHeight) {
                return true;
            }
            const cx = rect.left + rect.width / 2;
            const cy = rect.top + rect.height / 2;
            try {
                const topElem = document.elementFromPoint(cx, cy);
                let curr = topElem;
                while (curr && curr !== document.documentElement) {
                    if (curr === elem) return true;
                    curr = curr.parentElement;
                }
                return false;
            } catch {
                return true;
            }
        }

        /**
         * Checks if an element is currently visible in the DOM.
         *
         * Visibility is determined by the element's dimensions (width and height > 0) and
         * its CSS properties (`display`, `visibility`, `opacity`).
         *
         * @param {HTMLElement} elem The element to check.
         * @returns {boolean} `true` if the element is visible, otherwise `false`.
         */
        function isVisible(elem) {
            const r = elem.getBoundingClientRect();
            const style = window.getComputedStyle(elem);
            return r.width > 0 && r.height > 0 && style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
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
                id: getElementId(elem),
                node: elem,
                tagName: elem.tagName.toLowerCase(),
                className: elem.getAttribute('class') || null,
                type: elem.getAttribute('type') || null, placeholder: elem.getAttribute('placeholder') || null,
                innerText: txt || (elem.innerText || elem.value || '').trim(),
                attributes: Array.from(elem.attributes).map(a => ({name: a.name, value: a.value})),

                viewport: {x: r.left + sx, y: r.top + sy, width: r.width, height: r.height},
                center_x: r.left + r.width / 2 + sx,
                center_y: r.top + r.height / 2 + sy,

                isVisible: isVisible(elem),
                isInteractive: isInteractiveElement(elem),
                isValidText: isValidTextElement(elem),
                isTopElement: isTopElement(elem),
                isInViewport: !(r.bottom < 0 || r.top > window.innerHeight || r.right < 0 || r.left > window.innerWidth),

                isParentHighlighted: isParentHighlighted,
                xpath: generateXPath(elem),
                selector: generateSelector(elem)
            };
        }

        // ============================= Highlight Element =============================

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
                if (window._viewportOnly === true && !nodeInfo.isInViewport) return false;

                if (window._highlightText) {
                    return nodeInfo.isVisible && nodeInfo.isTopElement && nodeInfo.isValidText;
                } else {
                    return nodeInfo.isVisible && nodeInfo.isTopElement && nodeInfo.isInteractive;
                }
            }


            // initial filter
            if (!shouldHighlightElem(elemInfo)) return false;

            // skip if parent is highlighted and is not distinct interaction
            if (window._highlightText) {
                if (isParentHighlighted && !elemInfo.isInteractive) return false
            } else {
                if (isParentHighlighted && !isElementDistinctInteraction(elemObj)) return false;
            }

            // set highlight index
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
         * Selects a random color from a predefined palette.
         *
         * @returns {string} A hexadecimal color string.
         */
        function randomColor() {
            return palette[Math.floor(Math.random() * palette.length)];
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

                // try to highlight if this layer has real dom node
                if (node.node) {
                    const info = node.node;
                    const elem = info.node;
                    Array.from(elem.getClientRects()).forEach(r => {
                        if (r.width < 2 || r.height < 2) return;
                        const color = randomColor();

                        // draw box
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

                        // draw label
                        const label = document.createElement('div');
                        label.textContent = info.highlightIndex;
                        Object.assign(label.style, {
                            position: 'fixed',
                            backgroundColor: color,
                            color: '#fff',
                            fontSize: '12px',
                            padding: '2px 4px',
                            borderRadius: '3px',
                            pointerEvents: 'none'
                        });
                        overlayContainer.appendChild(label);
                        const lr = label.getBoundingClientRect();
                        let lx = r.left - lr.width - 5;
                        if (lx < 0) lx = r.left + r.width + 5;
                        const ly = r.top + (r.height - lr.height) / 2;
                        label.style.left = `${lx}px`;
                        label.style.top = `${ly}px`;
                    });

                }

                // continue to travel child node
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
            // 1) get element info
            const elemInfo = getElementInfo(elemObj, wasParentHighlighted);

            // 2) check node satisfies highlight condition
            const isCurNodeHighlighted = handleHighlighting(elemInfo, elemObj, wasParentHighlighted)
            const isParentHighlighted = wasParentHighlighted || isCurNodeHighlighted;

            // 3) recursively build structured dom tree, with 'isParentHighlighted' state
            const children = [];
            Array.from(elemObj.children).forEach(child => {
                const subtree = buildTree(child, isParentHighlighted);
                if (subtree) children.push(subtree);
            });

            // 4) highlight filter
            if (isCurNodeHighlighted) {
                highlightIndexMap[elemInfo.highlightIndex] = elemInfo;     // map highlightIndex to element info
                return {node: elemInfo, children};                      // highlightable node
            } else if (children.length > 0) {
                return {node: null, children};
            } else {
                return null;
            }
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
            highlightIndexMap = {};
            const domTree = buildTree(document.body);

            if (window._highlight) {
                renderHighlights(domTree);
                window.addEventListener('scroll', () => renderHighlights(domTree), {passive: true, capture: true});
                window.addEventListener('resize', () => renderHighlights(domTree));
            }

            return [domTree, highlightIndexMap];
        }
    }
)();
