"""Centralized lifecycle-managed Gemini API client factory."""

from __future__ import annotations

import threading
from typing import Optional

from google import genai
from google.genai import types

from ...core.ai_config import AIProviderSettings


class GeminiClientManager:
    """Thread-safe lifecycle wrapper for `google.genai.Client` with shutdown signal."""

    def __init__(
        self,
        settings: AIProviderSettings,
        *,
        client: Optional[genai.Client] = None,
    ) -> None:
        self._settings = settings
        self._client: Optional[genai.Client] = client
        self._owns_client = client is None
        self._lock = threading.RLock()
        self.shutdown_event = threading.Event()

    @property
    def settings(self) -> AIProviderSettings:
        return self._settings

    @property
    def is_configured(self) -> bool:
        return self._client is not None or self._settings.is_gemini_configured

    @property
    def is_initialized(self) -> bool:
        return self._client is not None

    def get_client(self) -> genai.Client:
        """Return an initialized Gemini SDK client, creating it lazily if needed."""
        with self._lock:
            self.shutdown_event.clear()
            if self._client is not None:
                return self._client
            self._settings.validate_gemini_ready()
            timeout_ms = max(1000, int(self._settings.gemini_timeout_seconds * 1000))
            http_options = types.HttpOptions(
                timeout=timeout_ms,
                retry_options=types.HttpRetryOptions(attempts=1),
            )
            self._client = genai.Client(
                api_key=self._settings.gemini_api_key,
                http_options=http_options,
            )
            self._owns_client = True
            return self._client

    def close(self) -> None:
        """Signal active waits to stop and close the underlying Gemini HTTP transport."""
        self.shutdown_event.set()
        with self._lock:
            if self._client is not None and self._owns_client:
                try:
                    self._client.close()
                except Exception:
                    pass
            self._client = None
