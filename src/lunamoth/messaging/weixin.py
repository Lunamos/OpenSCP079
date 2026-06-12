from __future__ import annotations

import base64
import json
import logging
import os
import queue
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

from .base import Adapter, DeliveryDeferred, InboundMessage

_log = logging.getLogger("lunamoth.messaging.weixin")

DEFAULT_BASE_URL = "https://ilinkai.weixin.qq.com"
DEFAULT_BOT_TYPE = "3"
DEFAULT_LONG_POLL_TIMEOUT_MS = 35_000
DEFAULT_API_TIMEOUT_MS = 15_000
QRCODE_VALID_SECONDS = 5 * 60
QRCODE_REFRESHES = 3
SESSION_TIMEOUT_ERRCODE = -14
WEIXIN_TEXT_MAX = 4000
CHANNEL_VERSION = "lunamoth"


def _str_field(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    return value.strip() if isinstance(value, str) else ""


def _int_config(value: Any, default: int, minimum: int = 1) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(parsed, minimum)


def _ok(payload: dict[str, Any]) -> bool:
    try:
        ret = int(payload.get("ret") or 0)
        errcode = int(payload.get("errcode") or 0)
    except (TypeError, ValueError):
        return False
    return ret == 0 and errcode == 0


def _errcode(payload: dict[str, Any]) -> int:
    try:
        return int(payload.get("errcode") or 0)
    except (TypeError, ValueError):
        return 0


def _format_api_error(payload: dict[str, Any]) -> str:
    ret = payload.get("ret", 0)
    errcode = payload.get("errcode", 0)
    errmsg = payload.get("errmsg", "")
    return f"ret={ret}, errcode={errcode}, errmsg={errmsg}"


def _normalize_base_url(value: Any) -> str:
    text = str(value or DEFAULT_BASE_URL).strip().rstrip("/")
    return text or DEFAULT_BASE_URL


def default_state_path() -> Path:
    root = os.getenv("LUNAMOTH_CONFIG_DIR")
    if root:
        return Path(root).expanduser().resolve() / "weixin_state.json"
    session = os.getenv("LUNAMOTH_SESSION", "")
    if session:
        return Path.home().expanduser() / ".lunamoth" / "sessions" / session / "weixin_state.json"
    return Path("weixin_state.json").resolve()


def qr_fallback_url(qrcode_value: str) -> str:
    qs = urllib.parse.urlencode({"size": "320x320", "data": qrcode_value})
    return f"https://api.qrserver.com/v1/create-qr-code/?{qs}"


def item_list_to_text(item_list: Any) -> str:
    """Extract text from iLink item_list.

    Text is type 1. Voice is type 3 and can include WeChat-cloud transcription
    in voice_item.text; media/CDN decryption is intentionally out of scope here.
    """

    if not isinstance(item_list, list):
        return ""
    parts: list[str] = []
    for item in item_list:
        if not isinstance(item, dict):
            continue
        try:
            item_type = int(item.get("type") or 0)
        except (TypeError, ValueError):
            item_type = 0
        if item_type == 1:
            text_item = item.get("text_item")
            if isinstance(text_item, dict):
                text = str(text_item.get("text") or "").strip()
                if text:
                    parts.append(text)
            continue
        if item_type == 3:
            voice_item = item.get("voice_item")
            if isinstance(voice_item, dict):
                text = str(voice_item.get("text") or "").strip()
                if text:
                    parts.append(text)
            continue
        _log.debug("ignored unsupported WeChat iLink item type %s", item_type)
    return "\n".join(parts).strip()


class WeixinAPI:
    """Small urllib client for Tencent iLink / ClawBot text endpoints."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        api_timeout_ms: int = DEFAULT_API_TIMEOUT_MS,
        opener=None,
    ) -> None:
        self.base_url = _normalize_base_url(base_url)
        self.api_timeout_ms = api_timeout_ms
        self._opener = opener or urllib.request.urlopen

    def set_base_url(self, base_url: str) -> None:
        self.base_url = _normalize_base_url(base_url)

    def _headers(self, *, token: str = "", extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
            "X-WECHAT-UIN": base64.b64encode(os.urandom(4)).decode("ascii"),
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if extra:
            headers.update(extra)
        return headers

    def request_json(
        self,
        method: str,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        token: str = "",
        timeout_ms: int | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(
            url,
            data=data,
            method=method.upper(),
            headers=self._headers(token=token, extra=headers),
        )
        timeout = (timeout_ms if timeout_ms is not None else self.api_timeout_ms) / 1000
        with self._opener(req, timeout=timeout) as resp:
            raw = resp.read()
        if not raw:
            return {}
        decoded = raw.decode("utf-8", errors="replace")
        out = json.loads(decoded)
        if not isinstance(out, dict):
            raise RuntimeError(f"WeChat iLink {endpoint} returned non-object JSON")
        return out

    def get_bot_qrcode(self, bot_type: str) -> dict[str, Any]:
        return self.request_json("GET", "ilink/bot/get_bot_qrcode", params={"bot_type": bot_type})

    def get_qrcode_status(self, qrcode_value: str, *, timeout_ms: int) -> dict[str, Any]:
        return self.request_json(
            "GET",
            "ilink/bot/get_qrcode_status",
            params={"qrcode": qrcode_value},
            timeout_ms=timeout_ms,
            headers={"iLink-App-ClientVersion": "1"},
        )

    def get_updates(self, *, token: str, sync_buf: str, timeout_ms: int) -> dict[str, Any]:
        return self.request_json(
            "POST",
            "ilink/bot/getupdates",
            payload={
                "base_info": {"channel_version": CHANNEL_VERSION},
                "get_updates_buf": sync_buf,
            },
            token=token,
            timeout_ms=timeout_ms,
        )

    def send_text(self, *, token: str, to_user_id: str, context_token: str, text: str) -> dict[str, Any]:
        return self.request_json(
            "POST",
            "ilink/bot/sendmessage",
            payload={
                "base_info": {"channel_version": CHANNEL_VERSION},
                "msg": {
                    "from_user_id": "",
                    "to_user_id": to_user_id,
                    "client_id": uuid.uuid4().hex,
                    "message_type": 2,
                    "message_state": 2,
                    "context_token": context_token,
                    "item_list": [{"type": 1, "text_item": {"text": text}}],
                },
            },
            token=token,
        )


class WeixinAdapter(Adapter):
    """Personal WeChat adapter over Tencent's official iLink / ClawBot API.

    The bot can only message a user after that user has messaged it in the
    current iLink session because sendmessage requires the inbound
    context_token. Media/CDN crypto is intentionally out of scope.
    """

    max_message_length = WEIXIN_TEXT_MAX

    def __init__(
        self,
        config: dict[str, Any],
        *,
        opener=None,
        state_path: str | Path | None = None,
        output: TextIO | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = dict(config)
        self.bot_type = str(self.config.get("bot_type") or DEFAULT_BOT_TYPE).strip() or DEFAULT_BOT_TYPE
        self.long_poll_timeout_ms = _int_config(
            self.config.get("long_poll_timeout_ms"),
            DEFAULT_LONG_POLL_TIMEOUT_MS,
            1_000,
        )
        self.api_timeout_ms = _int_config(self.config.get("api_timeout_ms"), DEFAULT_API_TIMEOUT_MS, 1_000)
        self.base_url = _normalize_base_url(self.config.get("base_url"))
        self.state_path = Path(state_path).expanduser().resolve() if state_path is not None else default_state_path()
        self._output = output or sys.stderr
        self._sleep = sleep
        self._monotonic = monotonic
        self._closed = threading.Event()
        self._state_lock = threading.RLock()
        self._api = WeixinAPI(base_url=self.base_url, api_timeout_ms=self.api_timeout_ms, opener=opener)

        self.token = ""
        self.account_id = ""
        self.ilink_bot_id = ""
        self.ilink_user_id = ""
        self.sync_buf = ""
        self.context_tokens: dict[str, str] = {}
        self.needs_relogin = False
        self._reply_target = ""
        self._last_sender = ""
        self._load_state()

    @property
    def name(self) -> str:
        return "weixin"

    def set_reply_target(self, message: InboundMessage) -> None:
        self._reply_target = str(message.sender_id).strip()
        if self._reply_target:
            self._last_sender = self._reply_target

    def clear_reply_target(self) -> None:
        self._reply_target = ""

    def _load_state(self) -> None:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, json.JSONDecodeError) as e:
            raise RuntimeError(f"WeChat state file {self.state_path} is unreadable: {e}") from e
        if not isinstance(data, dict):
            raise RuntimeError(f"WeChat state file {self.state_path} must contain a JSON object")
        self.token = str(data.get("token") or "").strip()
        self.account_id = str(data.get("account_id") or "").strip()
        self.ilink_bot_id = str(data.get("ilink_bot_id") or "").strip()
        self.ilink_user_id = str(data.get("ilink_user_id") or "").strip()
        self.sync_buf = str(data.get("sync_buf") or "").strip()
        self.needs_relogin = bool(data.get("needs_relogin"))
        saved_base = str(data.get("base_url") or "").strip()
        if saved_base:
            self.base_url = _normalize_base_url(saved_base)
            self._api.set_base_url(self.base_url)
        raw_tokens = data.get("context_tokens")
        if isinstance(raw_tokens, dict):
            self.context_tokens = {
                str(user_id).strip(): str(context_token).strip()
                for user_id, context_token in raw_tokens.items()
                if str(user_id).strip() and str(context_token).strip()
            }

    def _state_snapshot(self) -> dict[str, Any]:
        account_id = self.account_id or self.ilink_bot_id or self.ilink_user_id
        return {
            "token": self.token,
            "account_id": account_id,
            "ilink_bot_id": self.ilink_bot_id,
            "ilink_user_id": self.ilink_user_id,
            "base_url": self.base_url,
            "sync_buf": self.sync_buf,
            "context_tokens": dict(sorted(self.context_tokens.items())),
            "needs_relogin": self.needs_relogin,
        }

    def _save_state(self) -> None:
        with self._state_lock:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            data = json.dumps(self._state_snapshot(), ensure_ascii=False, indent=2, sort_keys=True)
            tmp = self.state_path.with_name(f".{self.state_path.name}.{os.getpid()}.tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(data)
                    f.write("\n")
                os.replace(tmp, self.state_path)
                os.chmod(self.state_path, 0o600)
            finally:
                try:
                    if tmp.exists():
                        tmp.unlink()
                except OSError:
                    pass

    def _print_login_qr(self, qrcode_value: str) -> None:
        print(
            "WeChat iLink login: scan this QR with your phone WeChat / "
            "微信 iLink 登录：请用手机微信扫码。",
            file=self._output,
            flush=True,
        )
        try:
            import qrcode  # type: ignore[import-not-found]

            qr = qrcode.QRCode(border=1)
            qr.add_data(qrcode_value)
            qr.make(fit=True)
            qr.print_ascii(out=self._output, tty=False, invert=True)
        except ImportError:
            print(
                "Install the optional messaging extra for terminal QR ASCII "
                "(qrcode); using the fallback URL below.",
                file=self._output,
                flush=True,
            )
        except Exception as e:
            _log.debug("failed to render WeChat login QR as ASCII: %s", e)
        print(f"WeChat QR fallback URL / 微信二维码备用链接: {qr_fallback_url(qrcode_value)}", file=self._output, flush=True)

    def _login(self) -> None:
        for refresh in range(QRCODE_REFRESHES + 1):
            data = self._api.get_bot_qrcode(self.bot_type)
            qrcode_value = _str_field(data, "qrcode")
            if not qrcode_value:
                raise RuntimeError("WeChat iLink login returned no qrcode")
            self._print_login_qr(qrcode_value)
            if refresh:
                _log.info("WeChat iLink QR refreshed (%s/%s)", refresh, QRCODE_REFRESHES)
            deadline = self._monotonic() + QRCODE_VALID_SECONDS
            while not self._closed.is_set() and self._monotonic() < deadline:
                status = self._api.get_qrcode_status(qrcode_value, timeout_ms=self.long_poll_timeout_ms)
                raw_status = _str_field(status, "status") or "wait"
                if raw_status == "confirmed":
                    token = _str_field(status, "bot_token")
                    if not token:
                        raise RuntimeError("WeChat iLink login confirmed but returned no bot_token")
                    self.token = token
                    self.ilink_bot_id = _str_field(status, "ilink_bot_id")
                    self.ilink_user_id = _str_field(status, "ilink_user_id")
                    self.account_id = self.ilink_bot_id or self.ilink_user_id
                    self.base_url = _normalize_base_url(_str_field(status, "baseurl") or self.base_url)
                    self._api.set_base_url(self.base_url)
                    self.needs_relogin = False
                    self._save_state()
                    _log.info("WeChat iLink login confirmed for account %s", self.account_id or "(unknown)")
                    return
                if raw_status == "expired":
                    break
                if raw_status in {"cancel", "canceled", "denied"}:
                    raise RuntimeError("WeChat iLink login was canceled or denied")
                self._sleep(1.0)
        raise RuntimeError("WeChat iLink QR login expired too many times; run the gateway again")

    def _ensure_login(self) -> None:
        if self.token and not self.needs_relogin:
            return
        if self.needs_relogin:
            _log.error("WeChat iLink state needs re-login; starting QR scan flow")
        self._login()

    def _mark_needs_relogin(self) -> None:
        self.needs_relogin = True
        self._save_state()

    def _handle_session_timeout(self, action: str, payload: dict[str, Any]) -> None:
        self._mark_needs_relogin()
        message = f"WeChat iLink {action} session timed out ({_format_api_error(payload)}); QR re-login is required"
        _log.error(message)
        raise RuntimeError(message)

    def _target_for_send(self) -> str:
        if self._reply_target:
            return self._reply_target
        if self._last_sender:
            return self._last_sender
        if len(self.context_tokens) == 1:
            return next(iter(self.context_tokens))
        return ""

    def send(self, text: str) -> None:
        self._ensure_login()
        target = self._target_for_send()
        if not target:
            message = (
                "WeChat iLink is waiting for the human to say hi first; "
                "sendmessage requires a per-user context_token."
            )
            _log.warning(message)
            raise DeliveryDeferred(message)
        context_token = self.context_tokens.get(target, "")
        if not context_token:
            message = (
                f"WeChat iLink cannot send to {target}: waiting for the human to say hi first "
                "so the platform provides a context_token."
            )
            _log.warning(message)
            raise DeliveryDeferred(message)
        payload = self._api.send_text(token=self.token, to_user_id=target, context_token=context_token, text=text)
        if _ok(payload):
            return
        if _errcode(payload) == SESSION_TIMEOUT_ERRCODE:
            self._handle_session_timeout("sendmessage", payload)
        raise RuntimeError(f"WeChat iLink sendmessage failed: {_format_api_error(payload)}")

    def _handle_inbound_message(self, msg: dict[str, Any], inbox: "queue.Queue[InboundMessage]") -> bool:
        sender_id = (
            str(msg.get("from_user_id") or msg.get("ilink_user_id") or msg.get("sender_id") or "").strip()
        )
        if not sender_id:
            _log.debug("ignored WeChat iLink message without sender id")
            return False
        context_token = str(msg.get("context_token") or "").strip()
        dirty = False
        if context_token and self.context_tokens.get(sender_id) != context_token:
            self.context_tokens[sender_id] = context_token
            dirty = True
        text = item_list_to_text(msg.get("item_list"))
        if text:
            self._last_sender = sender_id
            inbox.put(InboundMessage(sender_id=sender_id, sender_name=sender_id, text=text, reply=msg))
        return dirty

    def poll_once(self, inbox: "queue.Queue[InboundMessage]") -> int:
        """Poll one iLink getupdates response. Exposed for tests."""

        self._ensure_login()
        data = self._api.get_updates(token=self.token, sync_buf=self.sync_buf, timeout_ms=self.long_poll_timeout_ms)
        if not _ok(data):
            if _errcode(data) == SESSION_TIMEOUT_ERRCODE:
                self._handle_session_timeout("getupdates", data)
            raise RuntimeError(f"WeChat iLink getupdates failed: {_format_api_error(data)}")

        dirty = False
        if data.get("get_updates_buf"):
            self.sync_buf = str(data.get("get_updates_buf") or "")
            dirty = True

        count = 0
        msgs = data.get("msgs")
        if isinstance(msgs, list):
            for msg in msgs:
                if not isinstance(msg, dict):
                    continue
                dirty = self._handle_inbound_message(msg, inbox) or dirty
                count += 1
        if dirty:
            self._save_state()
        return count

    def run(self, inbox: "queue.Queue[InboundMessage]") -> None:
        self._ensure_login()
        while not self._closed.is_set():
            try:
                self.poll_once(inbox)
            except RuntimeError:
                raise
            except Exception as e:
                _log.warning("WeChat iLink getupdates error: %s", e)
                self._sleep(5.0)

    def close(self) -> None:
        self._closed.set()
