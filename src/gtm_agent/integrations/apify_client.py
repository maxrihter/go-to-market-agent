"""Apify client: trigger scraper actors and read their datasets.

Used by the source connectors (Instagram profiles, Meta Ad Library, SimilarWeb). Reads
are fail-soft at the call site; this layer retries transient HTTP failures and deletes a
dataset after a successful fetch.
"""

from __future__ import annotations

from datetime import timedelta

from apify_client import ApifyClientAsync
from apify_client.errors import ApifyApiError
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from ..log import get_logger

logger = get_logger(__name__)

_RETRYABLE_STATUS = {429, 500, 502, 503}


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, ApifyApiError) and exc.status_code in _RETRYABLE_STATUS


_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception(_is_retryable),
    reraise=True,
)


@_retry
async def run_actor(
    api_token: str,
    actor_id: str,
    run_input: dict,
    *,
    timeout_secs: int = 600,
) -> str:
    """Trigger an Apify actor, wait for it, and return its default dataset id."""
    client = ApifyClientAsync(api_token)
    run = await client.actor(actor_id).call(
        run_input=run_input, run_timeout=timedelta(seconds=timeout_secs)
    )
    if run is None or not run.default_dataset_id:
        msg = f"apify actor {actor_id!r} returned no dataset"
        raise RuntimeError(msg)
    logger.info("apify_actor_run", actor=actor_id, dataset_id=run.default_dataset_id)
    return run.default_dataset_id


@_retry
async def fetch_dataset(api_token: str, dataset_id: str) -> list[dict]:
    """Fetch all items from an Apify dataset, then delete it.

    Deletion runs AFTER a successful fetch so a retry re-reads the same dataset rather
    than hitting a 404.
    """
    client = ApifyClientAsync(api_token)
    dataset_client = client.dataset(dataset_id)

    items: list[dict] = []
    async for item in dataset_client.iterate_items():
        items.append(item)

    logger.info("apify_dataset_fetched", dataset_id=dataset_id, item_count=len(items))

    try:
        await dataset_client.delete()
        logger.info("apify_dataset_deleted", dataset_id=dataset_id)
    except ApifyApiError as exc:
        if exc.status_code == 404:
            logger.info("apify_dataset_already_deleted", dataset_id=dataset_id)
        else:
            logger.warning("apify_dataset_delete_failed", dataset_id=dataset_id, error=str(exc))

    return items
