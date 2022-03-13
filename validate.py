from typing import Set
import google.protobuf.text_format as text_format
import proto.conversation_pb2 as conversation_proto
import os


def visit_node(node: conversation_proto.ConversationNode, consumer, visited: Set = set()):
    visited.add(node.name)
    consumer(node)
    if len(node.link) > 0:
        for subnode in node.link:
            if len(subnode.branch.name) > 0 and not subnode.branch.name in visited:
                visit_node(subnode.branch, consumer, visited)


def validate_conversation_links(conversation):
    valid_ids = []

    def collect_id(node):
        valid_ids.append(node.name)
    for node in conversation.node:
        visit_node(node, collect_id)

    def verify_node(node):
        for link in node.link:
            print(
                "E: node['%s'].link['%s'] links to node that does not exist." % (node.name, link.name)) \
                if len(link.name) > 0 and not link.name in valid_ids else None
    for node in conversation.node:
        visit_node(node, verify_node)


def validate_answers(conversation):
    def do_answer_validation(node):
        print("E: node must have a name set.") if len(node.name) == 0 else None
        print("E: node['%s'] must have at least one answer." %
              node.name) if len(node.answer) == 0 else None
        for answer in node.answer:
            if answer.WhichOneof("answer") == "links":
                print("E: node['%s'].answer.links must have text set." % (node.name)) \
                    if len(answer.links.text) == 0 else None
                for url in answer.links.url:
                    print("E: node['%s'].answer.links['%s'].url must have both label and url set."
                          % (node.name, answer.links.text)) \
                        if len(url.label) == 0 or len(url.url) == 0 else None
            elif answer.WhichOneof("answer") == "photo":
                print("E: node['%s'].answer.photo['%s'] photo does not exist." % (node.name, answer.photo)) \
                    if not os.path.exists("photo/%s" % answer.photo) else None

    for node in conversation.node:
        visit_node(node, do_answer_validation)


def main():
    with open('conversation_tree.textproto', 'r') as f:
        f_buffer = f.read()
        conversation = text_format.Parse(
            f_buffer, conversation_proto.Conversation())
    validate_conversation_links(conversation)
    validate_answers(conversation)
    print("Done")


if __name__ == "__main__":
    main()
