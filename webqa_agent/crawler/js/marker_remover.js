() => {
    // Function to remove markers from a document
    function removeMarkersFromDocument(doc) {
        try {
            // 移除标记容器
            const markerContainer = doc.getElementById('__marker_container__');
            if (markerContainer) {
                markerContainer.remove();
            }

            // 清除所有标记元素
            const markers = doc.querySelectorAll('.__marker_element__');
            markers.forEach(marker => marker.remove());

            // 清除可能残留的样式
            const styles = doc.querySelectorAll('style[data-marker-style]');
            styles.forEach(style => style.remove());
        } catch (e) {
            // Ignore errors (e.g., cross-origin iframe)
        }
    }

    // Remove markers from main document
    removeMarkersFromDocument(document);

    // Remove markers from all iframes
    const iframes = document.querySelectorAll('iframe');
    iframes.forEach(iframe => {
        try {
            const iframeDoc = iframe.contentDocument || iframe.contentWindow?.document;
            if (iframeDoc) {
                removeMarkersFromDocument(iframeDoc);
            }
        } catch (e) {
            // Ignore cross-origin iframe errors
        }
    });
}
