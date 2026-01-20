"""Render stickers using playwright."""

import asyncio
import math
from pathlib import Path
from typing import Awaitable, Callable, Dict, List, Literal, Optional, TypedDict, Union

import anyio
from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    Playwright,
    Request,
    Route,
)
from yarl import URL

from .config import config
from . import resource as res
from .resource import (
    JINJA_ENV,
    LOADED_STICKER_INFO,
    StickerInfo,
    get_cache,
    make_cache_key,
    write_cache,
)
from .utils import is_full_width, qor

DEFAULT_WIDTH = 296
DEFAULT_HEIGHT = 256
DEFAULT_STROKE_WIDTH = 9
DEFAULT_LINE_SPACING = 1.3
DEFAULT_STROKE_COLOR = "#ffffff"

ROUTER_BASE_URL = "https://pjsk.local/"
PLUGIN_ROUTER_PREFIX = "plugin/"


# Global browser instance for reuse
_playwright: Optional[Playwright] = None
_browser: Optional[Browser] = None
_browser_context: Optional[BrowserContext] = None
_browser_lock = asyncio.Lock()


async def get_browser_context() -> BrowserContext:
    """Get or create a reusable browser context.

    This avoids the overhead of launching a new browser for each render,
    significantly improving performance.
    """
    global _playwright, _browser, _browser_context

    async with _browser_lock:
        if _browser_context is not None and _browser is not None:
            # Check if browser is still connected
            if _browser.is_connected():
                return _browser_context
            # Browser disconnected, clean up
            _browser_context = None
            _browser = None

        if _playwright is None:
            _playwright = await async_playwright().start()

        if _browser is None:
            _browser = await _playwright.chromium.launch()

        # Create a new context with device_scale_factor
        _browser_context = await _browser.new_context(device_scale_factor=1)
        return _browser_context


async def close_browser() -> None:
    """Close the global browser instance."""
    global _playwright, _browser, _browser_context

    async with _browser_lock:
        if _browser_context is not None:
            try:
                await _browser_context.close()
            except Exception:
                pass
            _browser_context = None

        if _browser is not None:
            try:
                await _browser.close()
            except Exception:
                pass
            _browser = None

        if _playwright is not None:
            try:
                await _playwright.stop()
            except Exception:
                pass
            _playwright = None


def calc_approximate_text_width(text: str, size: int, rotate_deg: float) -> float:
    """Calculate approximate text width considering rotation."""
    rotate_rad = math.radians(rotate_deg)
    width = sum((size if is_full_width(x) else size / 2) for x in text)
    return abs(width * math.cos(rotate_rad)) + abs(size * math.sin(rotate_rad))


def auto_adjust_font_size(
    text: str,
    size: int,
    rotate_deg: float,
    width: int = DEFAULT_WIDTH,
    min_size: int = 8,
    multiplier: float = 1.2,
) -> int:
    """Auto-adjust font size to fit within width."""
    while size > min_size:
        if (calc_approximate_text_width(text, size, rotate_deg) * multiplier) <= width:
            break
        size -= 1
    return size


async def root_router(route: Route):
    """Handle root route."""
    return await route.fulfill(body="<html></html>")


async def file_router(route: Route, request: Request):
    """Handle file routes by serving local files from data or plugin dir."""
    url = URL(request.url)
    url_path = url.path[1:]  # Remove leading /

    # Check if this is a plugin directory file (bundled fonts, etc.)
    if url_path.startswith(PLUGIN_ROUTER_PREFIX):
        relative = url_path[len(PLUGIN_ROUTER_PREFIX) :]
        path = anyio.Path(res.PLUGIN_DIR / relative)
    else:
        path = anyio.Path(res.DATA_FOLDER / url_path)

    try:
        data = await path.read_bytes()
    except Exception:
        return await route.abort()
    return await route.fulfill(body=data)


def to_router_url(path: Union[str, Path]) -> str:
    """Convert local path to router URL."""
    if not isinstance(path, Path):
        path = Path(path)

    # Check if path is under plugin directory (for bundled resources)
    try:
        relative = path.relative_to(res.PLUGIN_DIR)
        return f"{ROUTER_BASE_URL}{PLUGIN_ROUTER_PREFIX}{relative}".replace("\\", "/")
    except ValueError:
        pass

    # Otherwise it's under data folder
    try:
        relative = path.relative_to(res.DATA_FOLDER)
        return f"{ROUTER_BASE_URL}{relative}".replace("\\", "/")
    except ValueError:
        # Fallback: use absolute path as URL (may not work in all cases)
        return f"{ROUTER_BASE_URL}{path.name}"


class StickerRenderKwargs(TypedDict):
    """Arguments for sticker rendering."""

    image: str
    x: int
    y: int
    text: str
    font_color: str
    font_size: int
    rotate: float
    stroke_color: str
    stroke_width: int
    line_spacing: float
    font: str
    width: int
    height: int


def make_sticker_render_kwargs(
    info: StickerInfo,
    text: Optional[str] = None,
    x: Optional[int] = None,
    y: Optional[int] = None,
    rotate: Optional[float] = None,
    font_size: Optional[int] = None,
    font_color: Optional[str] = None,
    stroke_width: Optional[int] = None,
    stroke_color: Optional[str] = None,
    line_spacing: Optional[float] = None,
    auto_adjust: bool = False,
) -> StickerRenderKwargs:
    """Build render kwargs from sticker info and options."""
    default_text = info.default_text
    text = qor(text, default_text.text)
    rotate = qor(rotate, lambda: math.degrees(default_text.r / 10))
    font_size = (
        auto_adjust_font_size(text, default_text.s, rotate)
        if auto_adjust
        else qor(font_size, default_text.s)
    )
    return {
        "image": to_router_url(res.RESOURCE_FOLDER / info.img),
        "x": qor(x, default_text.x),
        "y": qor(y, default_text.y),
        "text": text,
        "font_color": qor(font_color, info.color),
        "font_size": font_size,
        "rotate": rotate,
        "stroke_color": qor(stroke_color, DEFAULT_STROKE_COLOR),
        "stroke_width": qor(stroke_width, DEFAULT_STROKE_WIDTH),
        "line_spacing": qor(line_spacing, DEFAULT_LINE_SPACING),
        "font": to_router_url(res.FONT_PATH),
        "width": DEFAULT_WIDTH,
        "height": DEFAULT_HEIGHT,
    }


async def render_sticker_html(**kwargs) -> str:
    """Render sticker SVG HTML."""
    template = JINJA_ENV.get_template("sticker.svg.jinja")
    return await template.render_async(id=hash(kwargs["image"]), **kwargs)


async def render_sticker_grid_html(items: List[str]) -> str:
    """Render sticker grid HTML."""
    template = JINJA_ENV.get_template("sticker_grid.html.jinja")
    return await template.render_async(items=items)


async def render_help_html(text: str) -> str:
    """Render help HTML."""
    template = JINJA_ENV.get_template("help.html.jinja")
    return await template.render_async(text=text)


async def capture_with_playwright(
    html: str,
    selector: str,
    image_type: Literal["png", "jpeg"] = "jpeg",
    omit_background: bool = False,
    cache_key: Optional[str] = None,
) -> bytes:
    """Capture element screenshot using playwright.

    Uses a reusable browser context for better performance.
    Only creates a new page for each render, avoiding browser launch overhead.
    """
    context = await get_browser_context()
    page = await context.new_page()

    try:
        # Set up routing for local files
        await page.route(f"{ROUTER_BASE_URL}**/*", file_router)
        await page.route(ROUTER_BASE_URL, root_router)

        await page.goto(ROUTER_BASE_URL)
        await page.set_content(html)

        element = await page.wait_for_selector(selector)
        assert element
        img = await element.screenshot(type=image_type, omit_background=omit_background)
    finally:
        # Always close the page to free resources
        await page.close()

    if config.pjsk_use_cache and cache_key:
        await write_cache(f"{cache_key}.{image_type}", img)
    return img


async def capture_sticker(html: str, cache_key: Optional[str] = None) -> bytes:
    """Capture sticker as PNG."""
    return await capture_with_playwright(
        html,
        "svg",
        image_type="png",
        omit_background=True,
        cache_key=cache_key,
    )


async def capture_template(html: str, cache_key: Optional[str] = None) -> bytes:
    """Capture template as JPEG."""
    return await capture_with_playwright(html, ".main-wrapper", cache_key=cache_key)


def use_cache(cache_key_func: Union[str, Callable], ext: Literal["png", "jpeg"]):
    """Decorator to add caching to render functions."""

    def decorator(func: Callable[..., Awaitable[bytes]]):
        async def wrapper(*args, **kwargs):
            key = (
                cache_key_func(*args, **kwargs)
                if callable(cache_key_func)
                else cache_key_func
            )
            if config.pjsk_use_cache:
                cached = await get_cache(f"{key}.{ext}")
                if cached:
                    return cached
            return await func(key, *args, **kwargs)

        return wrapper

    return decorator


def get_sticker_cache_key_maker(**params) -> str:
    """Generate cache key for sticker."""
    return make_cache_key(params)


@use_cache(get_sticker_cache_key_maker, "png")
async def get_sticker(key: str, **params) -> bytes:
    """Get rendered sticker image."""
    return await capture_sticker(await render_sticker_html(**params), cache_key=key)


@use_cache(lambda text: "help", "jpeg")
async def get_help(key: str, text: str) -> bytes:
    """Get rendered help image."""
    return await capture_template(await render_help_html(text), cache_key=key)


@use_cache(lambda: "all_characters", "jpeg")
async def get_all_characters_grid(key: str) -> bytes:
    """Get all characters grid image."""
    character_dict: Dict[str, StickerInfo] = {}
    for info in LOADED_STICKER_INFO:
        character = info.character
        if character not in character_dict:
            character = (
                character
                if character[0].isupper()
                else character[0].upper() + character[1:]
            )
            character_dict[character] = info

    sticker_templates = await asyncio.gather(
        *(
            render_sticker_html(**make_sticker_render_kwargs(info, char))
            for char, info in character_dict.items()
        ),
    )
    return await capture_template(
        await render_sticker_grid_html(sticker_templates),
        cache_key=key,
    )


def get_character_stickers_grid_cache_key_maker(character: str) -> str:
    """Generate cache key for character stickers grid."""
    return character


@use_cache(get_character_stickers_grid_cache_key_maker, "jpeg")
async def get_character_stickers_grid(key: str, character: str) -> bytes:
    """Get character stickers grid image."""
    character = character.lower()
    sticker_templates = await asyncio.gather(
        *(
            render_sticker_html(**make_sticker_render_kwargs(info, info.sticker_id))
            for info in LOADED_STICKER_INFO
            if info.character.lower() == character
        ),
    )
    return await capture_template(
        await render_sticker_grid_html(sticker_templates),
        cache_key=key,
    )
