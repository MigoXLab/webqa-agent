import json
import copy
import hashlib
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, Set
from collections import Counter


@dataclass
class DomTreeNode:
    """
    A data class representing a node in a simplified Document Object Model (DOM) tree.

    This class captures essential information about a DOM element, including its identity,
    attributes, layout, and state (e.g., visibility, interactivity). It also maintains
    the tree structure through parent-child relationships.

    Attributes:
        id (Optional[int]): A unique identifier for the element, generated from HTML.
        highlightIndex (Optional[int]): An index used for highlighting the element on the page.
        tagName (Optional[str]): The HTML tag name of the element (e.g., 'div', 'a').
        className (Optional[str]): The 'class' attribute of the element.
        innerText (str): The trimmed text content of the element.
        element_type (Optional[str]): The 'type' attribute, typically for <input> elements.
        placeholder (Optional[str]): The 'placeholder' attribute of the element.
        attributes (Dict[str, str]): A dictionary of all HTML attributes of the element.
        selector (str): A generated CSS selector for the element.
        xpath (str): A generated XPath for the element.
        viewport (Dict[str, float]): A dictionary containing the element's bounding box relative to the viewport.
        center_x (Optional[float]): The horizontal center coordinate of the element.
        center_y (Optional[float]): The vertical center coordinate of the element.
        isVisible (Optional[bool]): A flag indicating if the element is visible.
        isInteractive (Optional[bool]): A flag indicating if the element is interactive.
        isTopElement (Optional[bool]): A flag indicating if the element is the topmost element at its center.
        isInViewport (Optional[bool]): A flag indicating if the element is within the current viewport.
        parent (Optional['DomTreeNode']): A reference to the parent node in the tree.
        children (List['DomTreeNode']): A list of child nodes.
        depth (int): The depth of the node in the tree (root is at depth 0).
        subtree (Dict[str, Any]): A copy of the raw subtree data from the crawler, if any.

    """

    # Mapped from original node fields
    id: Optional[int] = None
    highlightIndex: Optional[int] = None
    tagName: Optional[str] = None
    className: Optional[str] = None
    innerText: str = ""
    element_type: Optional[str] = None
    placeholder: Optional[str] = None

    # Attributes converted from a list to a dictionary
    attributes: Dict[str, str] = field(default_factory=dict)

    # Added selector, xpath
    selector: str = ""
    xpath: str = ""

    # Layout information
    viewport: Dict[str, float] = field(default_factory=dict)
    center_x: Optional[float] = None
    center_y: Optional[float] = None

    # boolean flags
    isVisible: Optional[bool] = None
    isInteractive: Optional[bool] = None
    isTopElement: Optional[bool] = None
    isInViewport: Optional[bool] = None

    # Parent node
    parent: Optional['DomTreeNode'] = None
    # Child nodes
    children: List['DomTreeNode'] = field(default_factory=list)
    # Depth
    depth: int = 0
    # Sub DOM tree
    subtree: Dict[str, Any] = field(default_factory=dict)

    def __repr__(self):
        """Returns a string representation of the DomTreeNode."""
        return f"<DomTreeNode id={self.id!r} tag={self.tagName!r} depth={self.depth}>"

    def add_child(self, child: 'DomTreeNode') -> None:
        """
        Adds a child node to self.children and sets its parent and depth.
        """
        child.parent = self
        child.depth = self.depth + 1
        self.children.append(child)

    def find_by_tag(self, tag_name: str) -> List['DomTreeNode']:
        """
        Recursively finds all nodes matching the tag_name.
        """
        matches: List['DomTreeNode'] = []
        if self.tagName == tag_name:
            matches.append(self)
        for c in self.children:
            matches.extend(c.find_by_tag(tag_name))
        return matches

    def find_by_id(self, target_id: int) -> Optional['DomTreeNode']:
        """
        Performs a depth-first search to find the first node with id == target_id.
        Returns None if not found.
        """
        if self.highlightIndex == target_id:
            return self

        for c in self.children:
            result = c.find_by_id(target_id)
            if result is not None:
                return result

        return None

    @classmethod
    def build_root(cls, data: Dict[str, Any]) -> 'DomTreeNode':
        """
        Constructs a DomTreeNode tree from a raw dictionary, typically from JSON.

        This class method serves as the primary entry point for creating a tree from
        the data returned by the crawler. It handles cases where the input data might
        not have a single root 'node' by wrapping it in a synthetic root.

        Args:
            data: The raw dictionary representing the DOM subtree.

        Returns:
            The root DomTreeNode of the constructed tree.
        """
        if data.get('node') is None:
            fake_node = {
                'node': {
                    'id': None,
                    'highlightIndex': None,
                    'tagName': '__root__',
                    'className': None,
                    'innerText': '',
                    'type': None,
                    'placeholder': None,
                    'attributes': [],
                    'selector': None,
                    'xpath': None,
                    'viewport': {},
                    'center_x': None,
                    'center_y': None,
                    'isVisible': True,
                    'isInteractive': False,
                    'isTopElement': False,
                    'isInViewport': True
                },
                'children': [data],
                'subtree': []
            }

            data = fake_node

        def build_dom_tree(data: Dict[str, Any],
                           parent: Optional['DomTreeNode'] = None,
                           depth: int = 0) -> List['DomTreeNode']:
            """
            Builds a list of DomTreeNode from the injected JS result (nested dict).
            Returns a list of top-level (or multi-root) nodes.
            """
            nodes: List[DomTreeNode] = []
            node_data = data.get('node')
            children_data = data.get('children', [])
            subtree_data = copy.deepcopy(data.get("subtree", {}))

            if node_data:
                attrs = {a['name']: a['value'] for a in node_data.get('attributes', [])}

                node = cls(
                    id=node_data.get('id'),
                    highlightIndex=node_data.get('highlightIndex'),
                    tagName=(node_data.get('tagName') or '').lower() or None,
                    className=node_data.get('className'),
                    innerText=(node_data.get('innerText') or '').strip(),
                    element_type=node_data.get('type'),
                    placeholder=node_data.get('placeholder'),

                    attributes=attrs,
                    selector=node_data.get('selector'),
                    xpath=node_data.get('xpath'),
                    viewport=node_data.get('viewport', {}),
                    center_x=node_data.get('center_x'),
                    center_y=node_data.get('center_y'),

                    isVisible=node_data.get('isVisible'),
                    isInteractive=node_data.get('isInteractive'),
                    isTopElement=node_data.get('isTopElement'),
                    isInViewport=node_data.get('isInViewport'),

                    subtree=subtree_data,
                    parent=parent,
                    depth=depth
                )

                for cd in children_data:
                    for child in build_dom_tree(cd, parent=node, depth=depth + 1):
                        node.add_child(child)

                nodes.append(node)

            else:
                for cd in children_data:
                    nodes.extend(build_dom_tree(cd, parent=parent, depth=depth))

            return nodes

        roots = build_dom_tree(data)

        return roots[0]

    def pre_iter(self) -> List['DomTreeNode']:
        """Performs a pre-order traversal and returns a list of nodes."""
        nodes = [self]
        for c in self.children:
            nodes.extend(c.pre_iter())
        return nodes

    def post_iter(self) -> List['DomTreeNode']:
        """Performs a post-order traversal and returns a list of nodes."""
        nodes: List['DomTreeNode'] = []
        for c in self.children:
            nodes.extend(c.post_iter())
        nodes.append(self)
        return nodes

    def count_depth(self) -> Dict[int, int]:
        """Counts the number of nodes at each depth level."""
        counts = Counter(n.depth for n in self.pre_iter())
        return dict(counts)

    # Change detection related fields
    is_new: Optional[bool] = None  # Mark if element is new
    element_hash: Optional[str] = None  # Element hash value

    def calculate_element_hash(self) -> str:
        """
        Calculate unique hash value for the element.

        Hash is generated based on:
        - Parent path
        - Element attributes  
        - XPath

        Returns:
            str: SHA256 hash value of the element.
        """
        # Get parent path
        parent_path = self._get_parent_branch_path()
        parent_path_str = '/'.join(parent_path)

        # Get attributes string
        # attrs_str = ''.join(f'{k}={v}' for k, v in sorted(self.attributes.items()))

        # Combine hash source
        # hash_source = f"{parent_path_str}|{attrs_str}|{self.xpath}"
        hash_source = f"{parent_path_str}|{self.xpath}"
        # logging.debug(f"hash_source of elem {self.highlightIndex} ({self.innerText}):\nparent_path_str: {parent_path_str}\nxpath: {self.xpath}")

        # Calculate SHA256 hash
        self.element_hash = hashlib.sha256(hash_source.encode()).hexdigest()
        return self.element_hash

    def _get_parent_branch_path(self) -> List[str]:
        """
        Get parent path from root node to current node.

        Returns:
            List[str]: List of parent tag names.
        """
        path = []
        current = self
        while current.parent is not None:
            path.append(current.tagName or '')
            current = current.parent
        path.reverse()
        return path

    def get_clickable_elements(self) -> List['DomTreeNode']:
        """
        Get all clickable elements.

        Returns:
            List[DomTreeNode]: List of clickable elements.
        """
        clickable_elements = []

        # 检查当前节点是否可点击
        if (self.isInteractive and
                self.isVisible and
                self.isTopElement and
                self.highlightIndex is not None):
            clickable_elements.append(self)

        # 递归检查子节点
        for child in self.children:
            clickable_elements.extend(child.get_clickable_elements())

        return clickable_elements

    def get_clickable_elements_hashes(self) -> Set[str]:
        """
        Get hash set of all clickable elements.

        Returns:
            Set[str]: Hash set of clickable elements.
        """
        clickable_elements = self.get_clickable_elements()
        return {elem.calculate_element_hash() for elem in clickable_elements}

    def find_element_by_hash(self, target_hash: str) -> Optional['DomTreeNode']:
        """
        Find element by hash value.

        Args:
            target_hash: Target element hash value.

        Returns:
            Optional[DomTreeNode]: Found element node, None if not found.
        """
        if self.calculate_element_hash() == target_hash:
            return self

        for child in self.children:
            result = child.find_element_by_hash(target_hash)
            if result is not None:
                return result

        return None

    def mark_new_elements(self, cached_hashes: Set[str]) -> None:
        """
        Mark newly appeared elements.

        Args:
            cached_hashes: Cached element hash set.
        """
        # 标记当前元素
        if (self.isInteractive and
                self.isVisible and
                self.isTopElement and
                self.highlightIndex is not None):
            current_hash = self.calculate_element_hash()
            self.is_new = current_hash not in cached_hashes

        # 递归标记子元素
        for child in self.children:
            child.mark_new_elements(cached_hashes)
