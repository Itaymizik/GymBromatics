"""Single-request Gemini adapter. No paid fallback, tool use or automatic retries."""
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from typing import Any, Protocol
import urllib.error
import urllib.request


MODEL = 'gemini-3.1-flash-lite'


class FeedbackError(RuntimeError):
    """Safe error code: never includes credentials or upstream response bodies."""


class FeedbackProvider(Protocol):
    model: str

    def generate(self, system: str, evidence: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]: ...


def load_settings(path: Path = Path('.env.local')) -> dict[str, str]:
    """Read only these keys; no execution, interpolation or environment mutation."""
    names = ('GEMINI_API_KEY', 'GEMINI_FREE_TIER_CONFIRMED')
    settings = {}
    if path.is_file():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            key, separator, value = line.strip().partition('=')
            if separator and key.strip() in names:
                settings[key.strip()] = value.strip().strip('\"\'')
    for key in names:
        if key in os.environ:
            settings[key] = os.environ[key].strip()
    return settings


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


@dataclass(frozen=True)
class GeminiFreeTier:
    api_key: str = field(repr=False)
    free_tier_confirmed: bool = False
    model: str = field(default=MODEL, init=False)
    timeout_seconds: int = 90

    @classmethod
    def from_env(cls, path: Path = Path('.env.local')) -> 'GeminiFreeTier':
        settings = load_settings(path)
        return cls(settings.get('GEMINI_API_KEY', ''), settings.get('GEMINI_FREE_TIER_CONFIRMED', '').lower() == 'true')

    def generate(self, system: str, evidence: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key or '\n' in self.api_key or '\r' in self.api_key:
            raise FeedbackError('missing_api_key')
        if not self.free_tier_confirmed:
            raise FeedbackError('free_tier_not_confirmed')
        body = {
            'systemInstruction': {'parts': [{'text': system}]},
            'contents': [{'role': 'user', 'parts': [{'text': json.dumps(evidence, ensure_ascii=False, allow_nan=False)}]}],
            'generationConfig': {'temperature': .2, 'maxOutputTokens': 8192,
                                 'responseMimeType': 'application/json', 'responseJsonSchema': schema},
        }
        request = urllib.request.Request(
            f'https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent',
            data=json.dumps(body, ensure_ascii=False, allow_nan=False).encode('utf-8'),
            headers={'Content-Type': 'application/json', 'x-goog-api-key': self.api_key}, method='POST')
        try:
            with urllib.request.build_opener(_NoRedirect()).open(request, timeout=self.timeout_seconds) as response:
                payload = response.read(1_000_001)
            if len(payload) > 1_000_000:
                raise FeedbackError('response_too_large')
            envelope = json.loads(payload)
            if envelope.get('promptFeedback', {}).get('blockReason'):
                raise FeedbackError('provider_blocked')
            candidates = envelope.get('candidates', [])
            if len(candidates) != 1 or candidates[0].get('finishReason') != 'STOP':
                raise FeedbackError('incomplete_or_blocked_response')
            parts = candidates[0]['content']['parts']
            result = json.loads(''.join(p.get('text', '') for p in parts if not p.get('thought')))
            return {'content': result, 'usage': envelope.get('usageMetadata', {}),
                    'model_version': envelope.get('modelVersion', MODEL)}
        except urllib.error.HTTPError as error:
            # Never expose upstream messages, headers or the key-bearing request.
            code = {400:'request_rejected',401:'authentication_failed',403:'access_denied',
                    404:'model_unavailable',429:'quota_exceeded'}.get(error.code, 'provider_http_error')
            raise FeedbackError(code) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise FeedbackError('network_or_timeout') from None
        except (ValueError, KeyError, TypeError, AttributeError):
            raise FeedbackError('invalid_provider_response') from None
