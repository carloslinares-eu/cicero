"""The languages local models know. Unlike Google and DeepL, a local model can't be asked, so they are listed here."""

from __future__ import annotations

from cicero.core.translator import Language

# Code → English name. Codes are BCP-47 and are also what the prompts give the models.
NAMES = {
    "af": "Afrikaans", "am": "Amharic", "ar": "Arabic", "az": "Azerbaijani", "be": "Belarusian",
    "bg": "Bulgarian", "bn": "Bengali", "bo": "Tibetan", "bs": "Bosnian", "ca": "Catalan", "cs": "Czech",
    "cy": "Welsh", "da": "Danish", "de": "German", "el": "Greek", "en": "English", "en-GB": "English (UK)",
    "en-US": "English (US)", "eo": "Esperanto", "es": "Spanish", "es-MX": "Spanish (Mexico)", "et": "Estonian",
    "eu": "Basque", "fa": "Persian", "fi": "Finnish", "fil": "Filipino", "fr": "French", "fr-CA": "French (Canada)",
    "ga": "Irish", "gl": "Galician", "gu": "Gujarati", "ha": "Hausa", "he": "Hebrew", "hi": "Hindi",
    "hr": "Croatian", "hu": "Hungarian", "hy": "Armenian", "id": "Indonesian", "ig": "Igbo", "is": "Icelandic",
    "it": "Italian", "ja": "Japanese", "jv": "Javanese", "ka": "Georgian", "kk": "Kazakh", "km": "Khmer",
    "kn": "Kannada", "ko": "Korean", "ku": "Kurdish", "ky": "Kyrgyz", "la": "Latin", "lb": "Luxembourgish",
    "lo": "Lao", "lt": "Lithuanian", "lv": "Latvian", "mg": "Malagasy", "mk": "Macedonian", "ml": "Malayalam",
    "mn": "Mongolian", "mr": "Marathi", "ms": "Malay", "mt": "Maltese", "my": "Burmese", "ne": "Nepali",
    "nl": "Dutch", "no": "Norwegian", "pa": "Punjabi", "pl": "Polish", "ps": "Pashto", "pt": "Portuguese",
    "pt-BR": "Portuguese (Brazil)", "pt-PT": "Portuguese (Portugal)", "ro": "Romanian", "ru": "Russian",
    "si": "Sinhala", "sk": "Slovak", "sl": "Slovenian", "so": "Somali", "sq": "Albanian", "sr": "Serbian",
    "sv": "Swedish", "sw": "Swahili", "ta": "Tamil", "te": "Telugu", "tg": "Tajik", "th": "Thai", "tk": "Turkmen",
    "tr": "Turkish", "ug": "Uyghur", "uk": "Ukrainian", "ur": "Urdu", "uz": "Uzbek", "vi": "Vietnamese",
    "xh": "Xhosa", "yo": "Yoruba", "yue": "Cantonese", "zh-Hans": "Chinese (Simplified)",
    "zh-Hant": "Chinese (Traditional)", "zu": "Zulu",
}

# TranslateGemma's 55 evaluated languages (Google's WMT24++ set, with its regional variants).
TRANSLATEGEMMA = [
    "ar", "bg", "bn", "ca", "cs", "da", "de", "el", "en", "es", "es-MX", "et", "fa", "fi", "fil", "fr", "fr-CA",
    "gu", "he", "hi", "hr", "hu", "id", "is", "it", "ja", "kn", "ko", "lt", "lv", "ml", "mr", "nl", "no", "pa",
    "pl", "pt-BR", "pt-PT", "ro", "ru", "sk", "sl", "sr", "sv", "sw", "ta", "te", "th", "tr", "uk", "ur", "vi",
    "zh-Hans", "zh-Hant", "zu",
]

# Hy-MT2's languages, as listed on its model card.
HY_MT2 = [
    "zh-Hans", "en", "fr", "pt", "es", "ja", "tr", "ru", "ar", "ko", "th", "it", "de", "vi", "ms", "id", "fil",
    "hi", "zh-Hant", "pl", "cs", "nl", "km", "my", "fa", "gu", "ur", "te", "mr", "he", "bn", "ta", "uk", "bo",
    "kk", "mn", "ug", "yue",
]

# Hy-MT2 is prompted in Chinese, with Chinese language names, when Chinese is one of the two languages.
CHINESE_NAMES = {
    "zh-Hans": "中文", "zh-Hant": "繁体中文", "yue": "粤语", "en": "英语", "fr": "法语", "pt": "葡萄牙语",
    "es": "西班牙语", "ja": "日语", "tr": "土耳其语", "ru": "俄语", "ar": "阿拉伯语", "ko": "韩语", "th": "泰语",
    "it": "意大利语", "de": "德语", "vi": "越南语", "ms": "马来语", "id": "印尼语", "fil": "菲律宾语",
    "hi": "印地语", "pl": "波兰语", "cs": "捷克语", "nl": "荷兰语", "km": "高棉语", "my": "缅甸语", "fa": "波斯语",
    "gu": "古吉拉特语", "ur": "乌尔都语", "te": "泰卢固语", "mr": "马拉地语", "he": "希伯来语", "bn": "孟加拉语",
    "ta": "泰米尔语", "uk": "乌克兰语", "bo": "藏语", "kk": "哈萨克语", "mn": "蒙古语", "ug": "维吾尔语",
}
CHINESE_CODES = frozenset({"zh-Hans", "zh-Hant", "yue"})

# Every language in NAMES, for general models such as Qwen 3.5 that know hundreds.
GENERAL = sorted(NAMES)


def language_list(codes: list[str]) -> list[Language]:
    return sorted((Language(code, NAMES[code]) for code in codes), key=lambda language: language.name.casefold())


def name_of(code: str | None) -> str:
    return NAMES.get(code or "", code or "")


# What the language detector returns → the codes above.
_DETECTED = {"zh-cn": "zh-Hans", "zh-tw": "zh-Hant", "tl": "fil", "pt": "pt", "no": "no", "nb": "no"}


def from_detected(code: str, known: list[str]) -> str | None:
    """Map a detector code (``zh-cn``, ``pt``…) to one of ``known``, or None."""
    code = _DETECTED.get(code.lower(), code)
    if code in known:
        return code
    for candidate in known:  # "pt" → "pt-BR"/"pt-PT", "es" → "es": the first regional variant listed
        if candidate.split("-")[0] == code.split("-")[0]:
            return candidate
    return None
