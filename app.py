from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Query, Body
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import os
import asyncio

from config import settings
from deps import get_mediamtx_client
from mediamtx_client import MediaMTXClient
from responses import StandardResponse
from schemas import PathCreateRequest, PathPatchRequest
from system_monitor import get_system_monitor


def read_log_file(path: str, lines: int = 100):
    """Read the last N lines from a log file."""
    try:
        if not os.path.exists(path):
            return {"lines": [], "error": f"Log file not found: {path}"}

        with open(path, 'r') as f:
            all_lines = f.readlines()

        # Get the last N lines
        last_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines

        # Parse log lines (assuming JSON format or standard log format)
        parsed_lines = []
        for line in last_lines:
            line = line.strip()
            if not line:
                continue
            try:
                # Try to parse as JSON (MediaMTX structured logs)
                import json
                log_entry = json.loads(line)
                # Parse timestamp into a human-readable format if possible
                raw_ts = log_entry.get("timestamp", log_entry.get("time", ""))
                formatted_ts = raw_ts
                if raw_ts:
                    try:
                        from datetime import datetime
                        # Parse ISO8601 string (e.g. 2026-10-28T08:49:59.272353675Z)
                        dt = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
                        formatted_ts = dt.strftime("%Y-%m-%d %H:%M:%S")
                    except Exception:
                        pass

                parsed_lines.append({
                    "timestamp": formatted_ts,
                    "level": log_entry.get("level", ""),
                    "message": log_entry.get("message", log_entry.get("msg", ""))
                })
            except json.JSONDecodeError:
                # Fallback: treat as plain text
                parsed_lines.append({
                    "timestamp": "",
                    "level": "",
                    "message": line
                })

        return {"lines": parsed_lines, "error": None}
    except Exception as e:
        return {"lines": [], "error": str(e)}


async def clean_old_logs(max_size_mb: int = 5, max_lines: int = 5000):
    """Background task untuk membersihkan file log jika sudah terlalu besar atau terlalu banyak baris."""
    log_path = settings.LOG_FILE_PATH
    while True:
        try:
            if os.path.exists(log_path):
                # Cek ukuran file (MB)
                file_size_mb = os.path.getsize(log_path) / (1024 * 1024)
                with open(log_path, 'r') as f:
                    lines = f.readlines()

                if file_size_mb > max_size_mb or len(lines) > max_lines:
                    # Ambil hanya N baris terakhir (misal 2000 baris terbaru)
                    keep_lines = lines[-2000:]
                    with open(log_path, 'w') as f:
                        f.writelines(keep_lines)
                    print(f"[Info] Log dibersihkan. Ukuran sebelumnya: {file_size_mb:.2f}MB, baris: {len(lines)}")
        except Exception as e:
            print(f"[Warning] Gagal membersihkan log: {e}")

        # Cek setiap 6 jam sekali
        await asyncio.sleep(6 * 3600)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Jalankan background task pembersih log
    clean_task = asyncio.create_task(clean_old_logs())
    yield
    clean_task.cancel()
    MediaMTXClient.force_flush_sync()
    client = get_mediamtx_client()
    await client.close()
    monitor = get_system_monitor()
    await monitor.close()


app = FastAPI(title="MediaMTX Dashboard", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")


# --- SERVER ROUTES ---

@app.get("/api/server/health")
async def server_health(client: MediaMTXClient = Depends(get_mediamtx_client)):
    data = await client.get_server_health()
    return StandardResponse.success(data, "MediaMTX health status")


@app.get("/api/server/config")
async def server_config(client: MediaMTXClient = Depends(get_mediamtx_client)):
    data = await client.get_server_config()
    return StandardResponse.success(data, "MediaMTX configuration")


@app.patch("/api/server/config")
async def patch_server_config(
    payload: dict, client: MediaMTXClient = Depends(get_mediamtx_client)
):
    data = await client.patch_server_config(payload)
    return StandardResponse.success(data, "Configuration updated")


# --- PATHS ROUTES ---

@app.get("/api/paths")
async def list_paths(client: MediaMTXClient = Depends(get_mediamtx_client)):
    data = await client.list_paths()
    return StandardResponse.success(data, "Paths listed")


@app.post("/api/paths")
async def create_path(
    payload: PathCreateRequest, client: MediaMTXClient = Depends(get_mediamtx_client)
):
    data = await client.create_path(
        name=payload.name,
        source=payload.source,
        source_on_demand=payload.source_on_demand,
        source_on_demand_start_timeout=payload.source_on_demand_start_timeout,
        source_on_demand_close_after=payload.source_on_demand_close_after,
        max_readers=payload.max_readers,
        fallback=payload.fallback,
        source_redirect=payload.source_redirect,
    )
    return StandardResponse.success(data, "Path created")


@app.get("/api/paths/{name:path}")
async def get_path(name: str, client: MediaMTXClient = Depends(get_mediamtx_client)):
    data = await client.get_path(name)
    return StandardResponse.success(data, "Path details")


@app.patch("/api/paths/{name:path}")
async def update_path(
    name: str, payload: PathPatchRequest, client: MediaMTXClient = Depends(get_mediamtx_client)
):
    # Convert to dict, excluding None values
    payload_dict = payload.model_dump(exclude_none=True)
    data = await client.update_path(name, payload_dict)
    return StandardResponse.success(data, "Path updated")


@app.delete("/api/paths/{name:path}")
async def delete_path(name: str, client: MediaMTXClient = Depends(get_mediamtx_client)):
    await client.delete_path(name)
    return StandardResponse.success(None, "Path deleted")


# --- STREAMS ROUTES ---

@app.get("/api/streams")
async def list_streams(client: MediaMTXClient = Depends(get_mediamtx_client)):
    data = await client.list_streams()
    return StandardResponse.success(data, "Streams listed")


@app.get("/api/streams/summary")
async def streams_summary(client: MediaMTXClient = Depends(get_mediamtx_client)):
    data = await client.get_streams_summary()
    return StandardResponse.success(data, "Streams summary")


@app.get("/api/streams/{name:path}")
async def stream_detail(name: str, client: MediaMTXClient = Depends(get_mediamtx_client)):
    data = await client.get_stream_detail(name)
    return StandardResponse.success(data, "Stream details")


@app.post("/api/import/ams")
async def import_ams_streams(
    payload: dict = Body(...),
    client: MediaMTXClient = Depends(get_mediamtx_client)
):
    """
    Import streams from Ant Media Server export format.
    AMS format has 'app' (prefix) and 'streams' list.
    """
    app_prefix = payload.get("app", "").strip()
    streams = payload.get("streams", [])

    results = {"total": len(streams), "imported": 0, "failed": 0, "errors": []}

    for stream in streams:
        try:
            # Mapping AMS -> MediaMTX
            # Use 'app' as prefix if available to mimic 'applications' grouping
            raw_name = stream.get("streamId") or stream.get("name")
            if not raw_name:
                continue

            full_name = f"{app_prefix}/{raw_name}" if app_prefix else raw_name

            source = stream.get("streamUrl")
            source_on_demand = bool(stream.get("autoStartStopEnabled", True))

            # MediaMTX add path
            await client.create_path(
                name=full_name,
                source=source,
                source_on_demand=source_on_demand
            )
            results["imported"] += 1
        except Exception as e:
            results["failed"] += 1
            results["errors"].append(f"{raw_name}: {str(e)}")

    return StandardResponse.success(results, f"Imported {results['imported']} streams")

@app.get("/api/sessions")
async def list_sessions(client: MediaMTXClient = Depends(get_mediamtx_client)):
    """Return normalized sessions from all protocols."""
    data = await client.list_all_sessions()
    return StandardResponse.success(data, "Sessions listed")


@app.get("/api/sessions/rtsp")
async def list_rtsp_sessions(client: MediaMTXClient = Depends(get_mediamtx_client)):
    """Legacy endpoint for RTSP sessions only."""
    data = await client.list_sessions()
    return StandardResponse.success(data, "RTSP sessions listed")


@app.post(
    "/api/sessions/{type}/{id}/kick"
)
async def kick_session(
    type: str, id: str, client: MediaMTXClient = Depends(get_mediamtx_client)
):
    data = await client.kick_session(type, id)
    return StandardResponse.success(data, "Session kicked")


# --- PATH DEFAULTS ROUTES ---

@app.get("/api/config/path-defaults")
async def get_path_defaults(client: MediaMTXClient = Depends(get_mediamtx_client)):
    data = await client.get_path_defaults()
    return StandardResponse.success(data, "Path defaults retrieved")


@app.patch("/api/config/path-defaults")
async def patch_path_defaults(
    payload: dict, client: MediaMTXClient = Depends(get_mediamtx_client)
):
    data = await client.patch_path_defaults(payload)
    return StandardResponse.success(data, "Path defaults updated")


# --- RUNTIME ROUTES ---

@app.get("/api/runtime/hls/connections")
async def hls_connections(client: MediaMTXClient = Depends(get_mediamtx_client)):
    data = await client.list_hls_connections()
    return StandardResponse.success(data, "HLS connections listed")


@app.get("/api/runtime/rtsp/connections")
async def rtsp_connections(client: MediaMTXClient = Depends(get_mediamtx_client)):
    data = await client.list_rtsp_connections()
    return StandardResponse.success(data, "RTSP connections listed")


@app.get("/api/runtime/rtmp/connections")
async def rtmp_connections(client: MediaMTXClient = Depends(get_mediamtx_client)):
    data = await client.list_rtmp_connections()
    return StandardResponse.success(data, "RTMP connections listed")


@app.get("/api/runtime/hls/sessions")
async def hls_sessions(client: MediaMTXClient = Depends(get_mediamtx_client)):
    data = await client.list_hls_sessions()
    return StandardResponse.success(data, "HLS sessions listed")


@app.get("/api/runtime/rtsp/sessions")
async def rtsp_sessions(client: MediaMTXClient = Depends(get_mediamtx_client)):
    data = await client.list_rtsp_sessions()
    return StandardResponse.success(data, "RTSP sessions listed")


@app.get("/api/runtime/rtmp/sessions")
async def rtmp_sessions(client: MediaMTXClient = Depends(get_mediamtx_client)):
    data = await client.list_rtmp_sessions()
    return StandardResponse.success(data, "RTMP sessions listed")


@app.get("/api/metrics")
async def get_metrics(client: MediaMTXClient = Depends(get_mediamtx_client)):
    data = await client.get_metrics()
    return StandardResponse.success({"metrics": data}, "Metrics retrieved")


# --- SYSTEM MONITOR ROUTES ---

@app.get("/api/system/metrics")
async def get_system_metrics():
    monitor = get_system_monitor()
    data = await monitor.get_system_metrics()
    return StandardResponse.success(data, "System metrics retrieved")


# --- LOGS ROUTES ---

@app.get("/api/logs")
async def read_logs(
    lines: int = Query(100, ge=1, le=5000)
):
    data = read_log_file(settings.LOG_FILE_PATH, lines)
    return StandardResponse.success(data, "Logs retrieved")


# 48-hour safety cutoff in seconds
LOG_SAFETY_CUTOFF_SECONDS = 48 * 60 * 60


def parse_log_timestamp(line):
    """Parse timestamp from a log line. Returns datetime or None if unparseable."""
    try:
        import json
        log_entry = json.loads(line.strip())
        raw_ts = log_entry.get("timestamp", log_entry.get("time", ""))
        if raw_ts:
            from datetime import datetime
            # Parse ISO8601 string (e.g. 2026-10-28T08:49:59.272353675Z)
            return datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
    except Exception:
        pass
    return None


def is_within_safety_window(timestamp):
    """Check if a timestamp is within the 48-hour safety window."""
    if timestamp is None:
        return True  # Protect entries with unparseable/missing timestamps
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    age = (now - timestamp).total_seconds()
    return age < LOG_SAFETY_CUTOFF_SECONDS


def should_delete_entry(timestamp, start=None, end=None):
    """Determine if a log entry should be deleted based on timestamp and optional range."""
    if timestamp is None:
        return False  # Never delete entries with unparseable/missing timestamps
    # Check safety window
    if is_within_safety_window(timestamp):
        return False
    # Check custom range if provided
    if start is not None and timestamp < start:
        return False
    if end is not None and timestamp > end:
        return False
    return True


def filter_log_lines(lines, preset=None, start=None, end=None):
    """Filter log lines, returning (kept_lines, deleted_count).
    
    Presets:
    - 'week': delete entries from 7 days ago up to 48 hours ago
    - 'month': delete entries from 30 days ago up to 48 hours ago
    - None with start/end: custom range
    """
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    
    if preset == 'week':
        start = now - timedelta(days=7)
        end = now - timedelta(seconds=LOG_SAFETY_CUTOFF_SECONDS)
    elif preset == 'month':
        start = now - timedelta(days=30)
        end = now - timedelta(seconds=LOG_SAFETY_CUTOFF_SECONDS)
    
    kept = []
    deleted = 0
    for line in lines:
        ts = parse_log_timestamp(line)
        if should_delete_entry(ts, start, end):
            deleted += 1
        else:
            kept.append(line)
    return kept, deleted


@app.post("/api/logs/delete")
async def delete_logs(
    payload: dict = Body(...)
):
    """Delete log entries based on preset or custom range, respecting 48-hour safety cutoff."""
    log_path = settings.LOG_FILE_PATH
    try:
        if not os.path.exists(log_path):
            return StandardResponse.error(f"Log file not found: {log_path}")
        
        with open(log_path, 'r') as f:
            lines = f.readlines()
        
        preset = payload.get('preset')
        start_str = payload.get('start')
        end_str = payload.get('end')
        
        start = None
        end = None
        if start_str:
            from datetime import datetime
            start = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
        if end_str:
            from datetime import datetime
            end = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
        
        kept_lines, deleted_count = filter_log_lines(lines, preset, start, end)
        
        with open(log_path, 'w') as f:
            f.writelines(kept_lines)
        
        return StandardResponse.success({"deleted_count": deleted_count}, f"Deleted {deleted_count} log entries")
    except Exception as e:
        return StandardResponse.error(f"Failed to delete log entries: {str(e)}")


@app.post("/api/logs/clear")
async def clear_logs():
    """Truncate the configured log file in place (legacy endpoint)."""
    log_path = settings.LOG_FILE_PATH
    try:
        if not os.path.exists(log_path):
            return StandardResponse.error(f"Log file not found: {log_path}")
        # Truncate the file by opening in write mode
        with open(log_path, 'w') as f:
            pass
        return StandardResponse.success(None, "Log file cleared successfully")
    except Exception as e:
        return StandardResponse.error(f"Failed to clear log file: {str(e)}")


async def clean_old_logs(max_size_mb: int = 5, max_lines: int = 5000):
    """Background task to clean log file if too large, respecting 48-hour safety cutoff."""
    log_path = settings.LOG_FILE_PATH
    while True:
        try:
            if os.path.exists(log_path):
                file_size_mb = os.path.getsize(log_path) / (1024 * 1024)
                with open(log_path, 'r') as f:
                    lines = f.readlines()

                if file_size_mb > max_size_mb or len(lines) > max_lines:
                    # Apply safety filter first - never delete entries within 48 hours
                    kept_lines, deleted_count = filter_log_lines(lines)
                    
                    # If still too large after safety filter, keep only the newest entries
                    # but still respect the safety cutoff
                    if len(kept_lines) > max_lines:
                        # We need to keep the newest max_lines entries, but don't remove protected ones
                        # Find the cutoff point that keeps max_lines while preserving safety window
                        # For simplicity, if still too large, keep newest max_lines (which includes protected)
                        kept_lines = kept_lines[-max_lines:]
                        deleted_count = len(lines) - len(kept_lines)
                    
                    with open(log_path, 'w') as f:
                        f.writelines(kept_lines)
                    print(f"[Info] Log cleaned up. Size before: {file_size_mb:.2f}MB, lines before: {len(lines)}, deleted: {deleted_count}")
        except Exception as e:
            print(f"[Warning] Failed to clean log: {e}")

        await asyncio.sleep(6 * 3600)


# --- FRONTEND ---

@app.get("/")
async def root():
    return FileResponse("static/index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.API_HOST, port=settings.API_PORT)
