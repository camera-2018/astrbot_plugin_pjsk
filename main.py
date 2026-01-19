"""
Sekai Stickers - Project Sekai 表情包制作插件 for AstrBot
"""

import math
import os
import tempfile
from typing import Optional

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig

from .config import PluginConfig, config as plugin_config
from .render import (
    DEFAULT_LINE_SPACING,
    DEFAULT_STROKE_COLOR,
    DEFAULT_STROKE_WIDTH,
    get_all_characters_grid,
    get_character_stickers_grid,
    get_sticker,
    make_sticker_render_kwargs,
)
from .resource import (
    prepare_resource,
    select_or_get_random,
    LOADED_STICKER_INFO,
)
from .utils import ResolveValueError, resolve_value


HELP_TEXT = """
Project Sekai 表情生成

用法:
  pjsk [文字] [-i ID] [-x X] [-y Y] [-r 角度] [-s 大小] [-c 颜色]

参数:
  文字          添加的文字，为空时使用默认值
  -i, --id      表情 ID，可以通过 pjsk列表 查询
  -x            文字的中心 x 坐标
  -y            文字的中心 y 坐标
  -r, --rotate  文字旋转的角度
  -s, --size    文字的大小
  -c, --color   文字颜色，使用 16 进制格式

示例:
  pjsk 你好世界
  pjsk -i 1 测试文字
  pjsk列表
  pjsk列表 Miku
""".strip()


def parse_args(args_str: str) -> dict:
    """Parse command arguments."""
    result = {
        "text": [],
        "id": None,
        "x": None,
        "y": None,
        "rotate": None,
        "size": None,
        "color": None,
        "stroke_width": None,
        "stroke_color": None,
        "line_spacing": None,
    }
    
    parts = args_str.split()
    i = 0
    while i < len(parts):
        part = parts[i]
        if part in ("-i", "--id") and i + 1 < len(parts):
            result["id"] = parts[i + 1]
            i += 2
        elif part == "-x" and i + 1 < len(parts):
            result["x"] = parts[i + 1]
            i += 2
        elif part == "-y" and i + 1 < len(parts):
            result["y"] = parts[i + 1]
            i += 2
        elif part in ("-r", "--rotate") and i + 1 < len(parts):
            result["rotate"] = parts[i + 1]
            i += 2
        elif part in ("-s", "--size") and i + 1 < len(parts):
            result["size"] = parts[i + 1]
            i += 2
        elif part in ("-c", "--color") and i + 1 < len(parts):
            result["color"] = parts[i + 1]
            i += 2
        elif part in ("-W", "--stroke-width") and i + 1 < len(parts):
            result["stroke_width"] = parts[i + 1]
            i += 2
        elif part in ("-C", "--stroke-color") and i + 1 < len(parts):
            result["stroke_color"] = parts[i + 1]
            i += 2
        elif part in ("-S", "--line-spacing") and i + 1 < len(parts):
            result["line_spacing"] = parts[i + 1]
            i += 2
        elif not part.startswith("-"):
            result["text"].append(part)
            i += 1
        else:
            i += 1
    
    return result


@register(
    "astrbot_plugin_pjsk",
    "Agnes4m, LgCookie",
    "Project Sekai 表情包制作插件",
    "1.0.0",
    "https://github.com/Agnes4m/nonebot_plugin_pjsk"
)
class PJSKPlugin(Star):
    """Project Sekai Sticker Plugin for AstrBot."""
    
    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        self._initialized = False
        # Update global config with AstrBot config
        if config:
            plugin_config._config = config
    
    async def initialize(self):
        """Initialize plugin - download resources and install playwright browser."""
        logger.info("正在初始化 PJSK 表情插件...")
        try:
            # Install playwright browser if not exists
            await self._ensure_playwright_browser()
            # Download resources
            await prepare_resource()
            self._initialized = True
            logger.info(f"PJSK 表情插件初始化完成，加载了 {len(LOADED_STICKER_INFO)} 个表情")
        except Exception as e:
            logger.error(f"PJSK 表情插件初始化失败: {e}")
            raise
    
    async def _ensure_playwright_browser(self):
        """Install playwright chromium browser if not installed."""
        import subprocess
        import sys
        import platform
        
        try:
            # Check if chromium is already installed by trying to import and check
            from playwright.async_api import async_playwright
            async with async_playwright() as p:
                # Try to get browser executable path
                try:
                    browser = await p.chromium.launch()
                    await browser.close()
                    logger.debug("Playwright chromium 已安装")
                    return
                except Exception:
                    pass
        except Exception:
            pass
        
        # On Linux, install system dependencies first
        if platform.system() == "Linux":
            logger.info("正在安装 Playwright 系统依赖...")
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "playwright", "install-deps", "chromium"],
                    capture_output=True,
                    text=True,
                    timeout=300
                )
                if result.returncode == 0:
                    logger.info("Playwright 系统依赖安装成功")
                else:
                    logger.warning(f"Playwright 系统依赖安装可能有问题: {result.stderr}")
            except Exception as e:
                logger.warning(f"Playwright 系统依赖安装失败 (可能需要 sudo): {e}")
        
        # Install chromium
        logger.info("正在安装 Playwright chromium 浏览器...")
        try:
            result = subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                capture_output=True,
                text=True,
                timeout=300  # 5 minutes timeout
            )
            if result.returncode == 0:
                logger.info("Playwright chromium 安装成功")
            else:
                logger.warning(f"Playwright 安装可能有问题: {result.stderr}")
        except subprocess.TimeoutExpired:
            logger.error("Playwright 安装超时")
        except Exception as e:
            logger.error(f"Playwright 安装失败: {e}")
    
    @filter.command("pjsk")
    async def pjsk_generate(self, event: AstrMessageEvent):
        """生成 Project Sekai 表情包"""
        if not self._initialized:
            yield event.plain_result("插件正在初始化中，请稍后再试...")
            return
        
        # Get command arguments
        message = event.message_str
        # Remove command prefix and command name
        args_str = message
        for prefix in ["/pjsk", "pjsk"]:
            if args_str.startswith(prefix):
                args_str = args_str[len(prefix):].strip()
                break
        
        # Check for help
        if args_str in ("-h", "--help", "帮助"):
            yield event.plain_result(HELP_TEXT)
            return
        
        # Parse arguments
        args = parse_args(args_str)
        
        # Get sticker
        sticker_id: Optional[str] = args["id"]
        selected_sticker = select_or_get_random(sticker_id)
        
        if sticker_id and not selected_sticker:
            yield event.plain_result(f"没有找到 ID 为 {sticker_id} 的表情")
            return
        
        if not selected_sticker:
            yield event.plain_result("没有可用的表情，请检查资源是否下载完成")
            return
        
        default_text = selected_sticker.default_text
        text = " ".join(args["text"]) if args["text"] else default_text.text
        
        try:
            kw = make_sticker_render_kwargs(
                selected_sticker,
                text=text,
                x=resolve_value(args["x"], default_text.x),
                y=resolve_value(args["y"], default_text.y),
                rotate=resolve_value(
                    args["rotate"],
                    lambda: math.degrees(default_text.r / 10),
                    float,
                ),
                font_size=resolve_value(args["size"], default_text.s),
                font_color=args["color"] or selected_sticker.color,
                stroke_width=resolve_value(args["stroke_width"], DEFAULT_STROKE_WIDTH),
                stroke_color=args["stroke_color"] or DEFAULT_STROKE_COLOR,
                line_spacing=resolve_value(args["line_spacing"], DEFAULT_LINE_SPACING, float),
                auto_adjust=(args["size"] is None),
            )
            image_bytes = await get_sticker(**kw)
        except ResolveValueError as e:
            yield event.plain_result(f"参数值 `{e.args[0]}` 解析出错")
            return
        except Exception as e:
            logger.error(f"生成表情时出错: {e}")
            yield event.plain_result("生成表情时出错，请检查后台日志")
            return
        
        # Save to temp file and send
        temp_path = os.path.join(tempfile.gettempdir(), f"pjsk_{hash(text)}.png")
        with open(temp_path, "wb") as f:
            f.write(image_bytes)
        
        yield event.image_result(temp_path)
    
    @filter.command("pjsk列表")
    async def pjsk_list(self, event: AstrMessageEvent):
        """查看 PJSK 表情列表"""
        if not self._initialized:
            yield event.plain_result("插件正在初始化中，请稍后再试...")
            return
        
        # Get character name if provided
        message = event.message_str
        args_str = message
        for prefix in ["/pjsk列表", "pjsk列表"]:
            if args_str.startswith(prefix):
                args_str = args_str[len(prefix):].strip()
                break
        
        character = args_str.strip() if args_str else None
        
        try:
            if character:
                # Show stickers for specific character
                image_bytes = await get_character_stickers_grid(character)
                if not image_bytes:
                    yield event.plain_result(f"没有找到角色 `{character}` 的表情")
                    return
            else:
                # Show all characters
                image_bytes = await get_all_characters_grid()
        except Exception as e:
            logger.error(f"获取表情列表时出错: {e}")
            yield event.plain_result("获取表情列表时出错，请检查后台日志")
            return
        
        # Save to temp file and send
        temp_path = os.path.join(
            tempfile.gettempdir(), 
            f"pjsk_list_{character or 'all'}.jpeg"
        )
        with open(temp_path, "wb") as f:
            f.write(image_bytes)
        
        if character:
            yield event.image_result(temp_path)
        else:
            yield event.image_result(temp_path)
            yield event.plain_result("使用 /pjsk列表 <角色名> 查看该角色的所有表情 ID")
    
    async def terminate(self):
        """Clean up when plugin is unloaded."""
        logger.info("PJSK 表情插件已卸载")
