"""Telegram bot 推送 — PR5 of docs/specs/position_v2_harness.md §6.4。

凭证走环境变量（避免 yaml 落 token）：
- TELEGRAM_BOT_TOKEN: bot token from @BotFather
- TELEGRAM_CHAT_ID:   chat id (个人聊天用户 id; group 用 -100... 前缀)

未配 env → TelegramSender.send 返 (False, "TELEGRAM_BOT_TOKEN/CHAT_ID not set")
而非抛错；intraday 主脚本走 DB 落 delivered=False + error 文案即可。

零外部依赖：用 urllib.request；不引 telebot SDK 减少 venv 体积。
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
_DEFAULT_TIMEOUT_SEC = 10


class TelegramSender:
    """简单 Telegram 推送客户端，凭证从环境变量读取。"""

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        timeout_sec: int = _DEFAULT_TIMEOUT_SEC,
    ):
        self.bot_token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")
        self.timeout_sec = timeout_sec

    @property
    def configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def send(self, text: str) -> tuple[bool, Optional[str]]:
        """发送一条消息。返 (delivered, error_or_None)。

        - 未配 env → (False, "TELEGRAM_BOT_TOKEN/CHAT_ID not set")
        - 网络 / API 错误 → (False, "<error 文案>")
        - 成功 → (True, None)
        """
        if not self.configured:
            return False, "TELEGRAM_BOT_TOKEN/CHAT_ID not set"
        url = _TELEGRAM_API.format(token=self.bot_token)
        body = urllib.parse.urlencode({
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",  # Telegram 默认转义；消息里用 <code> / <b> 即可
            "disable_web_page_preview": "true",
        }).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                raw = resp.read().decode("utf-8")
                payload = json.loads(raw)
                if payload.get("ok"):
                    return True, None
                return False, f"telegram api error: {payload!r}"
        except urllib.error.HTTPError as e:
            return False, f"http error {e.code}: {e.read().decode('utf-8', errors='replace')[:200]}"
        except urllib.error.URLError as e:
            return False, f"url error: {e.reason!r}"
        except Exception as e:  # pragma: no cover (其它意外)
            return False, f"unexpected error: {e!r}"
