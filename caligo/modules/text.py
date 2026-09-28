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
        url = "https://clients5.google.com/translate_a/t"
        params = {
            "client": "dict-chrome-ex",
            "sl": source_lang,
            "tl": target_lang,
            "q": text,
        }
        http = getattr(self.bot, "http", None)

        # 1. Primary: Google clients5 API
        try:
            if http is not None:
                resp = await http.get(url, params=params, timeout=15)
            else:
                async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
                    resp = await client.get(url, params=params)

            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and len(data) > 0:
                    item = data[0]
                    if isinstance(item, list) and len(item) >= 2:
                        return item[0], item[1]
                    if isinstance(item, str):
                        return item, source_lang
        except Exception as e:
            self.log.warning(f"Google translate request failed: {e}")

        # 2. Fallback: MyMemory API
        try:
            langpair = f"{source_lang if source_lang != 'auto' else 'en'}|{target_lang}"
            mm_url = "https://api.mymemory.translated.net/get"
            mm_params = {"q": text, "langpair": langpair}
            if http is not None:
                resp = await http.get(mm_url, params=mm_params, timeout=15)
            else:
                async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
                    resp = await client.get(mm_url, params=mm_params)

            if resp.status_code == 200:
                data = resp.json()
                translated = data.get("responseData", {}).get("translatedText")
                if translated and not translated.startswith("'AUTO' IS AN INVALID"):
                    return translated, source_lang
        except Exception as e:
            self.log.warning(f"MyMemory translate fallback failed: {e}")

        return None, None

    @command.desc("Translate text to another language")
    @command.alias("tr")
    @command.usage("[lang? (e.g. 'id', 'ja', 'en-id')] [text?]", reply=True)
    async def cmd_translate(self, ctx: command.Context) -> str:
        reply = ctx.msg.reply_to_message
        reply_text = (reply.text or reply.caption) if reply else None
        raw_input = ctx.input.strip() if ctx.input else ""

        if not raw_input and not reply_text:
            return "__Give me text to translate or reply to a message.__"

        source_lang = "auto"
        target_lang = "en"
        text = ""

        if reply_text:
            if raw_input:
                token = raw_input.split()[0].lower()
                if "-" in token:
                    source_lang, target_lang = token.split("-", 1)
                elif "/" in token:
                    source_lang, target_lang = token.split("/", 1)
                else:
                    target_lang = token
            text = reply_text
        else:
            parts = raw_input.split(maxsplit=1)
            token = parts[0].lower()
            if "-" in token and len(parts) > 1:
                source_lang, target_lang = token.split("-", 1)
                text = parts[1]
            elif "/" in token and len(parts) > 1:
                source_lang, target_lang = token.split("/", 1)
                text = parts[1]
            elif token in LANGUAGES and len(parts) > 1:
                target_lang = token
                text = parts[1]
            else:
                text = raw_input

        if not text:
            return "__No text found to translate.__"

        translated_text, detected_lang = await self._translate(
            text, source_lang, target_lang
        )

        if not translated_text:
            return "⚠️ __Translation failed: Could not retrieve translation.__"

        # If detected language matches default target language (en), translate to Indonesian (id)
        if (
            source_lang == "auto"
            and detected_lang == target_lang
            and target_lang == "en"
            and (not raw_input or raw_input == text)
        ):
            alt_translated, alt_detected = await self._translate(text, "en", "id")
            if alt_translated:
                translated_text = alt_translated
                target_lang = "id"
                detected_lang = alt_detected or "en"

        src_name = LANGUAGES.get(
            (detected_lang or "auto").lower(), (detected_lang or "auto").upper()
        )
        dst_name = LANGUAGES.get(target_lang.lower(), target_lang.upper())
        src_code = detected_lang or "auto"

        escaped_result = html.escape(translated_text)
        return (
            f"<blockquote expandable>{escaped_result}\n\n"
            f"<b>{src_name}</b> (<code>{src_code}</code>) ➔ "
            f"<b>{dst_name}</b> (<code>{target_lang}</code>)</blockquote>"
        )


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

