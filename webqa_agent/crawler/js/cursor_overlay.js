/**
 * WebQA Agent Cursor Overlay
 *
 * Exposed API (all no-op safe via optional chaining):
 *   window.__webqa_cursor_move(x, y)  - animate cursor to viewport coords
 *   window.__webqa_cursor_click()     - show click ripple at current position
 *   window.__webqa_cursor_hide()      - hide cursor (e.g. before screenshot)
 *   window.__webqa_cursor_show()      - restore cursor visibility
 */
(() => {
    if (window.__webqa_cursor_active) return;
    window.__webqa_cursor_active = true;

    // --- Configuration ---
    const CURSOR_SIZE = 32;
    const MOVE_DURATION = '0.55s';   // CSS transition duration for movement
    const CLICK_RIPPLE_SIZE = 50;    // px, max diameter of click ripple

    // SVG arrow pointer — larger, with drop shadow for visibility on any background
    const CURSOR_SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="${CURSOR_SIZE}" height="${CURSOR_SIZE}" viewBox="0 0 24 24">
        <defs><filter id="__wcs"><feDropShadow dx="1" dy="1" stdDeviation="1.2" flood-opacity="0.45"/></filter></defs>
        <path d="M5 3l14 8-6.5 1.5L11 19z" fill="#fff" stroke="#E53935" stroke-width="1.5" filter="url(#__wcs)"/>
    </svg>`;

    // --- Cursor element ---
    const cursor = document.createElement('div');
    cursor.id = '__webqa_cursor__';
    Object.assign(cursor.style, {
        position: 'fixed',
        top: '0px',
        left: '0px',
        width: `${CURSOR_SIZE}px`,
        height: `${CURSOR_SIZE}px`,
        zIndex: '2147483646',
        pointerEvents: 'none',
        transition: `left ${MOVE_DURATION} cubic-bezier(.4,0,.2,1), top ${MOVE_DURATION} cubic-bezier(.4,0,.2,1)`,
        willChange: 'left, top',
        opacity: '0',
    });
    cursor.innerHTML = CURSOR_SVG;

    // --- Ripple container ---
    const ripple = document.createElement('div');
    ripple.id = '__webqa_cursor_ripple__';
    Object.assign(ripple.style, {
        position: 'fixed',
        width: '0px',
        height: '0px',
        borderRadius: '50%',
        border: '2.5px solid rgba(229, 57, 53, 0.75)',
        backgroundColor: 'rgba(229, 57, 53, 0.12)',
        pointerEvents: 'none',
        zIndex: '2147483645',
        opacity: '0',
        transform: 'translate(-50%, -50%)',
    });

    function ensureAttached() {
        if (!document.getElementById('__webqa_cursor__')) {
            document.documentElement.appendChild(cursor);
        }
        if (!document.getElementById('__webqa_cursor_ripple__')) {
            document.documentElement.appendChild(ripple);
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', ensureAttached);
    } else {
        ensureAttached();
    }

    let curX = 0, curY = 0;
    let firstMove = true;

    const TRANSITION_VALUE = `left ${MOVE_DURATION} cubic-bezier(.4,0,.2,1), top ${MOVE_DURATION} cubic-bezier(.4,0,.2,1)`;

    // --- Public API ---

    window.__webqa_cursor_move = function(x, y) {
        ensureAttached();
        curX = x;
        curY = y;

        if (firstMove) {
            cursor.style.transition = 'none';
            cursor.style.left = `${x}px`;
            cursor.style.top = `${y}px`;
            cursor.style.opacity = '1';
            void cursor.offsetWidth;
            cursor.style.transition = TRANSITION_VALUE;
            firstMove = false;
            return Promise.resolve();
        }

        cursor.style.left = `${x}px`;
        cursor.style.top = `${y}px`;
        cursor.style.opacity = '1';

        // Return a Promise that resolves when CSS transition ends
        return new Promise((resolve) => {
            const onEnd = (e) => {
                if (e.propertyName === 'left') {
                    cursor.removeEventListener('transitionend', onEnd);
                    resolve();
                }
            };
            cursor.addEventListener('transitionend', onEnd);
            setTimeout(() => { cursor.removeEventListener('transitionend', onEnd); resolve(); }, 700);
        });
    };

    window.__webqa_cursor_click = function() {
        ensureAttached();
        ripple.style.left = `${curX}px`;
        ripple.style.top = `${curY}px`;
        ripple.style.width = '0px';
        ripple.style.height = '0px';
        ripple.style.opacity = '1';
        ripple.style.transition = 'none';

        void ripple.offsetWidth;
        ripple.style.transition = 'width 0.35s ease-out, height 0.35s ease-out, opacity 0.35s ease-out';
        ripple.style.width = `${CLICK_RIPPLE_SIZE}px`;
        ripple.style.height = `${CLICK_RIPPLE_SIZE}px`;
        ripple.style.opacity = '0';
    };

    window.__webqa_cursor_hide = function() {
        cursor.style.visibility = 'hidden';
    };

    window.__webqa_cursor_show = function() {
        cursor.style.visibility = 'visible';
    };
})();
