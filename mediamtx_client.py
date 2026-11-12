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
from argon2 import PasswordHasher


_PW_HASHER = PasswordHasher()
_INTERNAL_HASH_PREFIXES = ("argon2:", "sha256:")


def _hash_internal_password(password: str) -> str:
    return f"argon2:{_PW_HASHER.hash(password)}"


def _is_internal_password_hashed(value) -> bool:
    return isinstance(value, str) and value.startswith(("argon2:", "sha256:"))


def _prepare_internal_password(value) -> str:
    if _is_internal_password_hashed(value):
        return value
    return _hash_internal_password(value) if value else ""


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
    _yaml_path = Path("mediamtx.yml")
    _internalUsers = Path("internalUsers.json")
    _ram_internal_users = {}
    # _ram_internal_users format (new):
    # { "entry-id-from-mt": { "user": "username", "pass": "...", "ips": [], "permissions": [...] }, ... }
    _info = {"connected": False, "restarted": False, "version": "unknown", "started": None}
    _health_started = None
    _last_restore_started = None
    _restoring_after_restart = False
    _is_dirty = False
    _last_modified = 0.0
    _debounce_seconds = 30.0

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
                saved_entries = data.get("entries")
                if isinstance(saved_entries, list):
                    MediaMTXClient._ram_internal_users = {
                        str(entry["id"]): entry
                        for entry in saved_entries
                        if entry.get("id") is not None
                    }
                else:
                    MediaMTXClient._ram_internal_users = {
                        f"legacy:{username}": {"id": f"legacy:{username}", "user": username, **entry}
                        for username, entry in data.get("users", {}).items()
                    }
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[Warning] Gagal memuat internalUsers.json: {exc}")

    @staticmethod
    def _save_internal_users_cache():
        entries = [e for e in MediaMTXClient._ram_internal_users.values() if e.get("id") is not None]
        payload = {"version": 2, "entries": entries}
        MediaMTXClient._internalUsers.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    @staticmethod
    def _permission_signature(permissions):
        return tuple(sorted((str(p.get("action", "")), str(p.get("path", ""))) for p in permissions or []))

    @classmethod
    def _managed_signature(cls, entry):
        return (
            entry.get("user", ""),
            entry.get("pass"),
            tuple(sorted(entry.get("ips") or [])),
            cls._permission_signature(entry.get("permissions")),
        )

    def _cached_user(self, item):
        saved = MediaMTXClient._ram_internal_users.get(str(item.get("id")), {})
        if not saved:
            saved = next((entry for entry in MediaMTXClient._ram_internal_users.values()
                          if (entry.get("id") is None or str(entry.get("id")).startswith("legacy:")) and entry.get("user") == item.get("user")), {})
        return saved

    @staticmethod
    def _remember_internal_user(item, password=None):
        entry_id = item.get("id")
        if entry_id is None:
            return
        if password is None:
            raise ValueError("password must be provided when caching an internal user")
        previous = MediaMTXClient._ram_internal_users.get(str(entry_id), {})
        MediaMTXClient._ram_internal_users[str(entry_id)] = {
            "id": entry_id,
            "user": item.get("user", previous.get("user", "")),
            "pass": password if password is not None else previous.get("pass", ""),
            "ips": item.get("ips", previous.get("ips", [])),
            "permissions": item.get("permissions", previous.get("permissions", [])),
        }
        MediaMTXClient._save_internal_users_cache()

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


        asyncio.create_task(self._debounce_flush())

    async def _queue_save_to_json(self, data: dict):
        async with self._cache_lock:
            MediaMTXClient._ram_internal_users = {
                str(entry["id"]): entry for entry in data.get("entries", []) if entry.get("id") is not None
            }
            MediaMTXClient._save_internal_users_cache()

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

                age = self._parse_started_to_seconds(started)
                if started and age < 10 and started != MediaMTXClient._last_restore_started:
                    MediaMTXClient._last_restore_started = started
                    await self._restore_after_restart()

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
            cached.pop("pathDefaults", None)
            if cached:
                await self.patch_server_config(cached, persist=False)

            if isinstance(paths_data, dict) and paths_data:
                for path_name, path_config in paths_data.items():
                    if not path_config or not isinstance(path_config, dict):
                        continue

                    try:
                        encoded_name = quote(path_name, safe="")
                        check_res = await self.client.get(f"{self.base_url}/config/paths/get/{encoded_name}")

                        if check_res.status_code == 200:
                            res = await self.client.patch(
                                f"{self.base_url}/config/paths/patch/{encoded_name}",
                                json=path_config
                            )
                        else:
                            res = await self.client.post(
                                f"{self.base_url}/config/paths/add/{encoded_name}",
                                json=path_config
                            )
                        if res.status_code in (200, 201, 204):
                            print(f"[Info] Path '{path_name}' sukses disimpan ke MediaMTX.", flush=True)
                        else:
                            print(f"[Warning] Gagal menyimpan path '{path_name}', status: {res.status_code}, respon: {res.text}", flush=True)

                    except Exception as path_err:
                        print(f"[Error] Terjadi kesalahan saat memulihkan path '{path_name}': {path_err}", flush=True)

            current = (await self.list_internal_users()).get("items", [])
            used_ids = set()
            saved_snapshot = list(MediaMTXClient._ram_internal_users.values())
            seen_signatures = set()
            for saved in saved_snapshot:
                signature = self._managed_signature(saved)
                if signature in seen_signatures:
                    MediaMTXClient._ram_internal_users.pop(str(saved.get("id")), None)
                    continue
                seen_signatures.add(signature)

            saved_snapshot = list(MediaMTXClient._ram_internal_users.values())
            for saved in saved_snapshot:
                username = saved.get("user", "")
                saved_password = saved.get("pass")
                if saved_password is None:
                    continue
                hashed_password = _prepare_internal_password(saved_password)
                payload = {
                    "user": username,
                    "pass": hashed_password,
                    "ips": saved.get("ips") or [],
                    "permissions": saved.get("permissions") or [],
                }
                entry_id = saved.get("id")
                match = next((item for item in current if str(item.get("id")) == str(entry_id)), None)
                if match is None:
                    expected = self._managed_signature({**payload, "pass": hashed_password})
                    match = next((item for item in current if str(item.get("id")) not in used_ids and self._managed_signature({
                        **item,
                        "pass": hashed_password if item.get("pass") == "<redacted>" else item.get("pass"),
                    }) == expected), None)
                if match and match.get("id"):
                    used_ids.add(str(match["id"]))
                    response = await self.client.patch(f"{self.base_url}/config/internal-users/patch/{match['id']}", json=payload)
                    response.raise_for_status()
                    new_id = match["id"]
                else:
                    response = await self.client.post(f"{self.base_url}/config/internal-users/add", json=payload)
                    response.raise_for_status()
                    created = response.json()
                    new_id = created.get("id")
                    if new_id:
                        used_ids.add(str(new_id))
                        current.append({**payload, **created})
                if new_id:
                    MediaMTXClient._ram_internal_users.pop(str(entry_id), None)
                    MediaMTXClient._ram_internal_users[str(new_id)] = {
                        "id": new_id,
                        "user": username,
                        "pass": hashed_password,
                        "ips": payload["ips"],
                        "permissions": payload["permissions"],
                    }
            self._save_internal_users_cache()

        except httpx.HTTPError as exc:
            print(f"[Warning] Gagal restore konfigurasi setelah restart MediaMTX: {exc}")
        finally:
            self._save_internal_users_cache()
            MediaMTXClient._restoring_after_restart = False

    async def get_server_config(self):
        r = await self.client.get(f"{self.base_url}/config/global/get")
        r.raise_for_status()
        j= r.json()
        print(j, flush=True)
        return j

    async def list_internal_users(self):
        r = await self.client.get(f"{self.base_url}/config/internal-users/list")
        r.raise_for_status()
        data = r.json()
        items = data.get("items", []) if isinstance(data, dict) else data
        redacted_items = []
        for item in items or []:
            item = dict(item)
            if isinstance(item.get("pass"), str):
                item["pass"] = "<redacted>"
            redacted_items.append(item)
        return {"items": redacted_items}

    async def _sync_internal_users_to_json(self):
        entries = [
            dict(entry)
            for entry in MediaMTXClient._ram_internal_users.values()
            if entry.get("id") is not None and entry.get("user") and entry.get("pass") is not None
        ]
        await self._queue_save_to_json({"entries": entries})

    async def create_internal_user(self, user: str, password: str, permissions: list[dict], ips: list[str] | None = None):
        hashed_password = _hash_internal_password(password)
        payload = {"user": user, "pass": hashed_password, "ips": ips or [], "permissions": permissions}
        response = await self.client.post(f"{self.base_url}/config/internal-users/add", json=payload)
        response.raise_for_status()
        created = response.json()
        if created.get("id"):
            self._remember_internal_user(created, password=hashed_password)
            await self._sync_internal_users_to_json()
            return created
        return created

    async def update_internal_user(self, user_id: str, user: str, password: str | None, permissions: list[dict], ips: list[str] | None = None):
        previous = next((item for item in (await self.list_internal_users()).get("items", []) if str(item.get("id")) == str(user_id)), None)
        if not previous:
            raise HTTPException(status_code=404, detail="Internal user not found")
        payload = {"user": user, "permissions": permissions}
        hashed_password = _prepare_internal_password(password) if password else None
        if hashed_password:
            payload["pass"] = hashed_password
        if ips is not None:
            payload["ips"] = ips
        r = await self.client.patch(f"{self.base_url}/config/internal-users/patch/{user_id}", json=payload)
        r.raise_for_status()
        cached = self._cached_user(previous)
        saved_password = hashed_password if hashed_password is not None else cached.get("pass")
        entry = {
            **previous,
            "id": previous["id"],
            "user": user,
            "permissions": permissions,
            "ips": ips if ips is not None else previous.get("ips", []),
        }
        if saved_password is not None:
            entry["pass"] = saved_password
            self._remember_internal_user(entry, password=saved_password)
        else:
            MediaMTXClient._ram_internal_users[str(previous["id"])] = entry
        await self._sync_internal_users_to_json()
        return r.json()

    async def delete_internal_user(self, user_id: str):
        existing = (await self.list_internal_users()).get("items", [])
        previous = next((item for item in existing if str(item.get("id")) == str(user_id)), None)
        r = await self.client.delete(f"{self.base_url}/config/internal-users/delete/{user_id}")
        r.raise_for_status()
        self._ram_internal_users.pop(str(user_id), None)
        await self._sync_internal_users_to_json()

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
            if persist:
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
        await self._queue_save_to_yaml(mapped, path_name=name)
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
