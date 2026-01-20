"""Utility functions for pjsk plugin."""

import unicodedata
from asyncio import Semaphore
from enum import Enum, auto
from functools import lru_cache
from typing import (
    Any,
    Awaitable,
    Callable,
    Iterable,
    List,
    Literal,
    Optional,
    Sequence,
    Type,
    TypeVar,
    Union,
    overload,
)

from httpx import AsyncClient, Limits

from .config import config


# Global HTTP client for connection pooling
_http_client: Optional[AsyncClient] = None


def get_http_client() -> AsyncClient:
    """Get or create a global HTTP client with connection pooling."""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = AsyncClient(
            proxy=config.pjsk_req_proxy,
            timeout=config.pjsk_req_timeout,
            limits=Limits(
                max_connections=50,
                max_keepalive_connections=20,
                keepalive_expiry=30.0,
            ),
        )
    return _http_client


async def close_http_client() -> None:
    """Close the global HTTP client."""
    global _http_client
    if _http_client is not None and not _http_client.is_closed:
        await _http_client.aclose()
        _http_client = None


T = TypeVar("T")
TN = TypeVar("TN", int, float)
TA = TypeVar("TA")
TB = TypeVar("TB")
R = TypeVar("R")


class ResponseType(Enum):
    JSON = auto()
    TEXT = auto()
    BYTES = auto()


@overload
async def async_request(
    *urls: str,
    response_type: Literal[ResponseType.JSON],
    retries: int = ...,
) -> Any: ...


@overload
async def async_request(
    *urls: str,
    response_type: Literal[ResponseType.TEXT],
    retries: int = ...,
) -> str: ...


@overload
async def async_request(
    *urls: str,
    response_type: ResponseType = ResponseType.BYTES,
    retries: int = ...,
) -> bytes: ...


async def async_request(
    *urls: str,
    response_type: ResponseType = ResponseType.BYTES,
    retries: int = config.pjsk_req_retry,
) -> Any:
    """Async HTTP request with retry and fallback URLs.

    Uses a global HTTP client with connection pooling for better performance.
    """
    if not urls:
        raise ValueError("No URL specified")

    url, rest = urls[0], urls[1:]
    try:
        client = get_http_client()
        response = await client.get(url)
        response.raise_for_status()
        if response_type == ResponseType.JSON:
            return response.json()
        if response_type == ResponseType.TEXT:
            return response.text
        return response.read()

    except Exception as e:
        err_suffix = (
            f"error occurred while requesting {url}: {e.__class__.__name__}: {e}"
        )
        if retries <= 0:
            if not rest:
                raise
            # Try next URL
            return await async_request(*rest, response_type=response_type)

        retries -= 1
        return await async_request(*urls, response_type=response_type, retries=retries)


def append_prefix(suffix: str, prefixes: Sequence[str]) -> List[str]:
    """Append suffix to each prefix."""
    return [prefix + suffix for prefix in prefixes]


def with_semaphore(semaphore: Semaphore):
    """Decorator to limit concurrency using semaphore."""

    def decorator(func: Callable[..., Awaitable[R]]):
        async def wrapper(*args, **kwargs) -> R:
            async with semaphore:
                return await func(*args, **kwargs)

        return wrapper

    return decorator


def chunks(iterable: Sequence[T], size: int) -> Iterable[Sequence[T]]:
    """Yield successive chunks from iterable."""
    for i in range(0, len(iterable), size):
        yield iterable[i : i + size]


class ResolveValueError(ValueError):
    """Error when resolving parameter value."""

    pass


def resolve_value(
    value: Optional[str],
    default: Union[TN, Callable[[], TN]],
    expected_type: Type[TN] = int,
) -> TN:
    """Resolve a value with support for relative offsets using ^ prefix."""

    def get_default() -> TN:
        return default() if callable(default) else default

    if not value:
        return get_default()
    try:
        if value.startswith("^"):
            return get_default() + expected_type(value[1:])
        return expected_type(value)
    except Exception as e:
        raise ResolveValueError(value) from e


def qor(a: Optional[TA], b: Union[TB, Callable[[], TB]]) -> Union[TA, TB]:
    """Return a if not None, otherwise return b (or call b if callable)."""
    return a if (a is not None) else (b() if callable(b) else b)


@lru_cache()
def is_full_width(char: str) -> bool:
    """Check if a character is full-width."""
    return unicodedata.east_asian_width(char) in ("A", "F", "W")
