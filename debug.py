import httpx
import json
import asyncio



BASE_URL = "http://mediamtx:9997/v3"

ENDPOINTS = [
    ("Info", "/info"),
    ("Global Config", "/config/global/get"),
    ("Path Configs", "/config/paths/list"),
    ("Active Streams", "/paths/list"),
    ("RTSP Sessions", "/rtsp/sessions/list"),
    ("WebRTC Sessions", "/webrtc/sessions/list"),
]

async def test_endpoints():
    print(f"Testing MediaMTX API at: {BASE_URL}\n")
    
    async with httpx.AsyncClient(timeout=5.0) as client:
        for name, path in ENDPOINTS:
            url = f"{BASE_URL}{path}"
            print(f"--- {name} ({url}) ---")
            try:
                r = await client.get(url)
                print(f"Status: {r.status_code}")
                if r.status_code == 200:
                    print("Response:")
                    print(json.dumps(r.json(), indent=2))
                else:
                    print(f"Error Body: {r.text}")
            except Exception as e:
                print(f"FAILED to connect: {e}")
            print("\n" + "="*50 + "\n")

if __name__ == "__main__":
    asyncio.run(test_endpoints())
