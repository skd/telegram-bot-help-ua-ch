from node_util import visit_node
from typing import Dict, List

import proto.conversation_pb2 as conversation_proto


def _create_node_by_name(
    conversation: conversation_proto.Conversation
) -> Dict[str, conversation_proto.ConversationNode]:
    node_by_name = dict()

    def updater(node: conversation_proto.ConversationNode):
        node_by_name[node.name] = node

    for node in conversation.node:
        visit_node(node, updater)
    return node_by_name


def _create_keyboard_options(node_by_name) -> Dict[str, List[List[str]]]:
    keyboard_by_name = dict()
    for name in node_by_name:
        if len(node_by_name[name].link) == 0:
            continue
        options = []
        for link in node_by_name[name].link:
            if len(link.name) > 0:
                options.append([link.name])
            elif len(link.branch.name) > 0:
                options.append([link.branch.name])
        keyboard_by_name[name] = options
    return keyboard_by_name


class ConversationData:

    def __init__(self, conversation: conversation_proto.Conversation):
        self._node_by_name: Dict[str, conversation_proto.ConversationNode] = _create_node_by_name(conversation)
        self._keyboard_by_name: Dict[str, List[List[str]]] = _create_keyboard_options(self._node_by_name)

    def node_by_name(self, name: str) -> conversation_proto.ConversationNode:
        return self._node_by_name.get(name)

    def keyboard_by_name(self, name: str) -> List[List[str]]:
        return self._keyboard_by_name.get(name)
