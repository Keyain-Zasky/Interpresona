"""
Machine Translation Backends
==============================
Provides a unified interface to multiple MT engines.
All backends take a list of plain-text strings and return translated strings.
Control-code placeholders (⟪VAR_n⟫) are preserved because the masker
removes them BEFORE calling the MT engine.

Supported backends
------------------
- DeepL        — https://www.deepl.com/pro-api  (requires API key)
- LibreTranslate — https://libretranslate.com    (self-hosted or public)
- MockTranslator — for testing (prepends a tag, no network needed)

Usage
-----
    translator = DeepLTranslator(api_key="...", source_lang="JA", target_lang="EN-GB")
    results = translator.translate(["Hello", "World"])
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from typing import Optional


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class BaseTranslator(ABC):
    """All MT backends must implement this interface."""

    name: str = "base"

    @abstractmethod
    def translate(self, texts: list[str]) -> list[str]:
        """
        Translate a batch of strings.
        Returns exactly len(texts) translated strings.
        Raises TranslationError on failure.
        """
        ...

    def translate_one(self, text: str) -> str:
        return self.translate([text])[0]


class TranslationError(Exception):
    """Raised when an MT backend returns an error."""


# ---------------------------------------------------------------------------
# DeepL backend
# ---------------------------------------------------------------------------

class DeepLTranslator(BaseTranslator):
    """
    DeepL API v2 translator.
    Free tier:  api-free.deepl.com  (api_key ends in ':fx')
    Pro tier:   api.deepl.com

    Batch limit: DeepL accepts up to 50 texts per request.
    """

    name = "DeepL"
    BATCH_SIZE = 50

    def __init__(
        self,
        api_key: str,
        target_lang: str = "EN-GB",
        source_lang: Optional[str] = None,
        formality: str = "default",
    ):
        self._api_key = api_key.strip()
        self._target = target_lang.upper()
        self._source = source_lang.upper() if source_lang else None
        self._formality = formality
        # Choose endpoint based on key suffix
        if self._api_key.endswith(":fx"):
            self._endpoint = "https://api-free.deepl.com/v2/translate"
        else:
            self._endpoint = "https://api.deepl.com/v2/translate"

    def translate(self, texts: list[str]) -> list[str]:
        # Filter out indices with no translatable content (pure placeholders, punctuation)
        import re
        results = [None] * len(texts)
        pending_indices = []
        pending_batch = []
        
        for idx, text in enumerate(texts):
            cleaned = re.sub(r"\{\d+\}", "", text).strip()
            if not cleaned or re.match(r"^[ \t\r\n.,;:!?'\"`~@#$%^&*()_+={}\[\]|\\<>\-※\ue000-\ue0ff]*$", cleaned):
                results[idx] = text
            else:
                pending_indices.append(idx)
                pending_batch.append(text)
                
        if pending_batch:
            translated_results = []
            for i in range(0, len(pending_batch), self.BATCH_SIZE):
                batch = pending_batch[i: i + self.BATCH_SIZE]
                translated_results.extend(self._translate_batch(batch))
            for idx, trans in zip(pending_indices, translated_results):
                results[idx] = trans
                
        return results

    def _translate_batch(self, texts: list[str]) -> list[str]:
        params: dict = {
            "target_lang": self._target,
            "formality": self._formality,
        }
        if self._source:
            params["source_lang"] = self._source

        # DeepL API accepts multiple `text` params
        body_parts = [f"text={urllib.parse.quote(t)}" for t in texts]
        body_parts += [f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items()]
        body = "&".join(body_parts).encode("utf-8")

        req = urllib.request.Request(
            self._endpoint,
            data=body,
            headers={
                "Authorization": f"DeepL-Auth-Key {self._api_key}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        try:
            import ssl
            ctx = ssl._create_unverified_context()
            with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return [item["text"] for item in data["translations"]]
        except urllib.error.HTTPError as exc:
            body_err = exc.read().decode("utf-8", errors="replace")
            raise TranslationError(
                f"DeepL HTTP {exc.code}: {body_err[:200]}"
            ) from exc
        except Exception as exc:
            raise TranslationError(f"DeepL request failed: {exc}") from exc

    def get_usage(self) -> dict:
        """Return current character usage (count + limit)."""
        req = urllib.request.Request(
            self._endpoint.replace("/translate", "/usage"),
            headers={"Authorization": f"DeepL-Auth-Key {self._api_key}"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# LibreTranslate backend
# ---------------------------------------------------------------------------

class LibreTranslateTranslator(BaseTranslator):
    """
    LibreTranslate open-source MT engine.
    Can be self-hosted or use the public API at https://libretranslate.com.

    Batch limit: LibreTranslate translates one string at a time.
    We send them sequentially with a small delay to avoid rate-limiting.
    """

    name = "LibreTranslate"

    def __init__(
        self,
        url: str = "https://libretranslate.com",
        api_key: str = "",
        source_lang: str = "ja",
        target_lang: str = "en",
        delay_ms: int = 100,
    ):
        self._url = url.rstrip("/")
        self._api_key = api_key
        self._source = source_lang
        self._target = target_lang
        self._delay = delay_ms / 1000.0

    def translate(self, texts: list[str]) -> list[str]:
        results = []
        import re
        for i, text in enumerate(texts):
            cleaned = re.sub(r"\{\d+\}", "", text).strip()
            is_bypass = False
            if not cleaned:
                is_bypass = True
            elif re.match(r"^[ \t\r\n.,;:!?'\"`~@#$%^&*()_+={}\[\]|\\<>\-※《》\/\\%0-9\ue000-\ue0ff]*$", cleaned):
                is_bypass = True
            elif cleaned.lower() in ("m", "h", "d", "s", "ms", "sec", "min", "hr", "day", "lv", "lv.", "xp", "hp", "mp", "gp", "cp"):
                is_bypass = True
            elif len(re.findall(r"[a-zA-Z]", cleaned)) < 3:
                is_bypass = True

            if is_bypass:
                results.append(text)
            else:
                results.append(self._translate_one(text))
            
            try:
                import tkinter as tk
                root = tk._default_root
                if root:
                    root.update()
            except Exception:
                pass
                
            if i < len(texts) - 1 and self._delay > 0:
                time.sleep(self._delay)
        return results

    def _translate_one(self, text: str) -> str:
        import re
        # Normalize English possessive {n}'s -> {n} so NMT parser does not drop {n}
        prep = re.sub(r"\{(\d+)\}\s*\'s", r"{\1}", text)
        padded = re.sub(r"([^\s\{])\{(\d+)\}", r"\1 {\2}", prep)
        padded = re.sub(r"\{(\d+)\}([^\s\}])", r"{\1} \2", padded)

        for attempt in range(3):
            try:
                res = self._raw_translate_request(padded)
                res = re.sub(r"\s+", " ", res).strip()
                return res
            except Exception as exc:
                if attempt == 2:
                    return text
                time.sleep(0.5 * (attempt + 1))
        return text

    def _raw_translate_request(self, text: str) -> str:
        payload = {
            "q": text,
            "source": self._source,
            "target": self._target,
            "format": "text",
        }
        if self._api_key:
            payload["api_key"] = self._api_key

        body = json.dumps(payload).encode("utf-8")
        req_post = urllib.request.Request(
            f"{self._url}/translate",
            data=body,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
            },
            method="POST",
        )

        import ssl
        ctx = ssl._create_unverified_context()

        try:
            with urllib.request.urlopen(req_post, context=ctx, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["translatedText"]
        except Exception as exc:
            # Fallback to Mode 2: GET URL Mode
            query = urllib.parse.urlencode({
                "text": text,
                "from": self._source,
                "to": self._target
            })
            req_get = urllib.request.Request(
                f"{self._url}/translate?{query}",
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
                },
                method="GET",
            )
            try:
                with urllib.request.urlopen(req_get, context=ctx, timeout=15) as resp:
                    return resp.read().decode("utf-8").strip()
            except Exception as get_exc:
                raise TranslationError(f"LibreTranslate GET fallback failed: {get_exc}") from get_exc


# ---------------------------------------------------------------------------
# Mock backend (for testing without a real API)
# ---------------------------------------------------------------------------

class MockTranslator(BaseTranslator):
    """
    Fake translator for testing — appends '[EN]' and uppercases the text.
    Does NOT modify ⟪VAR_n⟫ placeholders.
    """

    name = "Mock"

    def __init__(self, prefix: str = "[EN] "):
        self._prefix = prefix

    def translate(self, texts: list[str]) -> list[str]:
        results = []
        for text in texts:
            # Only transform plain text — leave placeholder tokens untouched
            # Split on ⟪...⟫ tokens and transform non-token parts
            import re
            _TOKEN = re.compile(r"(\{\d+\})")
            parts = _TOKEN.split(text)
            transformed = []
            for part in parts:
                if _TOKEN.fullmatch(part):
                    transformed.append(part)  # keep placeholder intact
                else:
                    transformed.append(part.upper() if part else part)
            results.append(self._prefix + "".join(transformed))
        return results


# ---------------------------------------------------------------------------
# Translator registry
# ---------------------------------------------------------------------------

BACKENDS: dict[str, type[BaseTranslator]] = {
    "deepl": DeepLTranslator,
    "libretranslate": LibreTranslateTranslator,
    "mock": MockTranslator,
}
