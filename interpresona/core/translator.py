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
            cleaned = re.sub(r"⟪\d+⟫", "", text).strip()
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
        for i, text in enumerate(texts):
            # If the text consists purely of placeholders, spaces, and punctuation symbols,
            # we do not need to send it to the MT engine (it would likely get corrupted or return '⟪').
            # We simply return the input string unmodified.
            import re
            cleaned = re.sub(r"⟪\d+⟫", "", text).strip()
            # If nothing remains except punctuation/spaces, bypass translation
            if not cleaned or re.match(r"^[ \t\r\n.,;:!?'\"`~@#$%^&*()_+={}\[\]|\\<>\-※\ue000-\ue0ff]*$", cleaned):
                results.append(text)
            else:
                results.append(self._translate_one(text))
            
            # Periodically allow Tkinter to refresh its window messages and draw updates 
            # to prevent Windows from marking the app as "Not Responding" during long loops
            try:
                import tkinter as tk
                # Get the active tk root instance if it exists and update it
                root = tk._default_root
                if root:
                    root.update()
            except Exception:
                pass
                
            if i < len(texts) - 1 and self._delay > 0:
                time.sleep(self._delay)
        return results

    def _translate_one(self, text: str) -> str:
        # Mode 1: Standard LibreTranslate POST JSON API
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
            with urllib.request.urlopen(req_post, context=ctx, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["translatedText"]
        except (urllib.error.HTTPError, urllib.error.URLError) as exc:
            # Check if we should fallback to Mode 2 (GET URL Mode)
            # 405 Method Not Allowed or 400 Bad Request usually indicate custom bridge or wrong API format
            is_fallback_error = False
            if isinstance(exc, urllib.error.HTTPError) and exc.code in (400, 403, 405):
                is_fallback_error = True
            elif not isinstance(exc, urllib.error.HTTPError):
                # Network or SSL issues might not support fallback, but we can try
                is_fallback_error = False

            if not is_fallback_error:
                # Re-raise standard error if it is a real connection/auth issue
                body_err = ""
                if isinstance(exc, urllib.error.HTTPError):
                    body_err = exc.read().decode("utf-8", errors="replace")[:200]
                raise TranslationError(f"LibreTranslate API failed: {exc} {body_err}") from exc

            # Mode 2: GET URL Mode (GET /translate?text=...&from=...&to=...)
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
                with urllib.request.urlopen(req_get, context=ctx, timeout=5) as resp:
                    # Renders directly as plain text (e.g. "Ciao")
                    return resp.read().decode("utf-8").strip()
            except Exception as get_exc:
                raise TranslationError(f"LibreTranslate both POST and GET fallback failed. GET error: {get_exc}") from get_exc
        except Exception as exc:
            raise TranslationError(f"LibreTranslate request failed: {exc}") from exc


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
            _TOKEN = re.compile(r"(⟪\d+⟫)")
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
