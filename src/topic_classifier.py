"""Rule-based topic classifier for contract documents."""

import re
from typing import Dict


TOPIC_PATTERNS: Dict[str, str] = {
    "termination": r"(解除|解約|契約終了)",
    "payment": r"(支払|賃料|家賃|敷金|礼金|費用)",
    "repair": r"(修繕|故障|修理|原状回復)",
    "prohibited": r"(禁止|禁止事項|禁ずる)",
    "pets": r"(ペット|動物|飼育)",
    "smoking": r"(喫煙|禁煙|たばこ)",
    "noise": r"(騒音|近隣|迷惑)",
    "use": r"(使用|用途|利用)",
    "parking": r"(駐車|駐車場)",
    "garbage": r"(ゴミ|廃棄|分別)",
}


def classify_topic(text: str) -> str:
    """Classify topic from text using simple keyword matching."""
    for topic, pattern in TOPIC_PATTERNS.items():
        if re.search(pattern, text):
            return topic
    return "unknown"
