"""Language detection and language-keyed prompt selection.

GPTHub: this module is a LEAF on purpose — it imports only `re`.

Two things lived here badly before:
  * `detect_lang` existed in TWO copies (mem_reader and the retrieve path), and the
    search path used the second one. Fixing Russian in one copy silently did nothing
    for retrieval.
  * Prompt dictionaries are read by direct indexing, so a language without an entry
    raised KeyError instead of degrading. `pick_by_lang` makes that degradation
    explicit.

Keeping this dependency-free lets both the reader and the retriever import it without
risking an import cycle.
"""

import re

def pick_by_lang(mapping, lang, fallback="en"):
    """Pick a prompt for *lang*, degrading to *fallback* when it has none.

    GPTHub: prompt dictionaries are read by direct indexing (``D["chat"][lang]``), so
    a language without an entry raises KeyError at runtime rather than degrading. Once
    detect_lang started returning "ru", every dictionary that has only en/zh became a
    crash — including COT_DICT on the SEARCH path, which would have killed recall for
    Russian queries outright.

    The main extraction path has real Russian prompts. Secondary subsystems (feedback,
    preference memory, chain-of-thought) fall back to English here — a deliberate,
    documented degradation, not an oversight.
    """
    if not isinstance(mapping, dict):
        return mapping
    if lang in mapping:
        return mapping[lang]
    return mapping[fallback]


def detect_lang(text):
    """
    Detect the language of the given text (Russian, Chinese or English).

    GPTHub: Russian was added because the function only ever returned "zh" or "en".
    Russian text has no Han characters, so it fell through to "en" and the memory
    extractor ran with the English prompt and English few-shot examples — which
    rewrote clean Russian facts into English summary blobs. See migration
    013_user_memory_facts, which exists solely to work around that.

    Args:
        text: Text to analyze

    Returns:
        "ru" for Russian, "zh" for Chinese, "en" for English (default)
    """
    try:
        if not text or not isinstance(text, str):
            return "en"
        cleaned_text = text
        # remove role and timestamp-like prefixes
        cleaned_text = re.sub(
            r"\b(user|assistant|query|answer)\s*:", "", cleaned_text, flags=re.IGNORECASE
        )
        # timestamps like [11:32 AM on 04 March, 2026]
        cleaned_text = re.sub(
            r"\[\s*\d{1,2}:\d{2}\s*(?:AM|PM)\s+on\s+\d{2}\s+[A-Za-z]+\s*,\s*\d{4}\s*\]",
            "",
            cleaned_text,
            flags=re.IGNORECASE,
        )
        # purely numeric timestamps like [2025-01-01 10:00]
        cleaned_text = re.sub(r"\[[\d\-:\s]+\]", "", cleaned_text)
        # remove URLs to prevent the dilution of Chinese characters
        cleaned_text = re.sub(r'https?://[^\s<>"{}|\\^`\[\]]+', "", cleaned_text)
        # remove common id-like tokens (uuid-ish / file_id / image_id /
        # my_id_01 etc.)
        # uuid
        cleaned_text = re.sub(
            r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
            " ",
            cleaned_text,
            flags=re.IGNORECASE,
        )
        # key:value where key ends with _id or is id, and value is quoted or bare token
        cleaned_text = re.sub(
            r'(?i)\b[a-z_]*id\b\s*[:=]\s*(".*?"|\'.*?\'|[a-z0-9_\-]+)', " ", cleaned_text
        )
        cleaned_text = re.sub(
            r'(?i)\b[a-z_]*_id\b\s*[:=]\s*(".*?"|\'.*?\'|[a-z0-9_\-]+)', " ", cleaned_text
        )
        # remove schema keywords like text / type / image_url / url
        cleaned_text = re.sub(
            r"\b(text|type|image_url|imageurl|url|file|file_id|image_id|file_data)\b",
            "",
            cleaned_text,
            flags=re.IGNORECASE,
        )
        # extract chinese characters
        chinese_pattern = r"[\u4e00-\u9fff\u3400-\u4dbf\U00020000-\U0002a6df\U0002a700-\U0002b73f\U0002b740-\U0002b81f\U0002b820-\U0002ceaf\uf900-\ufaff]"
        chinese_chars = re.findall(chinese_pattern, cleaned_text)
        # Cyrillic block (Russian and neighbours). `\w` keeps Cyrillic letters, so the
        # denominator below counts them and the ratio test works the same way as for zh.
        cyrillic_chars = re.findall(r"[\u0400-\u04ff]", cleaned_text)
        text_without_special = re.sub(r"[\s\d\W]", "", cleaned_text)
        if not text_without_special:
            return "en"
        if len(chinese_chars) / len(text_without_special) > 0.3:
            return "zh"
        if len(cyrillic_chars) / len(text_without_special) > 0.3:
            return "ru"
        return "en"
    except Exception:
        return "en"
