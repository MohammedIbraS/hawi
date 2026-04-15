"""
Shared utilities for all scrapers.
"""
import time
import httpx
from loguru import logger


def http_get_with_retry(
    client: httpx.Client,
    url: str,
    *,
    max_retries: int = 3,
    base_delay: float = 2.0,
    **kwargs,
) -> httpx.Response:
    """
    GET url with simple exponential-backoff retry for transient network errors.

    Retries on:
      - httpx.TimeoutException  (DNS timeout, read timeout)
      - httpx.ConnectError      (peer connection closed, name resolution failure)
      - HTTP 429 / 503 / 502    (rate-limit or temporary server error)

    Raises the last exception if all retries are exhausted.
    """
    delay = base_delay
    last_exc: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            resp = client.get(url, **kwargs)
            if resp.status_code in (429, 502, 503):
                raise httpx.HTTPStatusError(
                    f"HTTP {resp.status_code}",
                    request=resp.request,
                    response=resp,
                )
            return resp
        except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError) as exc:
            last_exc = exc
            if attempt == max_retries:
                break
            logger.warning(
                f"Transient error fetching {url} (attempt {attempt}/{max_retries}): {exc}. "
                f"Retrying in {delay:.0f}s…"
            )
            time.sleep(delay)
            delay = min(delay * 2, 30)

    raise last_exc  # type: ignore[misc]
