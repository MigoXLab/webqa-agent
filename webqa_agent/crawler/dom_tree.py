import copy
import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class DomTreeNode:
    # —— 映射自原始 node 字段 ——
    id: Optional[int] = None
    highlightIndex: Optional[int] = None
    tag: Optional[str] = None
    class_name: Optional[str] = None
    inner_text: str = ""
    element_type: Optional[str] = None
    placeholder: Optional[str] = None

    # attributes 列表转成的字典
    attributes: Dict[str, str] = field(default_factory=dict)

    # 新增 selector, xpath
    selector: str = ("",)
    xpath: str = ("",)

    # 布局信息
    viewport: Dict[str, float] = field(default_factory=dict)
    center_x: Optional[float] = None
    center_y: Optional[float] = None

    # boolean flags
    isVisible: Optional[bool] = None
    isInteractive: Optional[bool] = None
    isTopElement: Optional[bool] = None
    is_in_viewport: Optional[bool] = None

    # 父节点
    parent: Optional["DomTreeNode"] = None
    # 子节点
    children: List["DomTreeNode"] = field(default_factory=list)
    # 深度
    depth: int = 0
    # 子 DOM 树
    subtree: Dict[str, Any] = field(default_factory=dict)

    def __repr__(self):
        return f"<DomTreeNode id={self.id!r} tag={self.tag!r} depth={self.depth}>"

    def add_child(self, child: "DomTreeNode") -> None:
        """将 child 挂载到 self.children，同步设置 parent 和 depth。"""
        child.parent = self
        child.depth = self.depth + 1
        self.children.append(child)

    def find_by_tag(self, tag_name: str) -> List["DomTreeNode"]:
        """递归查找所有匹配 tag_name 的节点。"""
        matches: List["DomTreeNode"] = []
        if self.tag == tag_name:
            matches.append(self)
        for c in self.children:
            matches.extend(c.find_by_tag(tag_name))
        return matches

    def find_by_id(self, target_id: int) -> Optional["DomTreeNode"]:
        """深度优先查找：返回第一个 id == target_id 的节点，找不到则返回 None。"""
        # 先检查自身
        if self.id == target_id:
            return self

        # 递归检查子节点
        for c in self.children:
            result = c.find_by_id(target_id)
            if result is not None:
                return result

        return None

    def prune(self, predicate: Callable[["DomTreeNode"], bool]) -> Optional["DomTreeNode"]:
        """剪枝：保留满足 predicate 的节点，并递归处理子树。 如果当前节点和所有子节点都不满足，则返回 None。"""
        # 处理子节点
        pruned_children: List["DomTreeNode"] = []
        for c in self.children:
            pc = c.prune(predicate)
            if pc:
                pruned_children.append(pc)

        keep_self = predicate(self)
        if keep_self or pruned_children:
            # 构造新节点实例，保留属性但只挂载 pruned_children
            new_node = DomTreeNode(
                id=self.id,
                highlightIndex=self.highlightIndex,
                tag=self.tag,
                class_name=self.class_name,
                inner_text=self.inner_text,
                element_type=self.element_type,
                placeholder=self.placeholder,
                attributes=self.attributes.copy(),
                viewport=self.viewport.copy(),
                center_x=self.center_x,
                center_y=self.center_y,
                isVisible=self.isVisible,
                isInteractive=self.isInteractive,
                isTopElement=self.isTopElement,
                is_in_viewport=self.is_in_viewport,
                subtree=copy.deepcopy(self.subtree),
                depth=self.depth,
                selector=self.selector,  # 新增
                xpath=self.xpath,  # 新增
            )
            for child in pruned_children:
                new_node.add_child(child)
            return new_node
        return None

    def to_dict(self) -> Dict[str, Any]:
        """序列化回原始嵌套 dict 格式，包含 'node' 和 'children'。"""
        node_data: Dict[str, Any] = {
            "id": self.id,
            "highlightIndex": self.highlightIndex,
            "tagName": self.tag,
            "className": self.class_name,
            "innerText": self.inner_text,
            "type": self.element_type,
            "placeholder": self.placeholder,
            "attributes": [{"name": k, "value": v} for k, v in self.attributes.items()],
            "viewport": self.viewport,
            "center_x": self.center_x,
            "center_y": self.center_y,
            "isVisible": self.isVisible,
            "isInteractive": self.isInteractive,
            "isTopElement": self.isTopElement,
            "isInViewport": self.is_in_viewport,
        }

        def serialize_subtree(raw: Any) -> Any:
            if isinstance(raw, dict) and "node" in raw and "children" in raw:
                # 直接当作一整段 “raw data” 递归返回
                return raw
            elif isinstance(raw, list):
                return [serialize_subtree(item) for item in raw]
            else:
                return raw

        return {
            "node": node_data,
            "children": [c.to_dict() for c in self.children],
            "subtree": serialize_subtree(self.subtree),
        }

    @classmethod
    def build_root(cls, data: Dict[str, Any]) -> "DomTreeNode":
        if data.get("node") is None:
            fake_node = {
                "node": {
                    "id": None,
                    "highlightIndex": None,
                    "tagName": "__root__",
                    "className": None,
                    "innerText": "",
                    "type": None,
                    "placeholder": None,
                    "attributes": [],
                    "selector": None,  # 新增
                    "xpath": None,  # 新增
                    "viewport": {},
                    "center_x": None,
                    "center_y": None,
                    "isVisible": True,
                    "isInteractive": False,
                    "isTopElement": False,
                    "isInViewport": True,
                },
                "children": [data],
                "subtree": [],
            }

            data = fake_node

        def build_dom_tree(
            data: Dict[str, Any], parent: Optional["DomTreeNode"] = None, depth: int = 0
        ) -> List["DomTreeNode"]:
            """从注入 JS 结果（嵌套 dict）构建 DomTreeNode 列表。 返回顶层（或多根）节点列表。"""
            nodes: List[DomTreeNode] = []
            node_data = data.get("node")
            children_data = data.get("children", [])
            subtree_data = copy.deepcopy(data.get("subtree", {}))

            if node_data:
                attrs = {a["name"]: a["value"] for a in node_data.get("attributes", [])}

                node = cls(
                    id=node_data.get("id"),
                    highlightIndex=node_data.get("highlightIndex"),
                    tag=(node_data.get("tagName") or "").lower() or None,
                    class_name=node_data.get("className"),
                    inner_text=(node_data.get("innerText") or "").strip(),
                    element_type=node_data.get("type"),
                    placeholder=node_data.get("placeholder"),
                    attributes=attrs,
                    selector=node_data.get("selector"),  # 新增
                    xpath=node_data.get("xpath"),  # 新增
                    viewport=node_data.get("viewport", {}),
                    center_x=node_data.get("center_x"),
                    center_y=node_data.get("center_y"),
                    isVisible=node_data.get("isVisible"),
                    isInteractive=node_data.get("isInteractive"),
                    isTopElement=node_data.get("isTopElement"),
                    is_in_viewport=node_data.get("isInViewport"),
                    subtree=subtree_data,
                    parent=parent,
                    depth=depth,
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

    def pre_iter(self) -> List["DomTreeNode"]:
        """前序遍历，返回节点列表。"""
        nodes = [self]
        for c in self.children:
            nodes.extend(c.pre_iter())
        return nodes

    def post_iter(self) -> List["DomTreeNode"]:
        """后序遍历，返回节点列表。"""
        nodes: List["DomTreeNode"] = []
        for c in self.children:
            nodes.extend(c.post_iter())
        nodes.append(self)
        return nodes

    def count_depth(self) -> Dict[int, int]:
        counts = Counter(n.depth for n in self.pre_iter())
        return dict(counts)

    @classmethod
    def cutting(cls, node: "DomTreeNode") -> dict:
        """Cut off invalid info."""
        vp = node.viewport or {}
        left = vp.get("x")
        top = vp.get("y")
        width = vp.get("width")
        height = vp.get("height")

        # 计算 right, bottom
        if left is not None and width is not None:
            right = left + width
        else:
            right = None

        if top is not None and height is not None:
            bottom = top + height
        else:
            bottom = None

        bbox = [
            int(left) if left is not None else None,
            int(top) if top is not None else None,
            int(right) if right is not None else None,
            int(bottom) if bottom is not None else None,
        ]

        node_dict = {
            "id": node.highlightIndex,
            "tagName": node.tag,
            "innerText": node.inner_text,
            "bbox": bbox,
            "center_x": int(node.center_x) if node.center_x is not None else None,
            "center_y": int(node.center_y) if node.center_y is not None else None,
        }

        # 2. 递归处理 children
        children_list = []
        for child in node.children:
            children_list.append(cls.cutting(child))

        # 3. 返回新的嵌套结构
        return {"node": node_dict, "children": children_list}


# Example Usage
if __name__ == "__main__":
    with open("test_tree.json", encoding="utf-8") as f:
        raw = json.load(f)
    root = DomTreeNode.build_root(raw)
    print("Depth distribution:", root.count_depth())

    res = DomTreeNode.cutting(root)
    print(res)
    # print('All links:', [n for n in root.find_by_tag('a')])
