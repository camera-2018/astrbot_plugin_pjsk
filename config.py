"""Configuration for pjsk plugin."""

import os
from typing import List, Optional

# Default configuration values
DEFAULT_CONFIG = {
    "pjsk_req_retry": 1,
    "pjsk_req_timeout": 10,
    "pjsk_use_cache": True,
    "pjsk_clear_cache": False,
}

# Asset prefixes (not configurable via WebUI for simplicity)
PJSK_ASSETS_PREFIX: List[str] = [
    "https://raw.githubusercontent.com/TheOriginalAyaka/sekai-stickers/main/",
]

PJSK_REPO_PREFIX: List[str] = [
    "https://raw.githubusercontent.com/Agnes4m/nonebot_plugin_pjsk/main/",
]


def get_proxy_from_env() -> Optional[str]:
    """Get proxy from environment variables.

    Checks common proxy environment variables in order:
    - HTTPS_PROXY / https_proxy (for HTTPS requests)
    - HTTP_PROXY / http_proxy (fallback)
    - ALL_PROXY / all_proxy (catch-all)
    """
    proxy_vars = [
        "HTTPS_PROXY",
        "https_proxy",
        "HTTP_PROXY",
        "http_proxy",
        "ALL_PROXY",
        "all_proxy",
    ]
    for var in proxy_vars:
        proxy = os.environ.get(var)
        if proxy:
            return proxy
    return None


class PluginConfig:
    """Plugin configuration wrapper."""

    def __init__(self, config_dict=None):
        self._config = config_dict or DEFAULT_CONFIG
    
    def update_config(self, config_dict):
        """Update configuration with new values."""
        if config_dict:
            self._config = config_dict
    
    @property
    def pjsk_req_retry(self) -> int:
        return self._config.get("pjsk_req_retry", DEFAULT_CONFIG["pjsk_req_retry"])

    @property
    def pjsk_req_timeout(self) -> int:
        return self._config.get("pjsk_req_timeout", DEFAULT_CONFIG["pjsk_req_timeout"])

    @property
    def pjsk_use_cache(self) -> bool:
        return self._config.get("pjsk_use_cache", DEFAULT_CONFIG["pjsk_use_cache"])

    @property
    def pjsk_clear_cache(self) -> bool:
        return self._config.get("pjsk_clear_cache", DEFAULT_CONFIG["pjsk_clear_cache"])

    @property
    def pjsk_req_proxy(self) -> Optional[str]:
        """Get proxy for requests.

        Dynamically reads environment variable proxy to ensure AstrBot's
        proxy settings are picked up after core initialization.
        """
        return get_proxy_from_env()

    @property
    def pjsk_assets_prefix(self) -> List[str]:
        return PJSK_ASSETS_PREFIX

    @property
    def pjsk_repo_prefix(self) -> List[str]:
        return PJSK_REPO_PREFIX


# Global config instance (will be updated by main.py)
config = PluginConfig()

