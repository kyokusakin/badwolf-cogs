import re
from typing import List, Optional


DISCORD_MESSAGE_LIMIT = 2000
TRAILING_PUNCTUATION = ".,!?;:)]}"

TWITTER_STATUS_URL = re.compile(
    r"https?://(?:www\.|mobile\.)?(?:twitter\.com|x\.com)"
    r"/[A-Za-z0-9_]{1,15}/status(?:es)?/\d+"
    r"(?:[/?#][^\s<]*)?",
    re.IGNORECASE,
)

TWITTER_HOST = re.compile(
    r"^https?://(?:www\.|mobile\.)?(?:twitter\.com|x\.com)",
    re.IGNORECASE,
)


def has_twitter_status_url(content: str) -> bool:
    return bool(content and TWITTER_STATUS_URL.search(content))


def convert_twitter_url(url: str) -> str:
    trailing = ""

    while url and url[-1] in TRAILING_PUNCTUATION:
        trailing = url[-1] + trailing
        url = url[:-1]

    return TWITTER_HOST.sub("https://fxtwitter.com", url) + trailing


def replace_twitter_urls(content: str) -> str:
    return TWITTER_STATUS_URL.sub(lambda match: convert_twitter_url(match.group(0)), content)


def extract_converted_twitter_urls(content: str) -> List[str]:
    return [convert_twitter_url(match.group(0)) for match in TWITTER_STATUS_URL.finditer(content)]


def build_reply_content(original: str, converted: str) -> Optional[str]:
    if len(converted) <= DISCORD_MESSAGE_LIMIT:
        return converted

    urls = extract_converted_twitter_urls(original)
    if not urls:
        return None

    fallback = "\n".join(urls)
    if len(fallback) <= DISCORD_MESSAGE_LIMIT:
        return fallback

    kept = []
    current_length = 0
    for url in urls:
        added_length = len(url) + (1 if kept else 0)
        if current_length + added_length > DISCORD_MESSAGE_LIMIT:
            break

        kept.append(url)
        current_length += added_length

    return "\n".join(kept) if kept else None
