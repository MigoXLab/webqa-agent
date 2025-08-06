() => {
    // 移除标记容器
    const markerContainer = document.getElementById('__marker_container__');
    if (markerContainer) {
        markerContainer.remove();
    }

    // 清除所有标记元素
    const markers = document.querySelectorAll('.__marker_element__');
    markers.forEach(marker => marker.remove());

    // 清除可能残留的样式
    const styles = document.querySelectorAll('style[data-marker-style]');
    styles.forEach(style => style.remove());
}
