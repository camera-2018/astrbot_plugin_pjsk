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
    close_browser,
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
from .utils import ResolveValueError, resolve_value, close_http_client


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
    "camera-2018&RC-CHN",
    "Project Sekai 表情包制作插件,参考https://github.com/Agnes4m/nonebot_plugin_pjsk编写",
    "1.0.2",
    "https://github.com/camera-2018/astrbot_plugin_pjsk",
)
class PJSKPlugin(Star):
    """Project Sekai Sticker Plugin for AstrBot."""

    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        self._initialized = False
        # Update global config with AstrBot config
        if config:
            plugin_config.update_config(config)
            
    async def initialize(self):
        """Initialize plugin - download resources and install playwright browser."""
        from astrbot.api.star import StarTools
        from .resource import init_data_folder
        logger.info("正在初始化 PJSK 表情插件...")
        try:
            # Initialize data folder with AstrBot's data directory
            data_dir = StarTools.get_data_dir("astrbot_plugin_pjsk")
            init_data_folder(data_dir)
            # Install playwright browser if not exists
            await self._ensure_playwright_browser()
            # Download resources
            await prepare_resource()
            self._initialized = True
            logger.info(
                f"PJSK 表情插件初始化完成，加载了 {len(LOADED_STICKER_INFO)} 个表情"
            )
        except Exception as e:
            logger.error(f"PJSK 表情插件初始化失败: {e}")
            raise

    async def _ensure_playwright_browser(self):
        """Install the playwright chromium runtime if it is missing."""

        try:
            import playwright  # noqa: F401
        except ImportError:
            logger.error("Playwright 未安装，请执行: pip install playwright")
            raise RuntimeError("Playwright is not installed")

        missing = self._get_missing_chromium_runtime_files()
        if not missing:
            logger.info("Playwright chromium 运行文件已安装，跳过安装步骤")
        else:
            missing_names = ", ".join(item["name"] for item in missing)
            missing_paths = "; ".join(str(item["install_dir"]) for item in missing)
            if not plugin_config.pjsk_playwright_auto_install:
                raise RuntimeError(
                    "Playwright chromium 运行文件缺失且已关闭自动安装。"
                    "请执行 `python -m playwright install chromium` 后重启插件。"
                )

            logger.info(
                f"检测到 Playwright {missing_names} 缺失，正在按需安装: "
                f"{missing_paths}"
            )
            await self._run_playwright_install(
                install_only_shell=self._should_install_only_chromium_shell()
            )

            missing = self._get_missing_chromium_runtime_files()
            if missing:
                missing_paths = "; ".join(
                    str(item["install_dir"]) for item in missing
                )
                raise RuntimeError(
                    f"Playwright chromium 安装后仍缺少运行文件: {missing_paths}"
                )

            logger.info("Playwright chromium 运行文件安装成功")

        await self._ensure_playwright_system_dependencies()

    async def _ensure_playwright_system_dependencies(self) -> None:
        """Install Linux browser dependencies only when Chromium cannot start."""
        import platform

        if platform.system() != "Linux":
            return

        available, error = await self._can_launch_playwright_chromium()
        if available:
            logger.info("Playwright 系统依赖检测通过，跳过安装步骤")
            return

        logger.warning(
            f"Playwright Chromium 启动检测失败，将安装系统依赖: {error}"
        )
        await self._run_playwright_install_deps()

        available, error = await self._can_launch_playwright_chromium()
        if not available:
            raise RuntimeError(
                f"Playwright 系统依赖安装后 Chromium 仍无法启动: {error}"
            )
        logger.info("Playwright 系统依赖安装并检测成功")

    @staticmethod
    async def _can_launch_playwright_chromium():
        """Use an actual headless launch as the system dependency check."""
        from playwright.async_api import async_playwright

        playwright = None
        browser = None
        try:
            playwright = await async_playwright().start()
            browser = await playwright.chromium.launch(headless=True)
            return True, ""
        except Exception as exc:
            return False, str(exc)
        finally:
            if browser is not None:
                try:
                    await browser.close()
                except Exception:
                    pass
            if playwright is not None:
                try:
                    await playwright.stop()
                except Exception:
                    pass

    @staticmethod
    def _get_browsers_path():
        """Get the playwright browsers directory path.

        Mirrors playwright's own ``registryDirectory`` logic so that the
        path we check is consistent with the one playwright actually uses.
        """
        import os
        import platform
        from pathlib import Path

        browsers_path_env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
        if browsers_path_env == "0":
            # "0" means use playwright package's local .local-browsers directory
            try:
                import playwright as pw

                return (
                    Path(pw.__file__).parent
                    / "driver"
                    / "package"
                    / ".local-browsers"
                )
            except (ImportError, AttributeError):
                return None
        elif browsers_path_env:
            path = Path(browsers_path_env)
            if not path.is_absolute():
                path = Path(os.environ.get("INIT_CWD") or os.getcwd()) / path
            return path

        system = platform.system()
        if system == "Darwin":
            return Path.home() / "Library" / "Caches" / "ms-playwright"
        elif system == "Windows":
            local_app_data = os.environ.get("LOCALAPPDATA", "")
            if local_app_data:
                return Path(local_app_data) / "ms-playwright"
            return Path.home() / "AppData" / "Local" / "ms-playwright"
        else:  # Linux and others
            cache_home = os.environ.get("XDG_CACHE_HOME", "")
            if cache_home:
                return Path(cache_home) / "ms-playwright"
            return Path.home() / ".cache" / "ms-playwright"

    @staticmethod
    def _is_chromium_installed() -> bool:
        """Check whether the chromium runtime needed by this plugin exists."""

        return not PJSKPlugin._get_missing_chromium_runtime_files()

    @staticmethod
    def _get_missing_chromium_runtime_files():
        """Return missing Playwright chromium runtime artifacts.

        The renderer launches Chromium in headless mode.  Newer Playwright
        versions use ``chromium-headless-shell`` for that path, so checking only
        ``chromium-*`` can incorrectly pass while the actual launch executable
        is absent.
        """

        missing = []
        for requirement in PJSKPlugin._get_chromium_runtime_requirements():
            executable = next(
                (
                    path
                    for path in requirement["candidates"]
                    if PJSKPlugin._is_executable_file(path)
                ),
                None,
            )
            if executable is None:
                missing.append(requirement)
        return missing

    @staticmethod
    def _get_chromium_runtime_requirements():
        import json
        from pathlib import Path

        browsers_path = PJSKPlugin._get_browsers_path()
        if browsers_path is None:
            return [
                {
                    "name": "chromium",
                    "install_dir": Path("<unknown>"),
                    "candidates": [],
                }
            ]

        try:
            import playwright as pw

            browsers_json = (
                Path(pw.__file__).parent
                / "driver"
                / "package"
                / "browsers.json"
            )
            with open(browsers_json, encoding="utf-8") as f:
                data = json.load(f)
        except (ImportError, json.JSONDecodeError, OSError) as exc:
            logger.debug(f"Playwright browsers.json 读取失败: {exc}")
            return [
                {
                    "name": "chromium",
                    "install_dir": browsers_path / "chromium",
                    "candidates": [],
                }
            ]

        descriptors = {
            browser["name"]: browser
            for browser in data.get("browsers", [])
            if browser.get("name") in {"chromium", "chromium-headless-shell"}
        }
        if not descriptors:
            return [
                {
                    "name": "chromium",
                    "install_dir": browsers_path / "chromium",
                    "candidates": [],
                }
            ]

        runtime_names = (
            ["chromium-headless-shell"]
            if "chromium-headless-shell" in descriptors
            else ["chromium"]
        )

        requirements = []
        for name in runtime_names:
            descriptor = descriptors.get(name)
            if not descriptor:
                continue
            install_dir = browsers_path / (
                f"{name.replace('-', '_')}-{descriptor['revision']}"
            )
            requirements.append(
                {
                    "name": name,
                    "install_dir": install_dir,
                    "candidates": PJSKPlugin._get_browser_executable_candidates(
                        name,
                        install_dir,
                    ),
                }
            )
        return requirements

    @staticmethod
    def _get_browser_executable_candidates(name: str, install_dir):
        import platform

        system = platform.system()
        machine = platform.machine().lower()
        is_arm = machine in {"arm64", "aarch64"}

        def paths(*parts_list):
            return [install_dir.joinpath(*parts) for parts in parts_list]

        if name == "chromium-headless-shell":
            if system == "Linux":
                first = ("chrome-linux", "headless_shell") if is_arm else (
                    "chrome-headless-shell-linux64",
                    "chrome-headless-shell",
                )
                return paths(
                    first,
                    ("chrome-headless-shell-linux64", "chrome-headless-shell"),
                    ("chrome-linux", "headless_shell"),
                )
            if system == "Darwin":
                first = (
                    "chrome-headless-shell-mac-arm64",
                    "chrome-headless-shell",
                ) if is_arm else (
                    "chrome-headless-shell-mac-x64",
                    "chrome-headless-shell",
                )
                return paths(
                    first,
                    ("chrome-headless-shell-mac-arm64", "chrome-headless-shell"),
                    ("chrome-headless-shell-mac-x64", "chrome-headless-shell"),
                    ("chrome-mac", "headless_shell"),
                )
            if system == "Windows":
                return paths(
                    ("chrome-headless-shell-win64", "chrome-headless-shell.exe"),
                    ("chrome-win64", "headless_shell.exe"),
                    ("chrome-win", "headless_shell.exe"),
                )
            return []

        if system == "Linux":
            first = ("chrome-linux", "chrome") if is_arm else (
                "chrome-linux64",
                "chrome",
            )
            return paths(
                first,
                ("chrome-linux64", "chrome"),
                ("chrome-linux", "chrome"),
            )
        if system == "Darwin":
            first = (
                "chrome-mac-arm64",
                "Google Chrome for Testing.app",
                "Contents",
                "MacOS",
                "Google Chrome for Testing",
            ) if is_arm else (
                "chrome-mac-x64",
                "Google Chrome for Testing.app",
                "Contents",
                "MacOS",
                "Google Chrome for Testing",
            )
            return paths(
                first,
                (
                    "chrome-mac-arm64",
                    "Google Chrome for Testing.app",
                    "Contents",
                    "MacOS",
                    "Google Chrome for Testing",
                ),
                (
                    "chrome-mac-x64",
                    "Google Chrome for Testing.app",
                    "Contents",
                    "MacOS",
                    "Google Chrome for Testing",
                ),
                ("chrome-mac", "Chromium.app", "Contents", "MacOS", "Chromium"),
            )
        if system == "Windows":
            return paths(
                ("chrome-win64", "chrome.exe"),
                ("chrome-win", "chrome.exe"),
            )
        return []

    @staticmethod
    def _is_executable_file(path) -> bool:
        import os
        import platform

        if not path.is_file():
            return False
        if platform.system() == "Windows":
            return True
        return os.access(path, os.X_OK)

    @staticmethod
    def _should_install_only_chromium_shell() -> bool:
        requirements = PJSKPlugin._get_chromium_runtime_requirements()
        return bool(requirements) and all(
            item["name"] == "chromium-headless-shell" for item in requirements
        )

    async def _run_playwright_install(self, install_only_shell: bool) -> None:
        import shlex
        import sys

        args = [sys.executable, "-m", "playwright", "install"]
        if install_only_shell:
            args.append("--only-shell")
        args.append("chromium")

        logger.info(f"执行 Playwright 安装命令: {shlex.join(args)}")
        returncode, output = await self._run_playwright_command(args)
        if returncode == 0:
            return

        if install_only_shell and self._is_unknown_playwright_option(output):
            fallback_args = [arg for arg in args if arg != "--only-shell"]
            logger.warning(
                "当前 Playwright 不支持 --only-shell，改为安装完整 chromium"
            )
            logger.info(f"执行 Playwright 安装命令: {shlex.join(fallback_args)}")
            returncode, output = await self._run_playwright_command(fallback_args)
            if returncode == 0:
                return

        raise RuntimeError(f"Playwright chromium 安装失败: {output}")

    async def _run_playwright_install_deps(self) -> None:
        import shlex
        import sys

        args = [
            sys.executable,
            "-m",
            "playwright",
            "install-deps",
            "chromium",
        ]
        logger.info(f"执行 Playwright 系统依赖安装命令: {shlex.join(args)}")
        returncode, output = await self._run_playwright_command(args)
        if returncode != 0:
            raise RuntimeError(f"Playwright 系统依赖安装失败: {output}")

    async def _run_playwright_command(self, args):
        import asyncio
        import contextlib

        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=plugin_config.pjsk_playwright_install_timeout,
            )
        except asyncio.TimeoutError as exc:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            with contextlib.suppress(Exception):
                await proc.wait()
            raise RuntimeError("Playwright 安装超时") from exc
        return proc.returncode, self._short_process_output(stdout, stderr)

    @staticmethod
    def _short_process_output(stdout: bytes, stderr: bytes) -> str:
        parts = [
            output.decode(errors="replace").strip()
            for output in (stdout, stderr)
            if output
        ]
        output = "\n".join(part for part in parts if part)
        if len(output) > 2000:
            output = output[-2000:]
        return output or "无输出"

    @staticmethod
    def _is_unknown_playwright_option(output: str) -> bool:
        lowered = output.lower()
        return "unknown option" in lowered or "unknown argument" in lowered

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
                args_str = args_str[len(prefix) :].strip()
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
                line_spacing=resolve_value(
                    args["line_spacing"], DEFAULT_LINE_SPACING, float
                ),
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

        # Save to temp file and send, then clean up
        temp_path = os.path.join(
            tempfile.gettempdir(), f"pjsk_{hash(text)}_{id(event)}.png"
        )
        try:
            with open(temp_path, "wb") as f:
                f.write(image_bytes)
            yield event.image_result(temp_path)
        finally:
            # Clean up temporary file after sending
            try:
                os.remove(temp_path)
            except OSError:
                pass

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
                args_str = args_str[len(prefix) :].strip()
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

        # Save to temp file and send, then clean up
        temp_path = os.path.join(
            tempfile.gettempdir(), f"pjsk_list_{character or 'all'}_{id(event)}.jpeg"
        )
        try:
            with open(temp_path, "wb") as f:
                f.write(image_bytes)

            if character:
                yield event.image_result(temp_path)
            else:
                yield event.image_result(temp_path)
                yield event.plain_result(
                    "使用 /pjsk列表 <角色名> 查看该角色的所有表情 ID"
                )
        finally:
            # Clean up temporary file after sending
            try:
                os.remove(temp_path)
            except OSError:
                pass

    async def terminate(self):
        """Clean up when plugin is unloaded."""
        # Close browser instance to release resources
        await close_browser()
        # Close HTTP client to release connections
        await close_http_client()
        logger.info("PJSK 表情插件已卸载")
