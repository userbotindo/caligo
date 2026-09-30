from typing import Any, Iterable, Mapping, Optional

import emoji.unicode_codes

ITEM_SEPARATOR = "\n    • "


def join_list(items: Iterable[str]) -> str:
    """Joins the given items into an indented bullet list."""

    return ITEM_SEPARATOR.join(items)


def join_map(
    items: Mapping[str, Any],
    heading: Optional[str] = None,
    parse_mode: str = "markdown",
) -> str:
    """Joins the given key-value pairs into an indented bullet list, with bolded labels."""

    if parse_mode == "html":
        start = "<b>"
        end = "</b>"
    else:
        start = "**"
        end = "**"

    return join_list(
        (
            *((f"{start}{heading}:{end}",) if heading else ()),
            *(f"{start}{key}:{end} {value}" for key, value in items.items()),
        )
    )


def has_emoji(text: str) -> bool:
    return any(c in emoji.unicode_codes.EMOJI_DATA for c in text)


LANGUAGE_ALIASES: dict[str, str] = {
    # Indonesian
    "id": "id", "ina": "id", "indo": "id", "indonesia": "id", "indonesian": "id",
    # English
    "en": "en", "eng": "en", "english": "en", "us": "en", "uk": "en",
    # Korean
    "ko": "ko", "kr": "ko", "kor": "ko", "korea": "ko", "korean": "ko",
    # Japanese
    "ja": "ja", "jp": "ja", "jpn": "ja", "japan": "ja", "japanese": "ja",
    # Chinese
    "zh": "zh-cn", "cn": "zh-cn", "chn": "zh-cn", "chinese": "zh-cn", "mandarin": "zh-cn",
    "zh-cn": "zh-cn", "zh-tw": "zh-tw", "tw": "zh-tw", "taiwan": "zh-tw", "hk": "zh-tw",
    # Russian
    "ru": "ru", "rus": "ru", "russia": "ru", "russian": "ru",
    # Spanish
    "es": "es", "esp": "es", "spanish": "es", "spain": "es",
    # French
    "fr": "fr", "fra": "fr", "french": "fr", "france": "fr",
    # German
    "de": "de", "ger": "de", "german": "de", "deutsch": "de",
    # Arabic
    "ar": "ar", "ara": "ar", "arab": "ar", "arabic": "ar",
    # Thai
    "th": "th", "tha": "th", "thai": "th", "thailand": "th",
    # Vietnamese
    "vi": "vi", "vie": "vi", "vietnam": "vi", "vietnamese": "vi",
    # Filipino / Tagalog
    "tl": "tl", "fil": "tl", "tagalog": "tl", "filipino": "tl", "ph": "tl",
    # Malay
    "ms": "ms", "mys": "ms", "malay": "ms", "malaysia": "ms",
    # Portuguese
    "pt": "pt", "por": "pt", "portuguese": "pt", "brazil": "pt", "br": "pt",
    # Italian
    "it": "it", "ita": "it", "italian": "it", "italy": "it",
    # Turkish
    "tr": "tr", "tur": "tr", "turkish": "tr", "turkey": "tr",
    # Hindi
    "hi": "hi", "hin": "hi", "hindi": "hi", "india": "hi",
    # Dutch
    "nl": "nl", "dut": "nl", "dutch": "nl", "netherlands": "nl",
}


def normalize_lang(token: str) -> str:
    """Normalizes language names or aliases to ISO 639-1 / BCP 47 language codes."""
    cleaned = token.strip().lower()
    if cleaned in LANGUAGE_ALIASES:
        return LANGUAGE_ALIASES[cleaned]
    return cleaned


LANGUAGES: dict[str, str] = {
    "af": "Afrikaans", "sq": "Albanian", "am": "Amharic", "ar": "Arabic", "hy": "Armenian",
    "az": "Azerbaijani", "eu": "Basque", "be": "Belarusian", "bn": "Bengali", "bs": "Bosnian",
    "bg": "Bulgarian", "ca": "Catalan", "ceb": "Cebuano", "ny": "Chichewa", "zh": "Chinese",
    "zh-cn": "Chinese (Simplified)", "zh-tw": "Chinese (Traditional)", "co": "Corsican",
    "hr": "Croatian", "cs": "Czech", "da": "Danish", "nl": "Dutch", "en": "English",
    "eo": "Esperanto", "et": "Estonian", "tl": "Filipino", "fi": "Finnish", "fr": "French",
    "fy": "Frisian", "gl": "Galician", "ka": "Georgian", "de": "German", "el": "Greek",
    "gu": "Gujarati", "ht": "Haitian Creole", "ha": "Hausa", "haw": "Hawaiian", "he": "Hebrew",
    "iw": "Hebrew", "hi": "Hindi", "hmn": "Hmong", "hu": "Hungarian", "is": "Icelandic",
    "ig": "Igbo", "id": "Indonesian", "ga": "Irish", "it": "Italian", "ja": "Japanese",
    "jw": "Javanese", "kn": "Kannada", "kk": "Kazakh", "km": "Khmer", "ko": "Korean",
    "ku": "Kurdish", "ky": "Kyrgyz", "lo": "Lao", "la": "Latin", "lv": "Latvian",
    "lt": "Lithuanian", "lb": "Luxembourgish", "mk": "Macedonian", "mg": "Malagasy",
    "ms": "Malay", "ml": "Malayalam", "mt": "Maltese", "mi": "Maori", "mr": "Marathi",
    "mn": "Mongolian", "my": "Myanmar (Burmese)", "ne": "Nepali", "no": "Norwegian",
    "ps": "Pashto", "fa": "Persian", "pl": "Polish", "pt": "Portuguese", "pa": "Punjabi",
    "ro": "Romanian", "ru": "Russian", "sm": "Samoan", "gd": "Scots Gaelic", "sr": "Serbian",
    "st": "Sesotho", "sn": "Shona", "sd": "Sindhi", "si": "Sinhala", "sk": "Slovak",
    "sl": "Slovenian", "so": "Somali", "es": "Spanish", "su": "Sundanese", "sw": "Swahili",
    "sv": "Swedish", "tg": "Tajik", "ta": "Tamil", "te": "Telugu", "th": "Thai",
    "tr": "Turkish", "uk": "Ukrainian", "ur": "Urdu", "ug": "Uyghur", "uz": "Uzbek",
    "vi": "Vietnamese", "cy": "Welsh", "xh": "Xhosa", "yi": "Yiddish", "yo": "Yoruba",
    "zu": "Zulu",
}

