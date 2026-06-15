"""Secret redaction — scans and redacts secrets from tool output.

Based on Hermes' security.redact_secrets, this module applies regex-based
redaction to all tool outputs before they are injected into the conversation context.
"""

from __future__ import annotations

import re
from typing import List, Tuple


class SecretRedactor:
    """Scans and redacts secrets from tool output."""

    PATTERNS: List[Tuple[str, str]] = [
        # API keys: sk-..., pk-..., rk-...
        (r'(sk|pk|rk)-(?:[a-zA-Z0-9]{4,}-){0,5}[a-zA-Z0-9]{4,}', '[REDACTED_KEY]'),
        # GitHub tokens: ghp_..., gho_..., github_pat_...
        (r'gh[poat]_[a-zA-Z0-9]{16,}', '[REDACTED_GH_TOKEN]'),
        # OpenAI keys: sk-proj-..., sk-admin-...
        (r'sk-(?:proj|admin|org)-[a-zA-Z0-9]{16,}', '[REDACTED_OPENAI_KEY]'),
        # AWS keys: AKIA...
        (r'AKIA[0-9A-Z]{16}', '[REDACTED_AWS_KEY]'),
        # JWT tokens: eyJ...
        (r'eyJ[a-zA-Z0-9_-]{20,}\.[a-zA-Z0-9_-]{20,}\.[a-zA-Z0-9_-]{10,}', '[REDACTED_JWT]'),
        # Generic key=value with 'secret' or 'password'
        (r'(?:secret|password|token|api[_-]?key)\s*[:=]\s*\S+', '[REDACTED_CREDENTIAL]'),
        # Private key markers
        (r'-----BEGIN (?:RSA|EC|DSA|OPENSSH) PRIVATE KEY-----', '[REDACTED_PRIVATE_KEY]'),
        # Bearer tokens (common in Authorization headers)
        (r'bearer\s+[a-zA-Z0-9_\-\.]+', '[REDACTED_BEARER]'),
    ]

    def redact(self, text: str) -> tuple[str, int]:
        """Returns (redacted_text, count_of_redactions)."""
        count = 0
        for pattern, replacement in self.PATTERNS:
            new_text, n = re.subn(pattern, replacement, text, flags=re.IGNORECASE)
            count += n
            text = new_text
        return text, count
