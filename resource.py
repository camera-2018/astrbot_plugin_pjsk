"""Resource management for pjsk plugin."""

import asyncio
import json
import random
from contextlib import suppress
from pathlib import Path
from typing import Any, Coroutine, List, Optional, overload

import anyio
import jinja2
from pydantic import BaseModel, Field

from .config import config
from .utils import ResponseType, append_prefix, async_request, with_semaphore

# Plugin directory
PLUGIN_DIR = Path(__file__).parent

# Data folder - will be initialized by init_data_folder()
DATA_FOLDER: Optional[Path] = None
FONT_FOLDER: Optional[Path] = None
RESOURCE_FOLDER: Optional[Path] = None
STICKER_INFO_CACHE: Optional[Path] = None
CACHE_FOLDER: Optional[Path] = None
FONT_PATH: Optional[Path] = None

# Try to use bundled font first
BUNDLED_FONT_PATH = PLUGIN_DIR / "fonts" / "YurukaFangTang.ttf"

# Templates folder - bundled with plugin
TEMPLATES_FOLDER = PLUGIN_DIR / "templates"
JINJA_ENV = jinja2.Environment(
    loader=jinja2.FileSystemLoader(TEMPLATES_FOLDER),
    autoescape=jinja2.select_autoescape(["html", "xml"]),
    enable_async=True,
)


def init_data_folder(data_dir: Path = None):
    """Initialize data folder paths. Called from main.py with StarTools.get_data_dir()."""
    global \
        DATA_FOLDER, \
        FONT_FOLDER, \
        RESOURCE_FOLDER, \
        STICKER_INFO_CACHE, \
        CACHE_FOLDER, \
        FONT_PATH

    if data_dir:
        DATA_FOLDER = data_dir
    else:
        # Fallback for testing
        DATA_FOLDER = Path.cwd() / "data" / "pjsk"
        
    FONT_FOLDER = DATA_FOLDER / "fonts"
    RESOURCE_FOLDER = DATA_FOLDER / "resource"
    STICKER_INFO_CACHE = DATA_FOLDER / "characters.json"
    CACHE_FOLDER = DATA_FOLDER / "cache"

    # Use bundled font if exists, otherwise use data folder
    FONT_PATH = (
        BUNDLED_FONT_PATH
        if BUNDLED_FONT_PATH.exists()
        else FONT_FOLDER / "YurukaFangTang.ttf"
    )


def make_cache_key(obj: Any) -> str:
    """Generate cache key from object."""
    with suppress(Exception):
        return str(hash(obj))
    return str(hash(json.dumps(obj)))


async def ensure_directories():
    """Ensure all required directories exist."""
    for folder in (DATA_FOLDER, FONT_FOLDER, RESOURCE_FOLDER, CACHE_FOLDER):
        if not folder.exists():
            folder.mkdir(parents=True)

    # Clear cache if configured
    if config.pjsk_clear_cache and CACHE_FOLDER.exists():
        for f in CACHE_FOLDER.iterdir():
            f.unlink()


async def get_cache(filename: str) -> Optional[bytes]:
    """Get cached file content."""
    path = anyio.Path(CACHE_FOLDER / filename)
    if await path.exists():
        try:
            return await path.read_bytes()
        except Exception:
            pass
    return None


async def write_cache(filename: str, data: bytes):
    """Write data to cache."""
    path = anyio.Path(CACHE_FOLDER / filename)
    try:
        await path.write_bytes(data)
    except Exception:
        pass


class StickerText(BaseModel):
    """Default text configuration for a sticker."""

    text: str
    x: int
    y: int
    r: int  # rotate (in tenths of degrees)
    s: int  # font size


class StickerInfo(BaseModel):
    """Information about a sticker."""

    sticker_id: str = Field(..., alias="id")
    name: str
    character: str
    img: str
    color: str
    default_text: StickerText = Field(..., alias="defaultText")


LOADED_STICKER_INFO: List[StickerInfo] = []


def sort_stickers():
    """Sort stickers by character name and assign IDs."""
    LOADED_STICKER_INFO.sort(key=lambda x: x.character.lower())
    for i, x in enumerate(LOADED_STICKER_INFO, 1):
        x.sticker_id = str(i)


@overload
def select_or_get_random(sticker_id: None = None) -> StickerInfo: ...


@overload
def select_or_get_random(sticker_id: str) -> Optional[StickerInfo]: ...


def select_or_get_random(sticker_id: Optional[str] = None) -> Optional[StickerInfo]:
    """Select sticker by ID or get a random one."""
    return (
        next((x for x in LOADED_STICKER_INFO if sticker_id == x.sticker_id), None)
        if sticker_id
        else random.choice(LOADED_STICKER_INFO)
        if LOADED_STICKER_INFO
        else None
    )


async def check_and_download_font():
    """Download font if not present."""
    # If bundled font exists, no need to download
    if BUNDLED_FONT_PATH.exists():
        return

    if not FONT_PATH.exists():
        font_name = FONT_PATH.name
        path = anyio.Path(FONT_FOLDER) / font_name
        urls = append_prefix(f"fonts/{font_name}", config.pjsk_repo_prefix)
        await path.write_bytes(await async_request(*urls))


async def load_sticker_info():
    """Load sticker information from remote or cache."""
    await ensure_directories()

    path = anyio.Path(STICKER_INFO_CACHE)
    urls = append_prefix("src/characters.json", config.pjsk_assets_prefix)
    try:
        loaded_text = await async_request(*urls, response_type=ResponseType.TEXT)
        await path.write_text(loaded_text, encoding="u8")
    except Exception:
        if not (await path.exists()):
            raise
        loaded_text = await path.read_text(encoding="u8")

    LOADED_STICKER_INFO.clear()
    data = json.loads(loaded_text)
    for item in data:
        LOADED_STICKER_INFO.append(StickerInfo.model_validate(item))
    sort_stickers()


async def check_and_download_stickers():
    """Download missing sticker images."""
    semaphore = asyncio.Semaphore(10)

    @with_semaphore(semaphore)
    async def download(path_str: str):
        path = anyio.Path(RESOURCE_FOLDER) / path_str
        if not (await (dir_name := path.parent).exists()):
            await dir_name.mkdir(parents=True, exist_ok=True)

        urls = append_prefix(f"public/img/{path_str}", config.pjsk_assets_prefix)
        await path.write_bytes(await async_request(*urls))

    tasks: List[Coroutine] = [
        download(sticker_info.img)
        for sticker_info in LOADED_STICKER_INFO
        if not (RESOURCE_FOLDER / sticker_info.img).exists()
    ]
    if tasks:
        await asyncio.gather(*tasks)


async def check_and_download_resource():
    """Download all required resources."""
    await load_sticker_info()
    await check_and_download_stickers()


async def prepare_resource():
    """Prepare all resources for the plugin."""
    await ensure_directories()
    await asyncio.gather(
        check_and_download_resource(),
        check_and_download_font(),
    )
