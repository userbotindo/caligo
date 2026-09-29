import base64
import binascii
import html
import random
import unicodedata
from typing import ClassVar, Optional, Tuple

import httpx

from caligo import command, module


class Text(module.Module):
    name: ClassVar[str] = "Text"

    @command.desc("Unicode character from hex codepoint")
    @command.usage("[hexadecimal Unicode codepoint]")
    async def cmd_uni(self, ctx: command.Context) -> str:
        codepoint = ctx.input
        try:
            return chr(int(codepoint, 16))
        except ValueError:
            return "__Input is out of Unicode's range of__ `0x00000` __to__ `0xFFFFF` __range.__"

    @command.desc("Apply a sarcasm/mocking filter to the given text")
    @command.usage("[text to filter]", reply=True)
    async def cmd_mock(self, ctx: command.Context) -> str:
        text = ctx.input
        if not text and ctx.msg.reply_to_message:
            text = ctx.msg.reply_to_message.text
        elif not text and not ctx.msg.reply_to_message:
            return "__Give me a text or reply to a message.__"

        chars = [*text]
        for idx, ch in enumerate(chars):
            ch = ch.upper() if random.choice((True, False)) else ch.lower()
            chars[idx] = ch

        return "".join(chars)

    @command.desc("Dissect a string into named Unicode codepoints")
    @command.usage("[text to dissect]", reply=True)
    async def cmd_charinfo(self, ctx: command.Context) -> str:
        text = ctx.input
        if not text and ctx.msg.reply_to_message:
            text = ctx.msg.reply_to_message.text
        elif not text and not ctx.msg.reply_to_message:
            return "__Give me a text or reply to a message.__"

        chars = []
        for char in text:
            # Don't preview characters that mess up the output
            preview = char not in "`"

            # Attempt to get the codepoint's name
            try:
                name: str = unicodedata.name(char)
            except ValueError:
                # Control characters don't have names, so insert a placeholder
                # and prevent the character from being rendered to avoid breaking
                # the output
                name = "UNNAMED CONTROL CHARACTER"
                preview = False

            # Render the line and only show the character if safe
            line = f"`U+{ord(char):04X}` {name}"
            if preview:
                line += f" `{char}`"

            chars.append(line)

        return "\n".join(chars)

    @command.desc("Replace the spaces in a string with clap emoji")
    @command.usage("[text to filter, or reply]", reply=True)
    async def cmd_clap(self, ctx: command.Context) -> str:
        text = ctx.input
        if not text and ctx.msg.reply_to_message:
            text = ctx.msg.reply_to_message.text
        elif not text and not ctx.msg.reply_to_message:
            return "__Give me a text or reply to a message.__"

        return "\n".join("👏".join(line.split()) for line in text.split("\n"))

    @command.desc("Encode text into Base64")
    @command.alias("b64encode", "b64e")
    @command.usage("[text to encode, or reply]", reply=True)
    async def cmd_base64encode(self, ctx: command.Context) -> str:
        text = ctx.input
        if not text and ctx.msg.reply_to_message:
            text = ctx.msg.reply_to_message.text
        elif not text and not ctx.msg.reply_to_message:
            return "__Give me a text or reply to a message.__"

        return base64.b64encode(text.encode("utf-8")).decode()

    @command.desc("Decode Base64 data")
    @command.alias("b64decode", "b64d")
    @command.usage("[base64 text to decode, or reply]", reply=True)
    async def cmd_base64decode(self, ctx: command.Context) -> str:
        text = ctx.input
        if not text and ctx.msg.reply_to_message:
            text = ctx.msg.reply_to_message.text
        elif not text and not ctx.msg.reply_to_message:
            return "__Give me a text or reply to a message.__"

        try:
            return base64.b64decode(text).decode("utf-8", "replace")
        except binascii.Error as e:
            return f"⚠️ Invalid Base64 data: {e}"

    async def _translate(
        self, text: str, source_lang: str, target_lang: str
    ) -> Tuple[Optional[str], Optional[str]]:
        http: Optional[httpx.AsyncClient] = getattr(self.bot, "http", None)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        # 1. Primary: Google GTX API (supports full sentences & Asian scripts: ko, ja, zh-cn, etc.)
        try:
            url = "https://translate.googleapis.com/translate_a/single"
            params = {
                "client": "gtx",
                "sl": source_lang,
                "tl": target_lang,
                "dt": "t",
                "q": text,
            }
            if http is not None:
                resp = await http.get(url, params=params, headers=headers, timeout=15)
            else:
                async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
                    resp = await client.get(url, params=params, headers=headers)

            if resp.status_code == 200:
                data = resp.json()
                if data and isinstance(data, list) and len(data) > 0 and isinstance(data[0], list):
                    translated = "".join(
                        s[0] for s in data[0] if s and isinstance(s, list) and len(s) > 0 and s[0]
                    )
                    detected = (
                        data[2]
                        if len(data) > 2 and isinstance(data[2], str)
                        else source_lang
                    )
                    if translated:
                        return translated, detected
        except Exception as e:
            self.log.debug("Google GTX translate failed: %s", e)

        # 2. Secondary: Google clients5 API
        try:
            url = "https://clients5.google.com/translate_a/t"
            params = {
                "client": "dict-chrome-ex",
                "sl": source_lang,
                "tl": target_lang,
                "q": text,
            }
            if http is not None:
                resp = await http.get(url, params=params, headers=headers, timeout=15)
            else:
                async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
                    resp = await client.get(url, params=params, headers=headers)

            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and len(data) > 0:
                    item = data[0]
                    if isinstance(item, list) and len(item) >= 2:
                        return item[0], item[1]
                    if isinstance(item, str):
                        return item, source_lang
        except Exception as e:
            self.log.debug("Google clients5 translate failed: %s", e)

        # 3. Tertiary: MyMemory API
        try:
            langpair = f"{source_lang if source_lang != 'auto' else 'en'}|{target_lang}"
            mm_url = "https://api.mymemory.translated.net/get"
            mm_params = {"q": text, "langpair": langpair}
            if http is not None:
                resp = await http.get(mm_url, params=mm_params, headers=headers, timeout=15)
            else:
                async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
                    resp = await client.get(mm_url, params=mm_params, headers=headers)

            if resp.status_code == 200:
                data = resp.json()
                translated = data.get("responseData", {}).get("translatedText")
                if translated and not translated.startswith("'AUTO' IS AN INVALID"):
                    return translated, source_lang
        except Exception as e:
            self.log.debug("MyMemory translate fallback failed: %s", e)

        return None, None

    @command.desc("Translate text to another language")
    @command.alias("tr")
    @command.usage("[lang? (e.g. 'id', 'ja', 'kr', 'ko-id')] [text?]", reply=True)
    async def cmd_translate(self, ctx: command.Context) -> str:
        reply = ctx.msg.reply_to_message
        raw_input = ctx.input.strip() if ctx.input else ""

        # Check for quoted text in reply or command
        quote_text = None
        if hasattr(ctx.msg, "quote") and ctx.msg.quote and ctx.msg.quote.text:
            quote_text = ctx.msg.quote.text
        elif reply:
            if hasattr(reply, "quote") and reply.quote and reply.quote.text:
                quote_text = reply.quote.text
            elif reply.entities:
                full_rep = reply.text or reply.caption or ""
                for ent in reply.entities:
                    if str(ent.type) in (
                        "MessageEntityType.BLOCKQUOTE",
                        "MessageEntityType.EXPANDABLE_BLOCKQUOTE",
                        "blockquote",
                        "expandable_blockquote",
                    ):
                        quote_text = full_rep[ent.offset : ent.offset + ent.length]
                        break

        reply_text = quote_text or ((reply.text or reply.caption) if reply else None)

        if not raw_input and not reply_text:
            return "__Give me text to translate or reply to a message.__"

        source_lang = "auto"
        target_lang = "id"
        text = ""

        if reply_text:
            if raw_input:
                token = raw_input.split()[0].lower()
                if "-" in token:
                    s, t = token.split("-", 1)
                    source_lang, target_lang = normalize_lang(s), normalize_lang(t)
                elif "/" in token:
                    s, t = token.split("/", 1)
                    source_lang, target_lang = normalize_lang(s), normalize_lang(t)
                else:
                    target_lang = normalize_lang(token)
            else:
                target_lang = "id"
            text = reply_text
        else:
            parts = raw_input.split(maxsplit=1)
            token = parts[0].lower()
            if "-" in token and len(parts) > 1:
                s, t = token.split("-", 1)
                source_lang, target_lang = normalize_lang(s), normalize_lang(t)
                text = parts[1]
            elif "/" in token and len(parts) > 1:
                s, t = token.split("/", 1)
                source_lang, target_lang = normalize_lang(s), normalize_lang(t)
                text = parts[1]
            elif (token in LANGUAGE_ALIASES or token in LANGUAGES) and len(parts) > 1:
                target_lang = normalize_lang(token)
                text = parts[1]
            else:
                target_lang = "id"
                text = raw_input

        if not text:
            return "__No text found to translate.__"

        translated_text, detected_lang = await self._translate(
            text, source_lang, target_lang
        )

        if not translated_text:
            return "⚠️ __Translation failed: Could not retrieve translation.__"

        det_clean = (detected_lang or "auto").lower().replace("_", "-")
        # If auto detected language is same as default target, auto switch
        if source_lang == "auto" and (det_clean == target_lang or det_clean.startswith(target_lang)):
            if target_lang == "id" and (not raw_input or raw_input == text):
                alt_tr, alt_det = await self._translate(text, "id", "en")
                if alt_tr:
                    translated_text = alt_tr
                    target_lang = "en"
                    detected_lang = alt_det or "id"
            elif target_lang == "en" and (not raw_input or raw_input == text):
                alt_tr, alt_det = await self._translate(text, "en", "id")
                if alt_tr:
                    translated_text = alt_tr
                    target_lang = "id"
                    detected_lang = alt_det or "en"

        det_code = (detected_lang or "auto").lower().replace("_", "-")
        src_name = LANGUAGES.get(det_code, LANGUAGES.get(det_code.split("-")[0], det_code.upper()))
        dst_code = target_lang.lower().replace("_", "-")
        dst_name = LANGUAGES.get(dst_code, LANGUAGES.get(dst_code.split("-")[0], dst_code.upper()))

        escaped_result = html.escape(translated_text)
        return (
            f"<blockquote>\n"
            f"{escaped_result}\n"
            f"</blockquote>\n"
            f"<b>{src_name}</b> (<code>{det_code}</code>) ➔ "
            f"<b>{dst_name}</b> (<code>{dst_code}</code>)"
        )


LANGUAGE_ALIASES = {
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
    cleaned = token.strip().lower()
    if cleaned in LANGUAGE_ALIASES:
        return LANGUAGE_ALIASES[cleaned]
    return cleaned


LANGUAGES = {
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

