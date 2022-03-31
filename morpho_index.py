from collections import namedtuple
import logging
import pprint
import proto.conversation_pb2 as conversation_proto
import pymorphy2
import re

from multiset import Multiset
from node_util import visit_node
from operator import itemgetter
from typing import Dict, List, Set, Tuple

SPLIT_REGEX = re.compile("[^а-яА-Яa-zA-Z-]+")
RUSSIAN_WORD = re.compile("^[а-яА-Я-]+$")
NON_RUSSIAN_POS = "NONRUS"
IGNORED_NODES = set(["/start"])
morph = pymorphy2.MorphAnalyzer(lang="ru")

logger = logging.getLogger(__name__)

WordTag = namedtuple("WordTag", ["word", "part_of_speech"])


def word_tag(word: str) -> WordTag:
    word = word.lower()
    is_russian = re.match(RUSSIAN_WORD, word)
    length = len(word)
    if length < 3:
        return None
    parses = morph.parse(word)
    return WordTag(parses[0].normal_form,
                   parses[0].tag.POS if is_russian else NON_RUSSIAN_POS)


class MorphoIndex:

    def __init__(self, conversation: conversation_proto.Conversation):
        self._node_counts_by_word_tag: Dict[WordTag, Multiset] = {}

        def process_text(node: conversation_proto.ConversationNode, text: str,
                         weight: int):
            words = re.split(SPLIT_REGEX, text)
            for word in words:
                wt = word_tag(word)
                if not wt:
                    continue
                node_set = self._node_counts_by_word_tag.setdefault(
                    wt, Multiset())
                node_set.add(node.name, weight)

        def process_node(node: conversation_proto.ConversationNode):
            if node.name in IGNORED_NODES:
                return

            # Drastically boost search terms found in the node name.
            process_text(node, node.name, 9000)
            for ans in node.answer:
                if ans.text:
                    process_text(node, ans.text, 1)
                if ans.links and ans.links.text:
                    process_text(node, ans.links.text, 1)
                    for url in ans.links.url:
                        process_text(node, url.label, 1)

        for node in conversation.node:
            visit_node(node, process_node)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "node_counts_by_word_tag:\n%s",
                pprint.pformat(self._node_counts_by_word_tag, indent=2))

    def search(self, text: str) -> List[Tuple[str, int]]:
        words = re.split(SPLIT_REGEX, text)
        result_multiset = Multiset()
        found_word_count_by_node_name = {}
        for word in words:
            wt = word_tag(word)
            node_counts = self._node_counts_by_word_tag.get(wt)
            if not node_counts:
                continue
            for item in node_counts.items():
                count = found_word_count_by_node_name.get(item[0], 0)
                found_word_count_by_node_name[item[0]] = count + 1
                result_multiset.add(item[0], item[1])

        # Boost nodes having hits for multiple words from the query.
        nodes_and_scores = [(node_name, count * found_word_count_by_node_name[node_name]) \
         for (node_name, count) in result_multiset.items()]
        nodes_and_scores.sort(key=itemgetter(1), reverse=True)
        logger.debug(f"Search: [{text}] -> {nodes_and_scores}")
        return nodes_and_scores
