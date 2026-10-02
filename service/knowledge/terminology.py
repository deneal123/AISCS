"""Small bilingual retrieval glossary; translation never establishes scientific transfer."""

import re

# Stems expand vocabulary only. Nociception, subjective pain and ECAP stay distinct.
TERMS = {
    "нейрон": "neural neuronal",
    "активност": "activity",
    "предсказ": "prediction",
    "прогноз": "prediction",
    "рекуррент": "recurrent",
    "коннектом": "connectome",
    "вычислитель": "computational",
    "модел": "model",
    "мозг": "brain",
    "дрозофил": "Drosophila",
    "сенсомотор": "sensorimotor",
    "централиз": "centralized",
    "сеть": "network",
    "сети": "network",
    "сетей": "network",
    "сетев": "network",
    "чистк": "grooming",
    "антенн": "antennal",
    "симуляц": "simulation",
    "центральн": "central",
    "генератор": "generator",
    "ходьб": "walking",
    "мух": "fly",
    "распознаван": "recognition",
    "боли": "pain",
    "боль": "pain",
    "болев": "pain",
    "синтетич": "synthetic",
    "мультимодаль": "multimodal",
    "данн": "data",
    "обучен": "learning",
    "домен": "domain",
    "ультразвук": "ultrasound",
    "беспровод": "wireless",
    "имплант": "implant",
    "адаптив": "adaptive",
    "стимуляц": "stimulation",
    "высокодозн": "high-dose",
    "эффективност": "effectiveness",
    "спинн": "spinal cord",
    "неудачн": "failed",
    "операц": "surgery",
    "спин": "back",
    "регистрац": "recording",
    "электрон": "electron",
    "микроскоп": "microscopy",
    "соматосенсор": "somatosensory",
    "угрожающ": "threatening",
    "экг": "ECG electrocardiogram",
    "временн": "temporal",
    "сжат": "compression",
    "объединен": "fusion",
    "признак": "features",
    "замкнут": "closed-loop",
    "ноцицеп": "nociception",
    "клиническ": "clinical",
    "исход": "outcome",
    "ограничен": "constraint limitation",
    "набор": "dataset",
}
STOPWORDS = frozenset(
    "и в во на с со по для при от до без после the a an of in on with for to and".split()
)


def expand(query: str) -> str:
    original = query.casefold()
    remaining = original
    phrases = []
    for phrase, english in {
        "спинного мозга": "spinal cord",
        "спинной мозг": "spinal cord",
        "замкнутый контур": "closed-loop",
        "без обучения": "zero-shot",
    }.items():
        if phrase in remaining:
            phrases.extend(english.split())
            remaining = remaining.replace(phrase, " ")
    words = re.findall(r"[\w-]+", remaining)
    content = [w for w in words if w not in STOPWORDS]
    translations = []
    for word in content:
        for stem, english in TERMS.items():
            if word.startswith(stem):
                translations.extend(english.split())
    return " ".join(dict.fromkeys(re.findall(r"[\w-]+", original) + phrases + translations))
