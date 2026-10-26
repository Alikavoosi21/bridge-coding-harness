"""Fetch model IDs from the endpoint the user explicitly connected.

Credentials stay in headers; no redirects, provider bodies or secrets are
returned. A catalog is availability metadata, not proof of tool support.
"""
import asyncio
import json
from urllib.parse import urlsplit

import httpx

from .errors import ApiError


async def discover_models(base_url: str, api_key: str) -> dict:
    parts = urlsplit(base_url.strip())
    if parts.scheme not in {'http', 'https'} or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ApiError('invalid_request', 'نشانی سرویس معتبر نیست؛ Base URL را بدون کلید یا پارامتر وارد کن.', status_code=422)
    base = base_url.strip().rstrip('/')
    anthropic = parts.hostname == 'api.anthropic.com'
    url = base + ('/v1/models' if anthropic and not parts.path.rstrip('/').endswith('/v1') else '/models')
    headers = {'Accept': 'application/json'}
    if api_key:
        headers.update({'x-api-key': api_key, 'anthropic-version': '2023-06-01'} if anthropic else {'Authorization': 'Bearer ' + api_key})

    async def fetch():
        async with httpx.AsyncClient(timeout=10, follow_redirects=False, trust_env=False) as client:
            async with client.stream('GET', url, headers=headers) as response:
                if response.status_code in {401, 403}:
                    raise ApiError('provider_auth', 'سرویس این کلید را نپذیرفت یا اجازهٔ فهرست مدل‌ها را نداده است.', status_code=400)
                if response.status_code in {404, 405}:
                    raise ApiError('model_catalog_unsupported', 'این سرویس فهرست مدل‌ها نمی‌دهد؛ نام مدل را دستی وارد کن.', status_code=400)
                if 300 <= response.status_code < 400:
                    raise ApiError('provider_redirect', 'نشانی سرویس تغییر مسیر داد؛ نشانی نهایی سرویس را وارد کن.', status_code=400)
                if not response.is_success:
                    raise ApiError('provider_error', 'دریافت فهرست مدل‌ها ممکن نشد؛ بعداً دوباره امتحان کن.', status_code=400, retryable=True)
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 2_000_000:
                        raise ApiError('provider_response_invalid', 'فهرست مدل‌های سرویس بیش از حد بزرگ است.', status_code=400)
                return json.loads(body)
    try:
        payload = await asyncio.wait_for(fetch(), timeout=15)
    except (httpx.HTTPError, asyncio.TimeoutError) as error:
        raise ApiError('provider_unreachable', 'اتصال به سرویس ممکن نشد؛ نشانی و شبکه را بررسی کن.', status_code=400, retryable=True) from None
    except (ValueError, UnicodeError):
        raise ApiError('provider_response_invalid', 'پاسخ سرویس یک فهرست معتبر از مدل‌ها نیست.', status_code=400) from None
    rows = payload.get('data', payload.get('models')) if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ApiError('model_catalog_unsupported', 'این سرویس فهرست سازگار ندارد؛ نام مدل را دستی وارد کن.', status_code=400)
    models = {}
    for row in rows[:2000]:
        if not isinstance(row, dict):
            continue
        identifier = row.get('id') or row.get('name')
        if not isinstance(identifier, str) or not identifier or len(identifier) > 256 or any(ord(c) < 32 for c in identifier) or (api_key and api_key in identifier):
            continue
        label = row.get('display_name') or row.get('name') or identifier
        if not isinstance(label, str):
            label = identifier
        models[identifier] = {'id': identifier, 'name': label[:256].replace(api_key, '[redacted]') if api_key else label[:256]}
    return {'models': sorted(models.values(), key=lambda item: item['id']), 'partial': bool(payload.get('has_more')) or len(rows) > 2000}
