# Sekai Stickers

Project Sekai 表情包制作插件 for AstrBot

基于 [nonebot-plugin-pjsk](https://github.com/Agnes4m/nonebot_plugin_pjsk) 移植

## 功能

- 生成 Project Sekai 风格的表情包
- 支持自定义文字、位置、角度、大小、颜色等参数
- 查看所有角色和表情 ID
- 自动检查并按需安装 Playwright 浏览器

![wonderhoy](https://raw.githubusercontent.com/lgc-NB2Dev/readme/main/pjsk/wonderhoy.png)

## 安装

1. 将插件目录复制到 AstrBot 的 `data/plugins/` 目录
2. 重启 AstrBot

> 插件会在首次启动时自动安装 Playwright chromium 运行文件和所需资源。Linux 系统依赖默认不自动安装，如浏览器启动提示缺少依赖，可在配置中启用 `pjsk_playwright_install_deps` 或手动执行 `python -m playwright install-deps chromium`。

## 使用方法

### 生成表情

```
pjsk [文字]              - 使用随机表情生成
pjsk -i <ID> [文字]      - 使用指定 ID 的表情
pjsk -h                  - 查看详细帮助
```

**参数说明：**
- `-i, --id` - 表情 ID
- `-x` - 文字 x 坐标
- `-y` - 文字 y 坐标
- `-r, --rotate` - 旋转角度
- `-s, --size` - 文字大小
- `-c, --color` - 文字颜色 (16进制)

### 查看表情列表

```
pjsk列表                 - 查看所有角色
pjsk列表 <角色名>        - 查看指定角色的表情 ID
```

## 示例

```
pjsk 你好世界
pjsk -i 1 测试文字
pjsk -i 5 -s 30 小字体
pjsk列表
pjsk列表 Miku
```

## 配置项

在 AstrBot WebUI 中可配置：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `pjsk_req_retry` | 请求重试次数 | 1 |
| `pjsk_req_timeout` | 请求超时时间(秒) | 10 |
| `pjsk_use_cache` | 使用缓存 | true |
| `pjsk_clear_cache` | 启动时清理缓存 | false |
| `pjsk_playwright_auto_install` | 缺少 Chromium 运行文件时自动安装 | true |
| `pjsk_playwright_install_deps` | Linux 安装浏览器时附带系统依赖安装 | false |
| `pjsk_playwright_install_timeout` | Playwright 自动安装超时(秒) | 300 |

## 致谢

- 原项目: [nonebot-plugin-pjsk](https://github.com/Agnes4m/nonebot_plugin_pjsk)
- 表情资源: [sekai-stickers](https://github.com/TheOriginalAyaka/sekai-stickers)

## License

MIT License
