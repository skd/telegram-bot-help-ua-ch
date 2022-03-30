import proto.conversation_pb2 as conversation_proto

from typing import Set


def visit_node(node: conversation_proto.ConversationNode, consumer, visited: Set = None):
    if visited is None:
        visited = set()
    visited.add(node.name)
    consumer(node)
    if len(node.link) > 0:
        for subnode in node.link:
            if len(subnode.branch.name) > 0 and subnode.branch.name not in visited:
                visit_node(subnode.branch, consumer, visited)
