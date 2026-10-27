"""Bounded lexical guards for obvious source/claim polarity conflicts."""

from __future__ import annotations

import re

NEGATION_RE = re.compile(
    r"\b(?:not|no|never|without|cannot|can't|didn't|doesn't|won't|wasn't|weren't|isn't|aren't|"
    r"\u043d\u0435|\u043d\u0438|\u043d\u0435\u0442|\u0431\u0435\u0437|"
    r"\u043d\u0438\u043a\u043e\u0433\u0434\u0430|\u043d\u0435\u0432\u043e\u0437\u043c\u043e\u0436\u043d\u043e|"
    r"\u043d\u0435\u043b\u044c\u0437\u044f)\b",
    re.I,
)
CONDITION_RE = re.compile(
    r"\b(?:if|unless|when|while|once|provided(?:\s+that)?|only\s+if|in\s+case|assuming|"
    r"\u0435\u0441\u043b\u0438|\u0435\u0436\u0435\u043b\u0438|\u043a\u043e\u0433\u0434\u0430|"
    r"\u043f\u043e\u043a\u0430)\b|"
    r"\b(?:\u043f\u0440\u0438\u0020\u0443\u0441\u043b\u043e\u0432\u0438\u0438|"
    r"\u0432\u0020\u0441\u043b\u0443\u0447\u0430\u0435\u0020\u0435\u0441\u043b\u0438|"
    r"\u0442\u043e\u043b\u044c\u043a\u043e\u0020\u0435\u0441\u043b\u0438)\b",
    re.I,
)
TOKEN_RE = re.compile(r"[a-z\u0430-\u044f\u04510-9]+", re.I)
ALIGNMENT_STOPWORDS = frozenset(
    (
        "a an and are as at be been being but by did do does for from had has have he her hers him "
        "his i if in into is it its me my nor of on or our ours she that the their them they this "
        "those to was we were what when where which who will with you your "
        "only able possible likely "
        "не ни что это они она оно его её мы вы для при про как так же либо или "
        "был была были быть этот эта эти тот та те потому после до во на из к от по "
        "без над под"
    ).split()
)


def _lemma(token: str) -> str:
    value = token.casefold()
    if value.isascii():
        for suffix in ("ing", "ed"):
            if len(value) - len(suffix) >= 4 and value.endswith(suffix):
                value = value[: -len(suffix)]
                if suffix == "ing" and len(value) > 3 and value[-1] == value[-2]:
                    value = value[:-1]
                return value
        if len(value) >= 5 and value.endswith("s"):
            return value[:-1]
    return value


def _tokens(text: str) -> set[str]:
    return {
        _lemma(token)
        for token in TOKEN_RE.findall(text)
        if len(token) >= 3 and token.casefold() not in ALIGNMENT_STOPWORDS
    }


def _negated_anchors(sentence: str) -> set[str]:
    tokens = list(TOKEN_RE.finditer(sentence))
    anchors: set[str] = set()
    for marker in NEGATION_RE.finditer(sentence):
        following = (token for token in tokens if token.start() >= marker.end())
        anchor = next(
            (token for token in following if token.group().casefold() not in ALIGNMENT_STOPWORDS),
            None,
        )
        if anchor is not None:
            anchors.add(_lemma(anchor.group()))
    return anchors


def polarity_conflicts(claim: str, quotes: tuple[str, ...]) -> bool:
    """Flag only mismatched polarity on a shared nearby predicate, not any negation."""
    claim_sentences = re.split(r"(?<=[.!?;])\s+|,\s+", claim)
    source_sentences = [
        sentence for quote in quotes for sentence in re.split(r"(?<=[.!?;])\s+|,\s+", quote)
    ]
    for source_sentence in source_sentences:
        source_anchors = _negated_anchors(source_sentence)
        source_tokens = _tokens(source_sentence)
        for claim_sentence in claim_sentences:
            claim_anchors = _negated_anchors(claim_sentence)
            claim_tokens = _tokens(claim_sentence)
            if source_anchors & (claim_tokens - claim_anchors):
                return True
            if claim_anchors & (source_tokens - source_anchors):
                return True
    return False


def drops_relevant_condition(claim: str, quotes: tuple[str, ...]) -> bool:
    """Reject omission only when the claim overlaps the conditioned proposition."""
    if CONDITION_RE.search(claim):
        return False
    claim_tokens = _tokens(claim)
    for quote in quotes:
        for sentence in re.split(r"(?<=[.!?;])\s+", quote):
            if CONDITION_RE.search(sentence) and claim_tokens & _tokens(sentence):
                return True
    return False
