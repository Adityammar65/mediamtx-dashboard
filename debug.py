import httpx
import json
import asyncio
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit


BASE_URL = "http://mediamtx:9997/v3"

ENDPOINTS = [
    ("Info", "/info"),
    ("Global Config", "/config/global/get"),
    ("Path Configs", "/config/paths/list"),
    ("Active Streams", "/paths/list"),
    ("RTSP Sessions", "/rtsp/sessions/list"),
    ("WebRTC Sessions", "/webrtc/sessions/list"),
]

async def test_endpoints(name):
    print(f"Testing MediaMTX API at: {BASE_URL}\n")
    
    async with httpx.AsyncClient(timeout=5.0) as client:
        encoded_name = quote(name, safe="")
        url = f"{BASE_URL}/paths/get/{encoded_name}"

        r = await client.get(url)
        r.raise_for_status()
        data = r.json()
        print(f"Path: {data}")
        return {
            "name": data.get("name"),
            "ready": data.get("ready"),
            "tracks": data.get("tracks") or [],
            "bytes_received": data.get("bytesReceived", 0),
            "bytes_sent": data.get("bytesSent", 0)
        }

if __name__ == "__main__":
    asyncio.run(test_endpoints("atcs-kota/FMNoto.stream"))
