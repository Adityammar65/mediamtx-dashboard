from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Query, Body, Response, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
import re
import asyncio
from datetime import datetime, timedelta
import jwt
import httpx
import secrets

from config import settings
from deps import get_mediamtx_client
from mediamtx_client import MediaMTXClient
from responses import StandardResponse
from schemas import PathCreateRequest, PathPatchRequest
from system_monitor import get_system_monitor

@asynccontextmanager
async def lifespan(app: FastAPI):
    client = get_mediamtx_client()
    health_task = asyncio.create_task(client._cekMediamtxHealth())
    yield
    health_task.cancel()
    MediaMTXClient.force_flush_sync()
    MediaMTXClient.force_flush_internal_users_sync()
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


def create_access_token(data: dict):
    """Create a JWT access token."""
    expire = datetime.utcnow() + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    to_encode = {**data, "exp": expire}
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET, algorithm="HS256")
    return encoded_jwt


def decode_access_token(token: str) -> dict:
    """Decode and validate a JWT access token."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


def is_api_path(path: str) -> bool:
    """Check if path is an API path that requires authentication."""
    return path.startswith("/api/") and not path.startswith("/api/login")

def clean_journalctl_log(raw: str):
    parsed_logs = []
    systemd_line_pattern = re.compile(r'^([A-Za-z]{3}\s+\d+\s+\d{2}:\d{2}:\d{2})\s+\S+\s+[^:]+:\s+(.*)$')
    go_log_pattern = re.compile(r'^(\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2})\s+([A-Z]+)\s+(.*)$')
    for line in raw.splitlines():
        if not line.strip():
            continue

        sys_match = systemd_line_pattern.match(line)
        if sys_match:
            sys_timestamp, inner_content = sys_match.groups()

            go_match = go_log_pattern.match(inner_content)
            if go_match:
                ts, level, msg = go_match.groups()
                parsed_logs.append({
                    "timestamp": ts,
                    "level": level,
                    "message": msg
                })
            else:
                parsed_logs.append({
                    "timestamp": sys_timestamp,
                    "level": "INF",
                    "message": inner_content
                })
        else:
            parsed_logs.append({
                "timestamp": "-",
                "level": "INF",
                "message": line.strip()
            })

    return parsed_logs

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Middleware to require JWT authentication for all API endpoints."""
    if is_api_path(request.url.path):
        token = request.cookies.get("access_token")
        if not token:
            return JSONResponse(
                status_code=401,
                content={"detail": "Not authenticated"},
            )

        try:
            decode_access_token(token)
        except HTTPException as e:
            return JSONResponse(
                status_code=401,
                content={"detail": e.detail},
            )
        except Exception:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid authentication credentials"},
            )

    response = await call_next(request)
    return response


@app.post("/api/login")
async def login(response: Response, username: str = Body(...), password: str = Body(...)):
    """Login endpoint to authenticate user and create JWT token."""
    if username != settings.AUTH_USERNAME or password != settings.AUTH_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not settings.JWT_SECRET:
        raise HTTPException(status_code=500, detail="JWT_SECRET not configured")

    token = create_access_token({"sub": username})


    cookie_kwargs = {
        "key": "access_token",
        "value": token,
        "max_age": settings.JWT_EXPIRE_MINUTES * 60,
        "httponly": True,
        "samesite": "Lax",
    }

    if settings.JWT_SECURE_COOKIE:
        cookie_kwargs["secure"] = True

    response.set_cookie(**cookie_kwargs)

    return StandardResponse.success({
        "token": token,
        "expires_in": settings.JWT_EXPIRE_MINUTES * 60
    }, "Login successful")


@app.post("/api/logout")
async def logout(response: Response):
    """Logout endpoint to clear JWT cookie."""
    response.delete_cookie("access_token")
    return StandardResponse.success(None, "Logged out successfully")


@app.get("/api/internal-users")
async def list_internal_users(client: MediaMTXClient = Depends(get_mediamtx_client)):
    data = await client.list_internal_users()
    return StandardResponse.success(data.get("items", []), "Internal users retrieved")


@app.post("/api/internal-users")
async def create_internal_user(payload: dict = Body(...), client: MediaMTXClient = Depends(get_mediamtx_client)):
    raw_user = payload.get("user")
    raw_password = payload.get("password")
    if not isinstance(raw_user, str) or not raw_user.strip():
        raise HTTPException(400, "user must be a non-blank string")
    if not isinstance(raw_password, str) or not raw_password.strip():
        raise HTTPException(400, "password must be a non-blank string")
    user = raw_user.strip()
    password = raw_password
    permissions = payload.get("permissions", [])
    if not isinstance(permissions, list) or not permissions:
        raise HTTPException(400, "permissions are required")
    if any(not isinstance(permission, dict) or not permission.get("action") or not isinstance(permission.get("path"), str) for permission in permissions):
        raise HTTPException(400, "Each permission requires action and path")
    ips = payload.get("ips", [])
    if not isinstance(ips, list) or any(not isinstance(ip, str) for ip in ips):
        raise HTTPException(400, "ips must be a list of strings")
    data = await client.create_internal_user(user, password, permissions, ips)
    return StandardResponse.success(data, "Internal user created")


@app.patch("/api/internal-users/{username:path}")
async def update_internal_user(username: str, payload: dict = Body(...), client: MediaMTXClient = Depends(get_mediamtx_client)):
    raw_user = payload.get("user")
    if not isinstance(raw_user, str) or not raw_user.strip():
        raise HTTPException(400, "user must be a non-blank string")
    user = raw_user.strip()
    permissions = payload.get("permissions", [])
    if not isinstance(permissions, list) or not permissions:
        raise HTTPException(400, "permissions are required")
    raw_password = payload.get("password")
    if raw_password is not None and not isinstance(raw_password, str):
        raise HTTPException(400, "password must be a string when provided")
    password = raw_password.strip() if isinstance(raw_password, str) and raw_password.strip() else None
    ips = payload.get("ips")
    if ips is not None and (not isinstance(ips, list) or any(not isinstance(ip, str) for ip in ips)):
        raise HTTPException(400, "ips must be a list of strings")
    data = await client.update_internal_user(username, user, password, permissions, ips)
    return StandardResponse.success(data, "Internal user updated")


@app.delete("/api/internal-users/{username:path}")
async def delete_internal_user(username: str, client: MediaMTXClient = Depends(get_mediamtx_client)):
    await client.delete_internal_user(username)
    return StandardResponse.success(None, "Internal user deleted")


@app.get("/api/server/health")
async def server_health(client: MediaMTXClient = Depends(get_mediamtx_client)):
    data = await client.get_server_health()
    return StandardResponse.success(data, "MediaMTX health status")


@app.get("/api/server/config")
async def server_config(client: MediaMTXClient = Depends(get_mediamtx_client)):
    data = await client.get_server_config()
    return StandardResponse.success(data, "MediaMTX configuration")


@app.get("/api/server/public-address")
async def server_public_address():
    return StandardResponse.success(
        {"host": settings.MEDIAMTX_PUBLIC_HOST.strip()},
        "MediaMTX public address",
    )


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
        run_on_init=payload.run_on_init,
        run_on_init_restart=payload.run_on_init_restart,
        run_on_available=payload.run_on_available,
        run_on_available_restart=payload.run_on_available_restart,
        forward=[item.model_dump(exclude_none=True) for item in payload.forward],
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


@app.get("/api/streams/{name:path}/viewers")
async def stream_viewers(name: str, client: MediaMTXClient = Depends(get_mediamtx_client)):
    try:
        data = await client.get_stream_viewers(name)
    except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as exc:
        print(f"[Warning] MediaMTX viewer count unavailable ({type(exc).__name__})")
        data = {"viewer_count": 0, "status": "unavailable"}
    return StandardResponse.success(data, "Stream viewer count")


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


            raw_name = stream.get("streamId") or stream.get("name")
            if not raw_name:
                continue

            full_name = f"{app_prefix}/{raw_name}" if app_prefix else raw_name

            source = stream.get("streamUrl")
            source_on_demand = bool(stream.get("autoStartStopEnabled", True))


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
    lines: int = Query(10, ge=1, le=5000)
):
    base = str(settings.MEDIAMTX_AGENT_URL).rstrip("/")
    target_url = f"{base}/logs?lines={lines}"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(target_url, timeout=10.0)
            if response.status_code != 200:
                return JSONResponse(
                    status_code=response.status_code,
                    content={"success": False, "message": "Gagal mengambil log dari Agent"}
                )
            data = response.json()
            agent_data= data.get("logs", "")
            cleaned_data = clean_journalctl_log(agent_data)

            return StandardResponse.success(cleaned_data, "Logs retrieved")

    except httpx.RequestError as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": f"Gagal terhubung ke MediaMTX Agent: {str(e)}"}
        )

# -- Agent Routes --
@app.post("/api/action/{q}")
async def service(q: str, password: str = Body(..., embed=True)):
    if q not in ["start", "stop", "restart"]:
        return JSONResponse(
            status_code=400,
            content={"success": False, "message": "Invalid action"}
        )
    if not secrets.compare_digest(
        password.encode("utf-8"), settings.AUTH_PASSWORD.encode("utf-8")
    ):
        return JSONResponse(
            status_code=403,
            content={"success": False, "message": "Invalid password"}
        )

    base = str(settings.MEDIAMTX_AGENT_URL).rstrip("/")
    target_url = f"{base}/service?action={q}"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(target_url, timeout=10.0)
            agent_data = response.json()
            return JSONResponse(
                status_code=response.status_code,
                content={
                    "success": response.status_code == 200,
                    "message": agent_data.get("message", "Berhasil mengeksekusi perintah."),
                    "data": agent_data.get("data", "")
                }
            )
    except httpx.RequestError as e:
            return JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "message": f"Gagal terhubung ke MediaMTX Agent: {str(e)}"
                }
            )

# --- FRONTEND ---

@app.get("/")
async def root(request: Request):
    token = request.cookies.get("access_token")
    if not token:
        return RedirectResponse(url="/login", status_code=303)

    try:
        decode_access_token(token)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=303)

    return FileResponse("static/index.html")


@app.get("/login", include_in_schema=False)
async def login_page():
    return FileResponse("static/login.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.API_HOST, port=settings.API_PORT)
