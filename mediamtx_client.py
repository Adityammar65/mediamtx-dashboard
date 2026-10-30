from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
import asyncio
import time
from pathlib import Path
from typing import Optional

import httpx
import yaml
from fastapi import HTTPException

from config import settings


_SENSITIVE_QUERY_KEYS = {
    "access_token",
    "apikey",
    "api_key",
    "authorization",
    "auth",
    "password",
    "passwd",
    "refresh_token",
    "secret",
    "token",
}


def _mask_sensitive_url(value):
    if not isinstance(value, str):
        return value

    parts = urlsplit(value)
    netloc = parts.netloc
    if "@" in netloc:
        netloc = f"***:***@{netloc.rsplit('@', 1)[1]}"

    query = []
    for key, item in parse_qsl(parts.query, keep_blank_values=True):
        normalized_key = key.lower().replace("-", "_")
        sensitive = normalized_key in _SENSITIVE_QUERY_KEYS or any(
            marker in normalized_key for marker in ("token", "password", "passwd", "secret", "authorization", "apikey")
        )
        query.append((key, "***" if sensitive else item))
    return urlunsplit((parts.scheme, netloc, parts.path, urlencode(query), parts.fragment))


def _mask_path_config(config):
    if not isinstance(config, dict):
        return config

    safe_config = dict(config)
    for key in ("source", "sourceRedirect", "fallback"):
        if key in safe_config:
            safe_config[key] = _mask_sensitive_url(safe_config[key])
    return safe_config


class MediaMTXClient:
    _instance = None

    # RAM Version Control / State cache
    _cache_lock = asyncio.Lock()
    _ram_config = {}
    _cache_loaded = False
    _yaml_path = Path("mediamtx.yml")
    _is_dirty = False
    _last_modified = 0.0
    _debounce_seconds = 30.0  # Simpan ke file jika sudah tenang selama 5 menit

    def __init__(self):
        base = str(settings.MEDIAMTX_API_URL).rstrip("/")
        self.base_url = f"{base}/v3"
        self.client = httpx.AsyncClient(timeout=10.0)
        self.yaml_path = self._yaml_path
        if not MediaMTXClient._cache_loaded:
            self._load_initial_cache()

    def _load_initial_cache(self):
        """Memuat konfigurasi awal dari file yml ke RAM saat pertama kali inisialisasi."""
        try:
            if self.yaml_path.exists():
                MediaMTXClient._ram_config = yaml.safe_load(self.yaml_path.read_text()) or {}
            MediaMTXClient._cache_loaded = True
        except Exception as e:
            print(f"[Warning] Gagal memuat cache mediamtx.yml: {e}")

    @staticmethod
    def _sanitize_config_for_mediamtx(config: dict) -> dict:
        """Membersihkan struktur config agar tidak ada objek bersarang yang invalid untuk tipe data Go/MediaMTX."""
        # List of fields that are aliased (not strictly bool) in MediaMTX
        alias_fields = {"rtspEncryption", "rtmpEncryption", "hlsVariant", "authMethod"}
        cleaned = {}

        for key, value in config.items():
            if isinstance(value, dict):
                cleaned[key] = MediaMTXClient._sanitize_config_for_mediamtx(value)
            elif isinstance(value, bool):
                if key in alias_fields:
                    cleaned[key] = "yes" if value else "no"
                else:
                    cleaned[key] = value
            elif isinstance(value, str):
                if key not in alias_fields and value.lower() == "true":
                    cleaned[key] = True
                elif key not in alias_fields and value.lower() == "false":
                    cleaned[key] = False
                else:
                    cleaned[key] = value
            else:
                cleaned[key] = value
        return cleaned

    async def _queue_save_to_yaml(self, new_config: dict, path_name: Optional[str] = None):
        """Mencatat perubahan ke RAM terlebih dahulu dan menandai dirty (debounce pattern)."""
        async with self._cache_lock:
            if path_name:
                if "paths" not in MediaMTXClient._ram_config or not isinstance(MediaMTXClient._ram_config["paths"], dict):
                    MediaMTXClient._ram_config["paths"] = {}
                if path_name not in MediaMTXClient._ram_config["paths"] or not isinstance(MediaMTXClient._ram_config["paths"][path_name], dict):
                    MediaMTXClient._ram_config["paths"][path_name] = {}
                MediaMTXClient._ram_config["paths"][path_name].update(new_config)
            else:
                MediaMTXClient._ram_config.update(new_config)

            MediaMTXClient._is_dirty = True
            MediaMTXClient._last_modified = time.time()

        # Jalankan background task untuk debounce save
        asyncio.create_task(self._debounce_flush())

    async def _debounce_flush(self):
        """Menunggu hingga aktivitas konfigurasi mereda sebelum menulis ke disk."""
        await asyncio.sleep(self._debounce_seconds)
        async with self._cache_lock:
            if MediaMTXClient._is_dirty and (time.time() - MediaMTXClient._last_modified >= self._debounce_seconds):
                try:
                    safe_config = MediaMTXClient._sanitize_config_for_mediamtx(MediaMTXClient._ram_config)

                    self.yaml_path.write_text(yaml.dump(safe_config, sort_keys=False, allow_unicode=True))
                    MediaMTXClient._is_dirty = False
                    print("[Info] Konfigurasi berhasil disinkronkan ke mediamtx.yml (Debounced).")
                except Exception as e:
                    print(f"[Warning] Gagal flush ke mediamtx.yml: {e}")

    @classmethod
    def force_flush_sync(cls):
        """Dipanggil saat shutdown aplikasi untuk memastikan tidak ada data RAM yang tertinggal."""
        if cls._is_dirty and cls._yaml_path.exists():
            try:
                cls._yaml_path.write_text(yaml.dump(cls._ram_config, sort_keys=False, allow_unicode=True))
                cls._is_dirty = False
                print("[Info] Final sync: mediamtx.yml berhasil diperbarui.")
            except Exception as e:
                print(f"[Error] Gagal final sync ke mediamtx.yml: {e}")

    # --- Server ---
    async def get_server_health(self):
        try:
            r = await self.client.get(f"{self.base_url}/info")
            r.raise_for_status()
            return {"connected": True, **r.json()}
        except httpx.HTTPError:
            return {"connected": False, "version": "unknown"}

    async def get_server_config(self):
        r = await self.client.get(f"{self.base_url}/config/global/get")
        r.raise_for_status()
        return r.json()

    async def patch_server_config(self, payload):
        try:
            cleaned_payload = {}
            for key, value in payload.items():
                if key == "paths":
                    cleaned_payload[key] = value
                    continue

                if isinstance(value, dict):
                    if "enabled" in value:
                        cleaned_payload[key] = bool(value["enabled"])
                    else:
                        cleaned_payload[key] = value
                    continue

                if value == "true" or value is True:
                    cleaned_payload[key] = True
                elif value == "false" or value is False:
                    cleaned_payload[key] = False
                else:
                    cleaned_payload[key] = value

            cleaned_payload.pop("status", None)

            r = await self.client.patch(
                f"{self.base_url}/config/global/patch", json=cleaned_payload
            )
            if r.is_error:
                error_detail = r.text
                raise HTTPException(
                    status_code=r.status_code,
                    detail=f"MediaMTX Error: {error_detail}"
                )

            r.raise_for_status()
            await self._queue_save_to_yaml(cleaned_payload)
            return r.json()
        except httpx.HTTPStatusError as exc:
            print(f"HTTP Error from MediaMTX: {exc.response.text}")
            raise HTTPException(
                status_code=exc.response.status_code,
                detail=exc.response.text
            )

    # --- Paths ---
    async def list_paths(self):
        r = await self.client.get(f"{self.base_url}/config/paths/list")
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            data["items"] = [_mask_path_config(item) for item in data["items"]]
        return data

    async def create_path(self, name, source, source_on_demand, **kwargs):
        data = {}
        if source:
            data["source"] = source
            # sourceOnDemand applies to URL sources; sending it for publisher
            # and redirect paths can make MediaMTX reject the configuration.
            if source_on_demand is not None:
                data["sourceOnDemand"] = source_on_demand
        elif kwargs.get("source_redirect"):
            data["source"] = "redirect"
        # Optional fields
        if kwargs.get("source_on_demand_start_timeout"):
            data["sourceOnDemandStartTimeout"] = kwargs["source_on_demand_start_timeout"]
        if kwargs.get("source_on_demand_close_after"):
            data["sourceOnDemandCloseAfter"] = kwargs["source_on_demand_close_after"]
        if kwargs.get("max_readers") is not None:
            data["maxReaders"] = kwargs["max_readers"]
        if kwargs.get("fallback"):
            data["fallback"] = kwargs["fallback"]
        if kwargs.get("source_redirect"):
            data["sourceRedirect"] = kwargs["source_redirect"]
        r = await self.client.post(f"{self.base_url}/config/paths/add/{name}", json=data)
        r.raise_for_status()
        await self._queue_save_to_yaml(data, path_name=name)
        return r.json()

    async def get_path(self, name):
        encoded_name = quote(name, safe="")
        url = f"{self.base_url}/config/paths/get/{encoded_name}"

        r = await self.client.get(url)
        if r.status_code == 404:
            raise HTTPException(404, "Path not found")
        r.raise_for_status()
        return _mask_path_config(r.json())

    async def update_path(self, name, payload):
        # Map frontend field names to MediaMTX API field names
        mapped = {}
        field_map = {
            "source": "source",
            "source_on_demand": "sourceOnDemand",
            "source_on_demand_start_timeout": "sourceOnDemandStartTimeout",
            "source_on_demand_close_after": "sourceOnDemandCloseAfter",
            "max_readers": "maxReaders",
            "fallback": "fallback",
            "source_redirect": "sourceRedirect",
        }
        for key, value in payload.items():
            if key in field_map and value is not None:
                mapped[field_map[key]] = value
        r = await self.client.patch(
            f"{self.base_url}/config/paths/patch/{quote(name, safe='')}",
            json=mapped,
        )
        if r.status_code == 404:
            raise HTTPException(404, "Path not found")
        r.raise_for_status()
        await self._queue_save_to_yaml(payload, path_name=name)
        return r.json()

    async def delete_path(self, name):
        r = await self.client.delete(f"{self.base_url}/config/paths/delete/{quote(name, safe='')}")
        if r.status_code == 404:
            raise HTTPException(404, "Path not found")
        r.raise_for_status()
        async with self._cache_lock:
            paths = MediaMTXClient._ram_config.get("paths", {})
            if isinstance(paths, dict):
                paths.pop(name, None)
            MediaMTXClient._is_dirty = True
            MediaMTXClient._last_modified = time.time()
        asyncio.create_task(self._debounce_flush())

    # --- Streams ---
    async def list_streams(self):
        rtsp_con = await self.list_rtsp_connections()
        rtmp_con = await self.list_rtmp_connections()
        hls_con = await self.list_hls_connections()
        rtsp_ses = await self.list_rtsp_sessions()
        rtmp_ses = await self.list_rtmp_sessions()
        hls_ses = await self.list_hls_sessions()

        rtsp_items = rtsp_con.get("items", []) or []
        rtmp_items = rtmp_con.get("items", []) or []
        hls_items = hls_con.get("items", []) or []

        rtsp_items_ses = rtsp_ses.get("items", []) or []
        rtmp_items_ses = rtmp_ses.get("items", []) or []
        hls_items_ses = hls_ses.get("items", []) or []

        normalized = []

        for s in rtsp_items:
            if s.get("state", "") == "":
                continue
            normalized.append({
                "type": "rtsp",
                "id": s.get("id", "unknown"),
                "name": s.get("path", "unknown"),
                "remote_addr": s.get("remoteAddr", ""),
                "state": s.get("state", ""),
                "bytes_received": s.get("bytesReceived", 0),
                "bytes_sent": s.get("bytesSent", 0)
            })

        # Normalisasi koneksi RTMP
        for s in rtmp_items:
            if s.get("state", "") == "":
                continue
            normalized.append({
                "type": "rtmp",
                "id": s.get("id", "unknown"),
                "name": s.get("path", "unknown"),
                "remote_addr": s.get("remoteAddr", ""),
                "state": s.get("state", ""),
                "bytes_received": s.get("bytesReceived", 0),
                "bytes_sent": s.get("bytesSent", 0)
            })

        # Normalisasi koneksi HLS
        for s in hls_items:
            if s.get("state", "") == "":
                continue
            normalized.append({
                "type": "hls",
                "id": s.get("id", "unknown"),
                "name": s.get("path", "unknown"),
                "remote_addr": s.get("remoteAddr", ""),
                "state": s.get("state", ""),
                "bytes_received": s.get("bytesReceived", 0),
                "bytes_sent": s.get("bytesSent", 0)
            })

        # Normalisasi sesi rtsp
        for s in rtsp_items_ses:
            normalized.append({
                "type": "rtsp",
                "id": s.get("id", "unknown"),
                "name": s.get("path", "unknown"),
                "remote_addr": s.get("remoteAddr", ""),
                "state": s.get("state", ""),
                "bytes_received": s.get("bytesReceived", 0),
                "bytes_sent": s.get("bytesSent", 0)
            })

        # Normalisasi sesi RTMP
        for s in rtmp_items_ses:
            normalized.append({
                "type": "rtmp",
                "id": s.get("id", "unknown"),
                "name": s.get("path", "unknown"),
                "remote_addr": s.get("remoteAddr", ""),
                "state": s.get("state", ""),
                "bytes_received": s.get("bytesReceived", 0),
                "bytes_sent": s.get("bytesSent", 0)
            })

        # Normalisasi sesi HLS
        for s in hls_items_ses:
            normalized.append({
                "type": "hls",
                "id": s.get("id", "unknown"),
                "name": s.get("path", "unknown"),
                "remote_addr": s.get("remoteAddr", ""),
                "state": s.get("state", ""),
                "bytes_received": s.get("bytesReceived", 0),
                "bytes_sent": s.get("bytesSent", 0)
            })

        return {"items": normalized}

    async def get_streams_summary(self):
        items = []
        page = 0

        async def fetching(page):
            r = await self.client.get(f"{self.base_url}/paths/list",
                params={"page": page, "itemsPerPage": 100})
            r.raise_for_status()
            data = r.json()
            return data

        while True:
            datas = await fetching(page)
            page += 1
            page_items = datas.get("items", []) if isinstance(datas, dict) else []

            if page_items :
                items.extend(page_items)
            else:
                break;

        def safe_int(val):
            if isinstance(val, int): return val
            if isinstance(val, list): return len(val)
            return 0

        online = sum(1 for s in items if s.get("ready"))
        list_online = [s for s in items if s.get("ready")]
        return {
            "total": len(items),
            "online": online,
            "offline": len(items) - online,
            "total_readers": sum(safe_int(s.get("readers")) for s in items),
            "total_bytes_received": sum(s.get("bytesReceived", 0) for s in items),
            "total_bytes_sent": sum(s.get("bytesSent", 0) for s in items),
            "online_lists": list_online
        }

    async def get_stream_detail(self, name):
        encoded_name = quote(name, safe="")
        url = f"{self.base_url}/paths/get/{encoded_name}"

        r = await self.client.get(url)
        r.raise_for_status()
        data = r.json()
        return {
            "name": data.get("name"),
            "ready": data.get("ready"),
            "tracks": data.get("tracks") or [],
            "readers": len(data.get("readers", [])) if isinstance(data.get("readers"), list) else 0,
            "bytes_received": data.get("bytesReceived", 0),
            "bytes_sent": data.get("bytesSent", 0)
        }

    # --- Sessions ---
    async def list_sessions(self):
        sessions = []
        protocols = ["rtsp", "webrtc"]

        for proto in protocols:
            try:
                r = await self.client.get(f"{self.base_url}/{proto}/sessions/list")
                if r.status_code == 200:
                    items = r.json().get("items", []) or []
                    for s in items:
                        sessions.append({
                            "id": s.get("id"),
                            "type": proto,
                            "path": s.get("path"),
                            "remote_addr": s.get("remoteAddr"),
                            "bytes_received": s.get("bytesReceived", 0),
                            "bytes_sent": s.get("bytesSent", 0)
                        })

            except Exception as e:
                continue
        return {"items": sessions}

    async def kick_session(self, type, id):
        # MediaMTX uses different endpoints for different protocols
        # Connections vs Sessions endpoints vary by protocol
        endpoint_map = {
            "rtsp": "rtsp/sessions/kick",
            "rtsps": "rtsp/sessions/kick",
            "rtmp": "rtmp/sessions/kick",
            "rtmps": "rtmp/sessions/kick",
            "hls": "hls/connections/kick",
            "webrtc": "webrtc/sessions/kick",
            "srt": "srt/sessions/kick",
            "moq": "moq/sessions/kick",
        }
        endpoint = endpoint_map.get(type.lower(), f"{type}/sessions/kick")
        r = await self.client.post(f"{self.base_url}/{endpoint}/{id}")
        r.raise_for_status()
        return r.json()

    async def list_all_sessions(self):
        """Fetch sessions/connections from all available protocols and normalize."""
        protocols = [
            ("rtsp", "rtsp/sessions/list"),
            ("rtsps", "rtsp/sessions/list"),
            ("rtmp", "rtmp/sessions/list"),
            ("rtmps", "rtmp/sessions/list"),
            ("hls", "hls/sessions/list"),
            ("webrtc", "webrtc/sessions/list"),
            ("srt", "srt/sessions/list"),
            ("moq", "moq/sessions/list"),
        ]

        all_sessions = []
        for proto, endpoint in protocols:
            try:
                r = await self.client.get(f"{self.base_url}/{endpoint}")
                if r.status_code == 404:
                    # Endpoint not available in this MediaMTX version
                    continue
                r.raise_for_status()
                data = r.json()
                items = data.get("items", []) or []
                for item in items:
                    normalized = self._normalize_session(item, proto)
                    if normalized:
                        all_sessions.append(normalized)
            except httpx.HTTPError:
                # Protocol endpoint not available or error, skip
                continue

        return {"items": all_sessions}

    def _normalize_session(self, item, proto):
        """Normalize session/connection item from any protocol to common schema."""
        # MediaMTX returns different field names across protocols
        # Common fields: id, path, remoteAddr/remote_addr, bytesReceived/bytes_received, bytesSent/bytes_sent, ready
        session_id = item.get("id") or item.get("ID")
        if not session_id:
            return None

        path = item.get("path") or item.get("Path") or "-"
        remote_addr = item.get("remoteAddr") or item.get("remote_addr") or item.get("RemoteAddr") or "-"
        bytes_received = item.get("bytesReceived") or item.get("bytes_received") or item.get("BytesReceived") or 0
        bytes_sent = item.get("bytesSent") or item.get("bytes_sent") or item.get("BytesSent") or 0
        ready = item.get("ready") or item.get("Ready") or False

        return {
            "id": session_id,
            "type": proto,
            "path": path,
            "remote_addr": remote_addr,
            "bytes_received": bytes_received,
            "bytes_sent": bytes_sent,
            "ready": ready,
        }

    async def close(self):
        await self.client.aclose()

    # --- Path Defaults ---
    async def get_path_defaults(self):
        r = await self.client.get(f"{self.base_url}/config/path-defaults/get")
        r.raise_for_status()
        return r.json()

    async def patch_path_defaults(self, payload):
        r = await self.client.patch(
            f"{self.base_url}/config/path-defaults/patch", json=payload
        )
        r.raise_for_status()
        return r.json()

    # --- Protocol Sessions/Connections ---
    async def list_hls_connections(self):
        try:
            r = await self.client.get(f"{self.base_url}/hls/conns/list")
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError:
            return {"items": []}

    async def list_rtsp_connections(self):
        try:
            r = await self.client.get(f"{self.base_url}/rtsp/conns/list")
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError:
            return {"items": []}

    async def list_rtmp_connections(self):
        try:
            r = await self.client.get(f"{self.base_url}/rtmp/conns/list")
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError:
            return {"items": []}

    async def list_hls_sessions(self):
        try:
            r = await self.client.get(f"{self.base_url}/hls/sessions/list")
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError:
            return {"items": []}

    async def list_rtsp_sessions(self):
        try:
            r = await self.client.get(f"{self.base_url}/rtsp/sessions/list")
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError:
            return {"items": []}

    async def list_rtmp_sessions(self):
        try:
            r = await self.client.get(f"{self.base_url}/rtmp/sessions/list")
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError:
            return {"items": []}

    # --- Metrics ---
    async def get_metrics(self):
        try:
            r = await self.client.get(f"{self.base_url}/metrics")
            r.raise_for_status()
            return r.text()
        except httpx.HTTPError:
            return ""

    # --- Logs ---
    # Log reading is handled directly in the backend via file I/O
    # This method is kept for interface compatibility but not used
    async def read_log_file(self, path, lines=100):
        return {"lines": [], "error": "Log reading not implemented in MediaMTX API"}
