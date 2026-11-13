from statistics import median
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
import asyncio
import json
import time
from collections import deque
from pathlib import Path
from typing import Optional
import re
from datetime import datetime, timezone

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

_PROTOCOL_READER_KEYS = (
    "hlsMuxers",
    "rtspSessions",
    "rtspConns",
    "rtmpConns",
    "webrtcSessions",
    "webrtcConns",
    "srtConns",
)


def _mask_sensitive_url(value):
    return value

def _mask_path_config(config):
    return config


class MediaMTXClient:
    _instance = None
    _viewer_history = {}

    _cache_lock = asyncio.Lock()
    _ram_config = {}
    _cache_loaded = False
    _yaml_path = Path(settings.MEDIAMTX_CONFIG_PATH)
    _internalUsers = Path("internalUsers.json")
    _ram_internal_users = {}
    _info = {"connected": False, "restarted": False, "version": "unknown", "started": None}
    _health_started = None
    _last_restore_started = None
    _has_reconciled_internal_users = False
    _restoring_after_restart = False
    _is_dirty = False
    _is_internal_users_dirty = False
    _yaml_save_task = None
    _json_save_task = None
    _save_debounce_seconds = 5

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        if MediaMTXClient._instance is not None:
            raise RuntimeError("MediaMTXClient is a singleton, use get_instance()")
        base = str(settings.MEDIAMTX_API_URL).rstrip("/")
        self.base_url = f"{base}/v3"
        self.client = httpx.AsyncClient(timeout=10.0)
        self.yaml_path = self._yaml_path
        if not MediaMTXClient._cache_loaded:
            self._load_initial_cache()
        self._load_internal_users_cache()

    def _load_internal_users_cache(self):
        try:
            if MediaMTXClient._internalUsers.exists():
                data = json.loads(MediaMTXClient._internalUsers.read_text())
                users = data.get("users") if isinstance(data, dict) else None
                MediaMTXClient._ram_internal_users = users if isinstance(users, dict) else {}
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[Warning] Gagal memuat internalUsers.json: {exc}")

    async def merge_server_internal_users(self):
        items = (await self.list_internal_users()).get("items", []) or []
        users = dict(MediaMTXClient._ram_internal_users)
        for item in items:
            username = item.get("user") or ""
            if not username:
                continue
            saved = users.get(username, {})
            remote_pass = item.get("pass")
            merged = {**item, **saved}
            if "pass" in saved:
                merged["pass"] = saved["pass"]
            elif remote_pass in (None, "", "<redacted>"):
                merged.pop("pass", None)
            else:
                merged["pass"] = remote_pass
            merged["ips"] = saved.get("ips", item.get("ips") or [])
            merged["permissions"] = saved.get("permissions", item.get("permissions") or [])
            users[username] = merged
        await self._queue_save_to_json({"users": users})

    def _load_initial_cache(self):
        """Memuat konfigurasi awal dari file yml ke RAM saat pertama kali inisialisasi."""
        try:
            if self.yaml_path.exists():
                data = yaml.safe_load(self.yaml_path.read_text()) or {}
                MediaMTXClient._ram_config = data
                print(f"[Debug] Loaded config from YAML: {list(data.keys())}")
            MediaMTXClient._cache_loaded = True
        except Exception as e:
            print(f"[Warning] Gagal memuat cache mediamtx.yml: {e}")

    @staticmethod
    def _sanitize_config_for_mediamtx(config: dict) -> dict:
        """Membersihkan struktur config agar tidak ada objek bersarang yang invalid untuk tipe data Go/MediaMTX."""

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

    async def _queue_save_to_yaml(self, new_config: dict, path_name: Optional[str] = None, *, delete_path: Optional[str] = None):
        """Update the in-memory snapshot and debounce its durable YAML write."""
        async with self._cache_lock:
            if path_name:
                paths = MediaMTXClient._ram_config.setdefault("paths", {})
                if not isinstance(paths, dict):
                    raise ValueError("Cached paths configuration must be a mapping")
                paths.setdefault(path_name, {}).update(new_config)
            else:
                MediaMTXClient._ram_config.update(new_config)
            if delete_path is not None:
                paths = MediaMTXClient._ram_config.get("paths", {})
                if isinstance(paths, dict):
                    paths.pop(delete_path, None)
            MediaMTXClient._is_dirty = True
            task = MediaMTXClient._yaml_save_task
            if task and not task.done():
                task.cancel()
            MediaMTXClient._yaml_save_task = asyncio.create_task(self._delayed_yaml_save())

    async def _delayed_yaml_save(self):
        try:
            await asyncio.sleep(MediaMTXClient._save_debounce_seconds)
            async with MediaMTXClient._cache_lock:
                self._write_yaml_snapshot()
                MediaMTXClient._is_dirty = False
        except asyncio.CancelledError:
            raise
        except OSError as exc:
            print(f"[Error] Failed to persist {self.yaml_path}: {exc}")

    @staticmethod
    def _write_yaml_snapshot():
        path = MediaMTXClient._yaml_path
        temp_path = path.with_name(path.name + ".tmp")
        backup_path = path.with_name(path.name + ".bak")
        if path.exists():
            backup_temp = backup_path.with_name(backup_path.name + ".tmp")
            backup_temp.write_bytes(path.read_bytes())
            backup_temp.replace(backup_path)
        temp_path.write_text(yaml.dump(
            MediaMTXClient._sanitize_config_for_mediamtx(MediaMTXClient._ram_config),
            sort_keys=False,
            allow_unicode=True,
        ))
        temp_path.replace(path)

    async def _queue_save_to_json(self, data: dict):
        async with self._cache_lock:
            MediaMTXClient._ram_internal_users = data.get("users", {})
            MediaMTXClient._is_internal_users_dirty = True
            task = MediaMTXClient._json_save_task
            if task and not task.done():
                task.cancel()
            MediaMTXClient._json_save_task = asyncio.create_task(self._delayed_json_save())

    async def _delayed_json_save(self):
        try:
            await asyncio.sleep(MediaMTXClient._save_debounce_seconds)
            async with MediaMTXClient._cache_lock:
                self._write_internal_users_snapshot()
                MediaMTXClient._is_internal_users_dirty = False
        except asyncio.CancelledError:
            raise
        except OSError as exc:
            print(f"[Error] Failed to persist {MediaMTXClient._internalUsers}: {exc}")

    @staticmethod
    def _write_internal_users_snapshot():
        path = MediaMTXClient._internalUsers
        temp_path = path.with_name(path.name + ".tmp")
        temp_path.write_text(json.dumps(
            {"version": 1, "users": MediaMTXClient._ram_internal_users},
            indent=2,
            ensure_ascii=False,
        ))
        temp_path.replace(path)

    @classmethod
    def force_flush_internal_users_sync(cls):
        if cls._json_save_task and not cls._json_save_task.done():
            cls._json_save_task.cancel()
        if cls._is_internal_users_dirty:
            try:
                cls._write_internal_users_snapshot()
                cls._is_internal_users_dirty = False
            except OSError as exc:
                print(f"[Error] Failed final persist of {cls._internalUsers}: {exc}")

    @classmethod
    def force_flush_sync(cls):
        """Retry pending YAML snapshot persistence during graceful shutdown."""
        if cls._yaml_save_task and not cls._yaml_save_task.done():
            cls._yaml_save_task.cancel()
        if cls._is_dirty:
            try:
                cls._write_yaml_snapshot()
                cls._is_dirty = False
            except OSError as exc:
                print(f"[Error] Failed final persist of {cls._yaml_path}: {exc}")

    # --- Server ---

    def _parse_started_to_seconds(self, started_str: str) -> int:
        if not started_str:
            return 0
        try:
            clean_str = started_str.replace("Z", "+00:00")
            start_dt = datetime.fromisoformat(clean_str)
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)
            diff_seconds = int((datetime.now(timezone.utc) - start_dt).total_seconds())
            return max(diff_seconds, 0)
        except Exception as e:
            print(f"Gagal memparsing started time '{started_str}': {e}")
            return 0

    async def get_server_health(self):
        return {"connected": bool(MediaMTXClient._info.get("connected", False)), **MediaMTXClient._info}

    async def _cekMediamtxHealth(self):
        """Poll MediaMTX independently from frontend requests."""
        print("[Info] Background health check MediaMTX dimulai...", flush=True)
        while True:
            try:
                response = await self.client.get(
                    f"{self.base_url}/info",
                    headers={"Cache-Control": "no-cache"}
                )
                response.raise_for_status()
                info = response.json()
                started = info.get("started")

                restarted = (
                    MediaMTXClient._health_started is not None
                    and started != MediaMTXClient._health_started
                )

                MediaMTXClient._health_started = started

                MediaMTXClient._info.clear()
                MediaMTXClient._info.update({
                    "connected": True,
                    "restarted": restarted,
                    "version": info.get("version", "unknown"),
                    "started": started,
                })

                if started and (
                    not MediaMTXClient._has_reconciled_internal_users
                    or started != MediaMTXClient._last_restore_started
                ):
                    try:
                        await self.merge_server_internal_users()
                        await self._restore_after_restart()
                    except Exception as exc:
                        print(f"[Error] MediaMTX reconciliation failed; retrying next poll: {exc}", flush=True)
                    else:
                        MediaMTXClient._last_restore_started = started
                        MediaMTXClient._has_reconciled_internal_users = True

            except Exception as exc:
                MediaMTXClient._info.clear()
                MediaMTXClient._info.update({
                    "connected": False,
                    "restarted": False,
                    "version": "unknown",
                    "started": None
                })
                print(f"[Warning] Health check MediaMTX gagal atau server offline: {exc}", flush=True)
            await asyncio.sleep(5)

    async def _restore_after_restart(self):
        if MediaMTXClient._restoring_after_restart:
            return
        MediaMTXClient._restoring_after_restart = True
        try:
            cached = dict(MediaMTXClient._ram_config)
            paths_data = cached.pop("paths", {})
            cached.pop("authInternalUsers", None)
            path_defaults = cached.pop("pathDefaults", None)
            if cached:
                await self.patch_server_config(cached, persist=False)

            if isinstance(paths_data, dict):
                for path_name, path_config in paths_data.items():
                    if path_config is None:
                        path_config = {}
                    if not isinstance(path_config, dict):
                        raise ValueError(f"Invalid cached path config for {path_name!r}")

                    encoded_name = quote(path_name, safe="")
                    check_res = await self.client.get(f"{self.base_url}/config/paths/get/{encoded_name}")
                    if check_res.status_code == 200:
                        res = await self.client.patch(
                            f"{self.base_url}/config/paths/patch/{encoded_name}",
                            json=path_config,
                        )
                    elif check_res.status_code == 404:
                        res = await self.client.post(
                            f"{self.base_url}/config/paths/add/{encoded_name}",
                            json=path_config,
                        )
                    else:
                        check_res.raise_for_status()
                        raise httpx.HTTPStatusError(
                            "Unexpected path lookup response", request=check_res.request, response=check_res
                        )
                    res.raise_for_status()

            if isinstance(path_defaults, dict):
                response = await self.client.patch(
                    f"{self.base_url}/config/path-defaults/patch", json=path_defaults
                )
                response.raise_for_status()

            for username, saved in MediaMTXClient._ram_internal_users.items():
                permissions = saved.get("permissions", [])
                current = (await self.list_internal_users()).get("items", [])
                match = next((item for item in current if item.get("user") == username), None)
                payload = {
                    "user": username,
                    "pass": saved.get("pass", ""),
                    "ips": saved.get("ips", []),
                    "permissions": permissions,
                }
                if match and match.get("id"):
                    response = await self.client.patch(f"{self.base_url}/config/internal-users/patch/{match['id']}", json=payload)
                else:
                    response = await self.client.post(f"{self.base_url}/config/internal-users/add", json=payload)
                response.raise_for_status()

        except Exception as exc:
            print(f"[Error] MediaMTX reconciliation failed; will retry: {exc}", flush=True)
            raise
        finally:
            MediaMTXClient._restoring_after_restart = False

    async def get_server_config(self):
        r = await self.client.get(f"{self.base_url}/config/global/get")
        r.raise_for_status()
        j = r.json()
        return j

    async def list_internal_users(self):
        r = await self.client.get(f"{self.base_url}/config/internal-users/list")
        r.raise_for_status()
        return r.json()

    async def create_internal_user(self, user: str, password: str, permissions: list[dict], ips: list[str] | None = None):
        ips = ips or []
        payload = {"user": user, "pass": password, "ips": ips, "permissions": permissions}
        MediaMTXClient._ram_internal_users[user] = {"pass": password, "ips": ips, "permissions": permissions}
        await self._queue_save_to_json({"users": MediaMTXClient._ram_internal_users})
        existing = (await self.list_internal_users()).get("items", [])
        match = next((item for item in existing if item.get("user") == user), None)
        if match and match.get("id"):
            r = await self.client.patch(
                f"{self.base_url}/config/internal-users/patch/{match['id']}",
                json=payload,
            )
        else:
            r = await self.client.post(f"{self.base_url}/config/internal-users/add", json=payload)
        r.raise_for_status()
        return r.json()

    async def _resolve_user_id(self, username: str) -> str | None:
        """Refresh server list and return the current ID for a stable username."""
        items = (await self.list_internal_users()).get("items", [])
        match = next((item for item in items if item.get("user") == username), None)
        return match.get("id") if match else None

    async def update_internal_user(self, username: str, user: str, password: str | None, permissions: list[dict], ips: list[str] | None = None):
        current_id = await self._resolve_user_id(username)
        if not current_id:
            raise HTTPException(404, f"Internal user {username!r} not found; user list refreshed")
        existing = (await self.list_internal_users()).get("items", [])
        previous = next((item for item in existing if item.get("id") == current_id), None)
        previous_user = previous.get("user") if previous else None
        saved_user = MediaMTXClient._ram_internal_users.get(previous_user or username, {})
        ips = ips if ips is not None else (previous.get("ips") if previous else saved_user.get("ips", []))
        payload = {"user": user, "ips": ips, "permissions": permissions}
        if password:
            payload["pass"] = password

        saved_password = password or saved_user.get("pass", "")
        if previous_user and previous_user != user:
            MediaMTXClient._ram_internal_users.pop(previous_user, None)
        MediaMTXClient._ram_internal_users[user] = {"pass": saved_password, "ips": ips, "permissions": permissions}
        await self._queue_save_to_json({"users": MediaMTXClient._ram_internal_users})

        for attempt in range(2):
            r = await self.client.patch(f"{self.base_url}/config/internal-users/patch/{current_id}", json=payload)
            if r.status_code == 404 and attempt == 0:
                current_id = await self._resolve_user_id(username)
                if not current_id:
                    raise HTTPException(404, f"Internal user {username!r} no longer exists; user list refreshed")
                continue
            if r.status_code == 404:
                raise HTTPException(404, f"Internal user {username!r} changed during update; user list refreshed")
            r.raise_for_status()
            break
        return r.json()

    async def delete_internal_user(self, username: str):
        MediaMTXClient._ram_internal_users.pop(username, None)
        await self._queue_save_to_json({"users": MediaMTXClient._ram_internal_users})
        current_id = await self._resolve_user_id(username)
        if not current_id:
            raise HTTPException(404, f"Internal user {username!r} not found; user list refreshed")
        existing = (await self.list_internal_users()).get("items", [])
        previous = next((item for item in existing if item.get("id") == current_id), None)

        for attempt in range(2):
            r = await self.client.delete(f"{self.base_url}/config/internal-users/delete/{current_id}")
            if r.status_code == 404 and attempt == 0:
                current_id = await self._resolve_user_id(username)
                if not current_id:
                    raise HTTPException(404, f"Internal user {username!r} no longer exists; user list refreshed")
                continue
            if r.status_code == 404:
                raise HTTPException(404, f"Internal user {username!r} changed during delete; user list refreshed")
            r.raise_for_status()
            break

    async def patch_server_config(self, payload, persist=True):
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

            if persist:
                await self._queue_save_to_yaml(cleaned_payload)

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
            return r.json()
        except httpx.HTTPStatusError as exc:
            print(f"HTTP Error from MediaMTX: {exc.response.text}")
            raise HTTPException(
                status_code=exc.response.status_code,
                detail=exc.response.text
            )

    # --- Paths ---

    async def list_paths(self):
        items = []
        page = 0

        while True:
            r = await self.client.get(
                f"{self.base_url}/config/paths/list",
                params={"page": page, "itemsPerPage": 100},
            )
            r.raise_for_status()
            data = r.json()
            page_items = data.get("items", []) if isinstance(data, dict) else []
            if not page_items:
                break

            items.extend(page_items)
            page += 1

        return {"items": [_mask_path_config(item) for item in items]}

    async def create_path(self, name, source, source_on_demand, **kwargs):
        data = {}
        if source:
            data["source"] = source


            if source_on_demand is not None:
                data["sourceOnDemand"] = source_on_demand
        elif kwargs.get("source_redirect"):
            data["source"] = "redirect"

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
        await self._queue_save_to_yaml(data, path_name=name)
        r = await self.client.post(f"{self.base_url}/config/paths/add/{quote(name, safe='')}", json=data)
        r.raise_for_status()
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
        await self._queue_save_to_yaml(mapped, path_name=name)
        r = await self.client.patch(
            f"{self.base_url}/config/paths/patch/{quote(name, safe='')}",
            json=mapped,
        )
        if r.status_code == 404:
            raise HTTPException(404, "Path not found")
        r.raise_for_status()
        return r.json()

    async def delete_path(self, name):
        await self._queue_save_to_yaml({}, delete_path=name)
        r = await self.client.delete(f"{self.base_url}/config/paths/delete/{quote(name, safe='')}")
        if r.status_code == 404:
            raise HTTPException(404, "Path not found")
        r.raise_for_status()

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
            "readers": self._count_path_readers(data),
            "bytes_received": data.get("bytesReceived", 0),
            "bytes_sent": data.get("bytesSent", 0)
        }

    @staticmethod
    def _count_path_readers(data):
        protocol_reader_count = sum(
            len(data[key])
            for key in _PROTOCOL_READER_KEYS
            if isinstance(data.get(key), list)
        )
        if protocol_reader_count:
            return protocol_reader_count

        readers = data.get("readers")
        return len(readers) if isinstance(readers, list) else 0

    async def get_stream_viewers(self, name):
        encoded_name = quote(name, safe="")
        response = await self.client.get(
            f"{self.base_url}/paths/get/{encoded_name}",
            timeout=3.0,
        )
        if response.status_code == 404:
            history = MediaMTXClient._viewer_history.setdefault(name, deque(maxlen=60))
            history.append(0)
            return {
                "viewer_count": 0,
                "status": "inactive",
                "viewer_history": list(history),
            }

        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("MediaMTX returned an invalid path response")

        viewer_count = self._count_path_readers(data)
        history = MediaMTXClient._viewer_history.setdefault(name, deque(maxlen=60))
        history.append(viewer_count)
        return {
            "viewer_count": viewer_count,
            "status": "active" if data.get("ready") is True else "inactive",
            "viewer_history": list(history),
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

                    continue
                r.raise_for_status()
                data = r.json()
                items = data.get("items", []) or []
                for item in items:
                    normalized = self._normalize_session(item, proto)
                    if normalized:
                        all_sessions.append(normalized)
            except httpx.HTTPError:

                continue

        return {"items": all_sessions}

    def _normalize_session(self, item, proto):
        """Normalize session/connection item from any protocol to common schema."""


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
        await self._queue_save_to_yaml({"pathDefaults": payload})
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

    async def read_log_file(self, path, lines=100):
        return {"lines": [], "error": "Log reading not implemented in MediaMTX API"}
