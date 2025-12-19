/*
 * Extract page elements
 * Only highlight elements satisfying isVisible, isInteractive, isTopElement
 */

(function () {
        window._highlightEnabled = window._highlightEnabled ?? true;  // RenderHighlight Switch
        let idCounter = 1;
        // Support per-frame numbering base to avoid ID collisions across frames
        // If window.__highlightBase__ is provided, start indices from base + 1
        // let highlightIndex = 1;
        let highlightIndex = (typeof window.__highlightBase__ === 'number' ? window.__highlightBase__ : 0) + 1;
        const elementToId = new WeakMap();
        const highlightMap = new WeakMap();
        let highlightIdMap = new WeakMap();
        const styleCache = new WeakMap();
        const _elementHighlightColorMap = new WeakMap();
        const INTERACTIVE_TAGS = new Set(['a', 'button', 'input', 'select', 'textarea', 'summary', 'details', 'label', 'option']);
        const INTERACTIVE_ROLES = new Set(['button', 'link', 'menuitem', 'menuitemradio', 'menuitemcheckbox', 'radio', 'checkbox', 'tab', 'switch', 'slider', 'spinbutton', 'combobox', 'searchbox', 'textbox', 'listbox', 'option', 'scrollbar']);
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

        // ============================= Extract Element Info =============================
        function getElementId(elem) {
            if (!elementToId.has(elem)) elementToId.set(elem, idCounter++);
            return elementToId.get(elem);
        }

        function getCachedStyle(elem) {
            let s = styleCache.get(elem);
            if (!s) {
                s = window.getComputedStyle(elem);
                styleCache.set(elem, s);
            }
            return s;
        }

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

        function isInteractiveElement(element) {
            if (!element || element.nodeType !== Node.ELEMENT_NODE) {
                return false;
            }

            // Cache the tagName and style lookups
            const tagName = element.tagName.toLowerCase();
            const style = getCachedStyle(element);
            // const style = window.getComputedStyle(element);

            if (['textarea', 'i', 'span', 'a', 'input', 'button', 'svg','img'].includes(tagName)) {
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

            // if (element.hasAttribute("aria-expanded") ||
            //     element.hasAttribute("aria-pressed") ||
            //     element.hasAttribute("aria-selected") ||
            //     element.hasAttribute("aria-checked")) {
            //     return true;
            // }

            // check whether element has event listeners
            try {
                if (typeof getEventListeners === 'function') {
                    const listeners = getEventListeners(element);
                    const mouseEvents = ['click', 'mousedown', 'mouseup', 'dblclick', 'ng-click', '@click'];
                    for (const eventType of mouseEvents) {
                        if (listeners[eventType] && listeners[eventType].length > 0) {
                            return true; // Found a mouse interaction listener
                        }
                    }
                } else {
                    // Fallback: Check common event attributes if getEventListeners is not available
                    const commonMouseAttrs = ['onclick', 'onmousedown', 'onmouseup', 'ondblclick'];
                    if (commonMouseAttrs.some(attr => element.hasAttribute(attr))) {
                        return true;
                    }
                }
            } catch (e) {
            }

            return false
        }

        function isTopElement(elem) {
            const rect = elem.getBoundingClientRect();
            if (rect.right < 0 || rect.left > window.innerWidth || rect.bottom < 0 || rect.top > window.innerHeight) {
                return true;
            }
            const cx = rect.left + rect.width / 2;
            const cy = rect.top + rect.height / 2;
            try {
                const topEl = document.elementFromPoint(cx, cy);
                let curr = topEl;
                while (curr && curr !== document.documentElement) {
                    if (curr === elem) return true;
                    curr = curr.parentElement;
                }
                return false;
            } catch {
                return true;
            }
        }

        function isVisible(elem) {
            const r = elem.getBoundingClientRect();
            const style = window.getComputedStyle(elem);
            return r.width > 0 && r.height > 0 && style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
        }

        function shouldHighlightInfo(nodeInfo) {
            return nodeInfo.isVisible && nodeInfo.isInteractive && nodeInfo.isTopElement;
        }

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
                isTopElement: isTopElement(elem),
                isInViewport: !(r.bottom < 0 || r.top > window.innerHeight || r.right < 0 || r.left > window.innerWidth),

                isParentHighlighted: isParentHighlighted,
                xpath: generateXPath(elem),
                selector: generateSelector(elem)
            };
        }

        // ============================= Highlight Element =============================
        function randomColor() {
            return palette[Math.floor(Math.random() * palette.length)];
        }

        function handleHighlighting(elemInfo, elemObj, parentIframe, isParentHighlighted) {
            // 1) basic filter
            if (!shouldHighlightInfo(elemInfo)) return false;

            // 2) skip if parent is highlighted and is not distinct interaction
            if (isParentHighlighted && !isElementDistinctInteraction(elemObj)) return false;

            // 3) (optional) highlight only within viewport
            // if (!elemInfo.isInViewport && elemInfo.viewportExpansion !== -1) return false;

            if (highlightMap.has(elemObj)) {
                elemInfo.highlightIndex = highlightMap.get(elemObj);
            } else {
                elemInfo.highlightIndex = highlightIndex;
                highlightMap.set(elemObj, highlightIndex);
                highlightIndex += 1;
            }

            return true;
        }

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
        function buildTree(elemObj, wasParentHighlighted = false) {
            // 1) get element info
            const elemInfo = getElementInfo(elemObj, wasParentHighlighted);

            // 2) check node satisfies highlight condition
            const isCurNodeHighlighted = handleHighlighting(elemInfo, elemObj, null, wasParentHighlighted)
            const isParentHighlighted = wasParentHighlighted || isCurNodeHighlighted;

            // 3) recursively build structured dom tree, with 'isParentHighlighted' state
            const children = [];
            Array.from(elemObj.children).forEach(child => {
                const subtree = buildTree(child, isParentHighlighted);
                if (subtree) children.push(subtree);
            });

            // 4) highlight filter
            if (isCurNodeHighlighted) {
                highlightIdMap[elemInfo.highlightIndex] = elemInfo;     // map highlightIndex to element info
                return {node: elemInfo, children};                      // keep info if is highlightable
            } else if (children.length > 0) {
                return {node: null, children};                          // child node is highlightable
            } else {
                return null;                                            // skip
            }
        }

        // ============================= Main Function =============================
        window.buildElementTree = function () {
            highlightIdMap = {};
            const tree = buildTree(document.body);

            if (window._highlightEnabled) {
                renderHighlights(tree);
                window.addEventListener('scroll', () => renderHighlights(tree), {passive: true, capture: true});
                window.addEventListener('resize', () => renderHighlights(tree));
            }
            return [tree, highlightIdMap];
        }
    }
)();
