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

UKR_APOS = "'`’ʼ"
UKR_APOS_REGEX = re.compile(f"[{UKR_APOS}]")
APOS_STRIP_REGEX = re.compile(f"^[{UKR_APOS}]+|[{UKR_APOS}]+$")
SPLIT_REGEX = re.compile(f"[^а-яёґєіїА-ЯЁҐЄІЇa-zA-Z{UKR_APOS}-]+")
RUSSIAN_WORD = re.compile("^[а-яёА-ЯЁ-]+$")
UKRAINIAN_WORD = re.compile(f"^[А-ЩЬЮЯҐЄІЇа-щьюяґєії{UKR_APOS}-]+$")
UNKNOWN_POS = "UNK"
NODE_NAME_TERM_SCORE = 9000
IGNORED_NODES = set(["/start"])
MORPH_RU = pymorphy2.MorphAnalyzer()
MORPH_UK = pymorphy2.MorphAnalyzer(lang='uk')

logger = logging.getLogger(__name__)

WordTag = namedtuple("WordTag", ["word", "part_of_speech"])


def normalize_word(word: str):
    word = re.sub(APOS_STRIP_REGEX, '', word)
    word = re.sub(r"ё", "е", word.lower())
    word = re.sub(UKR_APOS_REGEX, "'", word)
    return word


def word_tag_for_parse(parse):
    return WordTag(parse.normal_form, parse.tag.POS)


def word_tags(word: str) -> List[WordTag]:
    word = normalize_word(word)
    length = len(word)

    # Retain abbreviated canton names (e.g. "ZH").
    if length < 2:
        return []

    is_russian = re.match(RUSSIAN_WORD, word)
    is_ukrainian = re.match(UKRAINIAN_WORD, word)
    parse_ru = None
    parse_uk = None
    if is_russian:
        parses = MORPH_RU.parse(word)
        if parses:
            parse_ru = parses[0]
    if is_ukrainian:
        parses = MORPH_UK.parse(word)
        if parses:
            parse_uk = prefer_noun(word, parses)

    result = []
    if parse_ru and parse_ru.is_known:
        result.append(word_tag_for_parse(parse_ru))
    if parse_uk and parse_uk.is_known:
        word_tag_uk = word_tag_for_parse(parse_uk)
        if word_tag_uk not in result:
            result.append(word_tag_uk)
    if not result and parse_ru:
        result.append(word_tag_for_parse(parse_ru))
    if not result and parse_uk:
        result.append(word_tag_for_parse(parse_uk))

    return result


def prefer_noun(original_word: str, parses: List):
    # Likely, only top-score parses should be considered but the parse score
    # is not supported for Ukrainian in pymorphy2.
    candidate = parses[0]
    for parse in parses:
        if parse.is_known and parse.tag.POS == "NOUN":
            if parse.normal_form == original_word:
                return parse
            candidate = parse
    return candidate


class MorphoIndex:

    def __init__(self, conversation: conversation_proto.Conversation):
        self._node_counts_by_word_tag: Dict[WordTag, Multiset] = {}

        def process_text(node: conversation_proto.ConversationNode, text: str,
                         weight: int):
            words = re.split(SPLIT_REGEX, text)
            for word in words:
                wtags = word_tags(word)
                for wt in wtags:
                    node_set = self._node_counts_by_word_tag.setdefault(
                        wt, Multiset())
                    node_set.add(node.name, weight)

        def process_node(node: conversation_proto.ConversationNode):
            if node.name in IGNORED_NODES:
                return

            # Drastically boost search terms found in the node name.
            process_text(node, node.name, NODE_NAME_TERM_SCORE)
            for alt_name in node.alt_name:
                process_text(node, alt_name, NODE_NAME_TERM_SCORE)
            for keyword in node.keyword:
                process_text(node, keyword, 1)
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
            wtags = word_tags(word)
            for wt in wtags:
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
