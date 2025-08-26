from dataclasses import dataclass
from typing import Set, Optional, Dict, Any
from webqa_agent.crawler.dom_tree import DomTreeNode
import time


@dataclass
class CachedDomState:
    """
    DOM state cache class.
    
    Used to store DOM state snapshots for change detection.
    """
    url: str
    clickable_element_hashes: Set[str]
    timestamp: float


class DomCacher:
    """
    DOM change detector.
    
    Provides DOM state comparison and change detection functionality.
    """

    def __init__(self):
        self._cached_state: Optional[CachedDomState] = None

    def detect_dom_diff(self,
                        current_tree: DomTreeNode,
                        current_url: str) -> Dict[str, Any]:
        """
        Detect DOM changes.

        Args:
            current_tree: Current DOM tree.
            current_url: Current page URL.

        Returns:
            Dict[str, Any]: Change detection results.
        """

        # Get current clickable element hashes
        current_hashes = current_tree.get_clickable_elements_hashes()

        result = {
            'has_changes': False,
            'new_elements_count': 0,
            'removed_elements_count': 0,
            'total_elements': len(current_hashes)
        }

        # If cached state exists and URL matches, perform comparison
        if self._cached_state and self._cached_state.url == current_url:
            cached_hashes = self._cached_state.clickable_element_hashes

            # Calculate new and removed elements
            new_hashes = current_hashes - cached_hashes
            removed_hashes = cached_hashes - current_hashes

            result.update({
                'has_changes': len(new_hashes) > 0 or len(removed_hashes) > 0,
                'new_elements_count': len(new_hashes),
                'removed_elements_count': len(removed_hashes),
                # 'new_element_hashes': new_hashes,
                # 'removed_element_hashes': removed_hashes
            })

            # Mark new elements
            current_tree.mark_new_elements(cached_hashes)

        # Update cached state
        self._cached_state = CachedDomState(
            url=current_url,
            clickable_element_hashes=current_hashes,
            timestamp=time.time()
        )

        return result

    def clear_cache(self) -> None:
        """
        Clear cached state.
        """
        self._cached_state = None

    def get_cached_state(self) -> Optional[CachedDomState]:
        """
        Get cached state.

        Returns:
            Optional[CachedDomState]: Cached DOM state.
        """
        return self._cached_state
