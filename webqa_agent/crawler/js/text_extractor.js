() => {
    // 基础可见性检查
    function isVisible(element) {
        if (!element || !element.getBoundingClientRect) return false;
        const rect = element.getBoundingClientRect();
        const style = window.getComputedStyle(element);

        return rect.width > 3 &&
               rect.height > 3 &&
               style.display !== 'none' &&
               style.visibility !== 'hidden' &&
               style.opacity !== '0' &&
               parseFloat(style.opacity) > 0;
    }

    // 检查元素是否是最顶层的（模仿 element_detector.js 的实现）
    function isTopElement(elem) {
        const rect = elem.getBoundingClientRect();
        // 如果元素在视口外，返回 true（处理边界情况）
        if (rect.right < 0 || rect.left > window.innerWidth || rect.bottom < 0 || rect.top > window.innerHeight) {
            return true;
        }

        // 计算元素中心点坐标
        const cx = rect.left + rect.width / 2;
        const cy = rect.top + rect.height / 2;

        try {
            // 获取在该中心点位置的最顶层元素
            const topEl = document.elementFromPoint(cx, cy);
            let curr = topEl;

            // 检查该元素或其父级是否包含目标元素
            while (curr && curr !== document.documentElement) {
                if (curr === elem) return true;
                curr = curr.parentElement;
            }
            return false;
        } catch {
            return true;
        }
    }

    // 检查元素是否有实际内容
    function hasContent(element) {
        // 文本内容检查
        const text = element.innerText || '';
        if (text.trim().length > 1 && !/^\d+$/.test(text.trim())) {
            return true;
        }

        // 检查是否是有意义的元素类型
        const tagName = element.tagName.toLowerCase();
        if (['a', 'button', 'input', 'select', 'textarea', 'img',
             'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'li'].includes(tagName)) {
            return true;
        }

        // 检查是否有样式类名，表明可能有语义
        if (element.className && typeof element.className === 'string' && element.className.length > 0) {
            return true;
        }

        // 检查是否有交互属性
        if (element.getAttribute('role') ||
            element.getAttribute('aria-label') ||
            element.onclick ||
            element.getAttribute('onclick') ||
            element.getAttribute('href') ||
            element.getAttribute('tabindex') !== null) {
            return true;
        }

        return false;
    }

    // 提取元素文本内容
    function getElementText(element) {
        // 如果是输入元素，获取其值或占位符
        if (element.tagName.toLowerCase() === 'input' ||
            element.tagName.toLowerCase() === 'textarea') {
            return element.value || element.placeholder || '';
        }

        // 优先获取整个元素的innerText，这样可以包含子元素的文本
        let textContent = element.innerText?.trim() || '';

        // 如果innerText为空，尝试获取元素的直接文本内容
        if (!textContent) {
            for (const node of element.childNodes) {
                if (node.nodeType === Node.TEXT_NODE) {
                    const trimmed = node.textContent.trim();
                    if (trimmed) textContent += trimmed + ' ';
                }
            }
            textContent = textContent.trim();
        }

        return textContent;
    }

    // 检查文本是否有意义
    function isMeaningfulText(text) {
        // 排除只有数字的文本（可能是分页或列表编号）
        if (/^[0-9]+$/.test(text)) {
            return false;
        }

        // 排除太短的文本
        if (text.length < 3) {
            return false;
        }

        return true;
    }

    // 收集页面上所有可见元素的文本信息
    function collectTextElements(rootElement) {
        const textElements = [];
        const processedTexts = new Set(); // 用于去重

        function processElement(element) {
            // 检查元素是否可见且是最顶层的
            if (!element || !isVisible(element) || !isTopElement(element)) return;

            // 获取元素的文本内容
            const text = getElementText(element);

            // 如果当前元素有有意义的文本内容，收集它并跳过子元素处理
            if (text && isMeaningfulText(text) && !processedTexts.has(text)) {
                const rect = element.getBoundingClientRect();
                processedTexts.add(text);

                textElements.push({
                    text,
                    tag: element.tagName.toLowerCase(),
                    position: {
                        x: Math.round(rect.left),
                        y: Math.round(rect.top),
                        width: Math.round(rect.width),
                        height: Math.round(rect.height)
                    }
                });

                // 如果当前元素有有意义的文本，就不再处理子元素，避免重复
                return;
            }

            // 只有当前元素没有有意义的文本时，才递归处理子元素
            for (const child of element.children) {
                processElement(child);
            }
        }

        processElement(rootElement);
        return textElements;
    }

    // 主函数：提取页面内容
    function extractPageContent() {
        // 获取页面元数据
        const metadata = {
            title: document.title,
            url: window.location.href,
            size: {
                width: window.innerWidth,
                height: window.innerHeight,
                scrollHeight: document.documentElement.scrollHeight
            }
        };

        // 收集所有文本元素
        const textElements = collectTextElements(document.body);

        return {
            metadata,
            textElements
        };
    }

    return extractPageContent();
}
