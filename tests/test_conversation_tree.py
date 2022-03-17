from typing import Set
import google.protobuf.text_format as text_format
import proto.conversation_pb2 as conversation_proto
import os

def read_conversation_tree():
    with open('conversation_tree.textproto', 'r') as f:
        f_buffer = f.read()
        return text_format.Parse(f_buffer, conversation_proto.Conversation())

def visit_node(node: conversation_proto.ConversationNode, consumer, visited: Set = None):
    # See https://docs.python.org/3/reference/compound_stmts.html#function-definitions:
    # "Default parameter values are evaluated from left to right when the _function definition_ is executed."
    # Thus, |visited| is never cleared if assigned to in the signature.
    if visited is None:
        visited = set()
    visited.add(node.name)
    consumer(node)
    if len(node.link) > 0:
        for subnode in node.link:
            if len(subnode.branch.name) > 0 and not subnode.branch.name in visited:
                visit_node(subnode.branch, consumer, visited)


class TestConversationTree:
    def test_conversation_links(self):
        conversation = read_conversation_tree()
        valid_ids = []

        def collect_id(node):
            assert node.name not in valid_ids, "node['%s']: There are more than one node with the same name." % node.name
            valid_ids.append(node.name)
        for node in conversation.node:
            visit_node(node, collect_id)
        def verify_node(node):
            for link in node.link:
                assert len(link.name) == 0 or link.name in valid_ids, "node['%s'].link['%s'] links to node that does not exist." % (node.name, link.name)
        for node in conversation.node:
            visit_node(node, verify_node)

    def test_answers(self):
        conversation = read_conversation_tree()
        def do_answer_validation(node):
            assert len(node.name) > 0, "node must have a name set."
            assert len(node.answer) > 0, "node['%s'] must have at least one answer." % node.name
            for answer in node.answer:
                if answer.WhichOneof("answer") == "links":
                    assert len(answer.links.text) > 0, "node['%s'].answer.links must have text set." % node.name
                    for url in answer.links.url:
                        assert len(url.label) > 0 and len(url.url) > 0, "node['%s'].answer.links['%s'].url must have both label and url set."
                elif answer.WhichOneof("answer") == "photo":
                    assert os.path.exists("photo/%s" % answer.photo), "node['%s'].answer.photo['%s'] photo does not exist." % (node.name, answer.photo)
                elif answer.WhichOneof("answer") == "venue":
                    assert answer.venue.lat != 0 and answer.venue.lon != 0, f"node['{node.name}'].answer.venue.{{lat|lon}} must not be empty"
                    assert len(answer.venue.address) > 0, f"node['{node.name}'].answer.venue.address must not be empty"
                    assert len(answer.venue.title) > 0, f"node['{node.name}'].answer.venue.title must not be empty"

        for node in conversation.node:
            visit_node(node, do_answer_validation)
