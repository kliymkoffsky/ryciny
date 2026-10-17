"""Samsung The Frame: the TV's local Art Mode API, the same one the app's SamsungFrame.kt uses (and samsungtvws).

A WebSocket on the art-app channel for requests and a plain TCP "D2D" socket the TV opens for the image bytes.
Port 8002 is TLS with the TV's self-signed certificate, so it is not checked: this talks only to the address
set in the add-on, on the home network. The first connection makes the TV ask on screen whether to allow
"Ryciny": accept it with the remote; the TV then hands out a token, kept in /data/frame.json.
"""

from __future__ import annotations

import asyncio
import base64
import datetime as dt
import json
import logging
import random
import socket
import ssl
import struct
import threading
import time
import uuid

import websockets

log = logging.getLogger(__name__)

WATCH_WAIT_S = 5 * 60


class FrameError(Exception):
    pass


class Watching(Exception):
    """The TV is showing something else (Netflix, a channel): never switch it to Art Mode."""


def _tls() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


class Session:
    def __init__(self, host: str, token: str | None, on_token, port: int = 8002) -> None:
        self.host, self.token, self.on_token, self.port = host, token, on_token, port
        self.ws = None

    async def __aenter__(self):
        name = base64.b64encode(b"Ryciny").decode()
        url = f"wss://{self.host}:{self.port}/api/v2/channels/com.samsung.art-app?name={name}" + (f"&token={self.token}" if self.token else "")
        try:
            self.ws = await websockets.connect(url, ssl=_tls(), open_timeout=8, max_size=None, ping_interval=None)
        except (OSError, asyncio.TimeoutError) as e:
            raise FrameError(f"telewizor nie odpowiada pod {self.host} ({e})") from e
        # Pairing waits on a person with a remote, so the first event gets a minute.
        connect = await self._next(60, lambda m: m.get("event") in ("ms.channel.connect", "ms.channel.unauthorized"))
        if connect["event"] == "ms.channel.unauthorized":
            raise FrameError("telewizor odmówił dostępu: zezwól na „Ryciny” w ustawieniach urządzeń zewnętrznych")
        token = (connect.get("data") or {}).get("token")
        if token and token != self.token:
            self.on_token(token)
        await self._next(15, lambda m: m.get("event") == "ms.channel.ready")
        return self

    async def __aexit__(self, *_):
        if self.ws:
            await self.ws.close()

    async def _next(self, timeout: float, match) -> dict:
        async def loop():
            while True:
                m = json.loads(await self.ws.recv())
                if m.get("event") == "ms.error":
                    raise FrameError(f"telewizor: {(m.get('data') or {}).get('message')}")
                if match(m):
                    return m
        try:
            return await asyncio.wait_for(loop(), timeout)
        except asyncio.TimeoutError as e:
            raise FrameError("telewizor nie odpowiedział na czas; czy jest włączony albo w Art Mode?") from e

    async def request(self, request: str, wait_for: str | None = None, rid: str | None = None, **params) -> dict:
        rid = rid or str(uuid.uuid4())
        data = {"request": request, **params, "id": rid, "request_id": rid}
        await self.ws.send(json.dumps({"method": "ms.channel.emit",
                                       "params": {"event": "art_app_request", "to": "host", "data": json.dumps(data)}}))
        return await self._answer(rid, wait_for)

    async def _answer(self, rid: str | None, event: str | None) -> dict:
        while True:
            m = await self._next(30, lambda x: x.get("event") == "d2d_service_message")
            try:
                payload = json.loads(m.get("data") or "{}")
            except ValueError:
                continue
            mid = payload.get("request_id") or payload.get("id")
            if rid is not None and mid != rid:
                continue
            if payload.get("event") == "error":
                raise FrameError(f"telewizor zwrócił błąd {payload.get('error_code', '?')}")
            if event is None or payload.get("event") == event:
                return payload

    async def upload(self, jpeg: bytes) -> str:
        rid = str(uuid.uuid4())
        ready = await self.request(
            "send_image", wait_for="ready_to_use", rid=rid, file_type="jpg", file_size=len(jpeg),
            image_date=dt.datetime.now().strftime("%Y:%m:%d %H:%M:%S"),
            matte_id="none", portrait_matte_id="none",  # the plate carries its own paper and border
            conn_info={"d2d_mode": "socket", "connection_id": random.randrange(4 * 1024**3), "id": rid},
        )
        info = ready["conn_info"]
        if isinstance(info, str):
            info = json.loads(info)
        header = json.dumps({"num": 0, "total": 1, "fileLength": len(jpeg), "fileName": "ryciny", "fileType": "jpg",
                             "secKey": info["key"], "version": "0.0.1"}).encode("ascii")
        ip, port = info["ip"], int(info["port"])

        def send() -> None:
            raw = socket.create_connection((ip, port), timeout=15)
            sock = _tls().wrap_socket(raw, server_hostname=ip) if info.get("secured") else raw
            with sock:
                sock.sendall(struct.pack(">I", len(header)) + header + jpeg)

        await asyncio.get_running_loop().run_in_executor(None, send)
        added = await self._answer(None, "image_added")
        if not added.get("content_id"):
            raise FrameError("telewizor nie podał id obrazu")
        return added["content_id"]

    async def take_over(self, ours: str | None) -> dict:
        """Notes the TV's current artwork, slideshow and auto-rotation, and turns the latter two off."""
        async def get(req):
            try:
                return await self.request(req)
            except FrameError:
                return {}
        current = await get("get_current_artwork")
        slideshow = {k: v for k, v in (await get("get_slideshow_status")).items() if k in ("value", "category_id", "type")}
        rotation = {k: v for k, v in (await get("get_auto_rotation_status")).items() if k in ("value", "category_id", "type")}
        for req, status in (("set_slideshow_status", slideshow), ("set_auto_rotation_status", rotation)):
            if status.get("value") not in (None, "off"):
                await self.set_rotation(req, {**status, "value": "off"})
        cid = current.get("content_id", "")
        return {"contentId": "" if cid == ours else cid, "categoryId": current.get("category_id", ""),
                "slideshow": slideshow, "rotation": rotation}

    async def set_rotation(self, req: str, status: dict) -> None:
        try:
            await self.request(req, value=status.get("value", "off"), category_id=status.get("category_id", "MY-C0002"),
                               type=status.get("type", "shuffleslideshow"))
        except FrameError as e:
            log.warning("frame %s: %s", req, e)

    async def delete(self, cid: str) -> None:
        try:
            await self.request("delete_image_list", content_id_list=[{"content_id": cid}])
        except FrameError as e:
            log.warning("frame delete %s: %s", cid, e)


class Frame:
    """Keeps The Frame showing the TV plate (tvplate.py): on a change of what is heard, at most every few minutes."""

    def __init__(self, cfg, state_file) -> None:
        self.cfg = cfg
        self.file = state_file
        self.lock = threading.Lock()
        self.state = self._load()
        self.status = ""
        self.sent_at = 0.0
        self.identity: str | None = None
        self.next_try = 0.0  # while the TV is used for watching, ask again only every few minutes

    def _load(self) -> dict:
        try:
            return json.loads(self.file.read_text())
        except (OSError, ValueError):
            return {}

    def _save(self) -> None:
        self.file.write_text(json.dumps(self.state))

    def _token(self, token: str) -> None:
        self.state["token"] = token
        self._save()

    def push(self, jpeg: bytes, identity: str, title: str) -> None:
        with self.lock:
            host = self.cfg.frame_host.strip()
            if not host:
                self.status = "wpisz adres IP telewizora"
                return
            self.status = "łączę; jeśli telewizor zapyta, zezwól pilotem na „Ryciny”" if not self.state.get("token") else "wysyłam…"
            try:
                cid = asyncio.run(self._show(host, jpeg))
            except Watching:
                self.next_try = time.time() + WATCH_WAIT_S
                self.status = f"{dt.datetime.now():%H:%M}: telewizor jest używany do oglądania; rycina poczeka na Art Mode"
                log.info("frame: TV not in Art Mode, skipped")
                return
            except FrameError as e:
                self.status = f"błąd: {e}"
                log.warning("frame: %s", e)
                return
            except Exception as e:  # noqa: BLE001
                self.status = f"błąd: {e}"
                log.exception("frame")
                return
            self.state["contentId"] = cid
            self._save()
            self.sent_at, self.identity = time.time(), identity
            self.status = f"wysłano o {dt.datetime.now():%H:%M}: {title} ({len(jpeg) // 1024} kB)"
            log.info("frame: %s", self.status)

    async def _show(self, host: str, jpeg: bytes) -> str:
        async with Session(host, self.state.get("token"), self._token) as s:
            # Only while the TV shows art (or is "off", which on The Frame is Art Mode): never interrupt watching.
            mode = await s.request("get_artmode_status")
            if mode.get("value") != "on":
                raise Watching()
            previous = self.state.get("contentId")
            if "original" not in self.state:
                self.state["original"] = await s.take_over(previous)
                self._save()
            cid = await s.upload(jpeg)
            await s.request("select_image", content_id=cid, show=True)
            if previous and previous != cid:
                await s.delete(previous)
            return cid

    def art_mode(self) -> str:
        """The TV's Art Mode status ("on"/"off"), without sending or switching anything."""
        async def ask() -> str:
            async with Session(self.cfg.frame_host.strip(), self.state.get("token"), self._token) as s:
                return str((await s.request("get_artmode_status")).get("value"))
        with self.lock:
            return asyncio.run(ask())

    def restore(self) -> None:
        """Takes the plate off the TV and puts back the TV's own artwork, slideshow and auto-rotation."""
        with self.lock:
            host = self.cfg.frame_host.strip()
            if not host:
                return
            try:
                asyncio.run(self._restore(host))
            except Exception as e:  # noqa: BLE001
                self.status = f"błąd: {e}"
                return
            had = (self.state.get("original") or {}).get("contentId")
            self.state.pop("contentId", None)
            self.state.pop("original", None)
            self._save()
            self.identity = None
            self.status = "przywrócono sztukę z telewizora" if had else "rycina usunięta; telewizor pokazuje swoją sztukę"

    async def _restore(self, host: str) -> None:
        async with Session(host, self.state.get("token"), self._token) as s:
            o = self.state.get("original") or {}
            if o.get("contentId"):
                params = {"content_id": o["contentId"], "show": True}
                if o.get("categoryId"):
                    params["category_id"] = o["categoryId"]
                try:
                    await s.request("select_image", **params)
                except FrameError as e:
                    log.warning("frame select original: %s", e)
            for req, key in (("set_slideshow_status", "slideshow"), ("set_auto_rotation_status", "rotation")):
                if (o.get(key) or {}).get("value"):
                    await s.set_rotation(req, o[key])
            if self.state.get("contentId"):
                await s.delete(self.state["contentId"])
