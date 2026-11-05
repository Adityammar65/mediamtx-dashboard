

MOCK_PATHS = {
    "cam-1": {
        "name": "cam-1",
        "source": "rtsp://admin:***@192.168.1.10:554/stream1",
        "source_on_demand": True,
        "source_redirect": "",
        "source_protocols": ["tcp", "udp"],
        "run_on_init": "",
        "run_on_init_restart": False,
        "fallback": "",
    },
    "cam-2": {
        "name": "cam-2",
        "source": "publisher",
        "source_on_demand": False,
        "source_redirect": "",
        "source_protocols": ["tcp", "udp"],
        "run_on_init": "",
        "run_on_init_restart": False,
        "fallback": "",
    },
    "cam-3": {
        "name": "cam-3",
        "source": "rtsp://user:***@192.168.1.11:554/live",
        "source_on_demand": True,
        "source_redirect": "",
        "source_protocols": ["tcp"],
        "run_on_init": "",
        "run_on_init_restart": False,
        "fallback": "cam-1",
    },
}


MOCK_STREAMS = [
    {
        "name": "cam-1",
        "ready": True,
        "tracks": [
            {"codec": "h264", "width": 1920, "height": 1080, "fps": 30},
            {"codec": "opus", "channels": 2, "sample_rate": 48000},
        ],
        "readers": 3,
        "bytes_received": 1024000,
        "bytes_sent": 3072000,
    },
    {
        "name": "cam-2",
        "ready": False,
        "tracks": [],
        "readers": 0,
        "bytes_received": 0,
        "bytes_sent": 0,
    },
    {
        "name": "cam-3",
        "ready": True,
        "tracks": [
            {"codec": "h265", "width": 3840, "height": 2160, "fps": 25},
        ],
        "readers": 1,
        "bytes_received": 2048000,
        "bytes_sent": 2048000,
    },
]


MOCK_SESSIONS = [
    {
        "id": "sess-rtsp-1",
        "type": "rtsp",
        "path": "cam-1",
        "remote_addr": "192.168.1.100:54321",
        "bytes_received": 1024000,
        "bytes_sent": 1024000,
    },
    {
        "id": "sess-webrtc-1",
        "type": "webrtc",
        "path": "cam-1",
        "remote_addr": "192.168.1.101:44321",
        "bytes_received": 0,
        "bytes_sent": 1024000,
    },
    {
        "id": "sess-rtsp-2",
        "type": "rtsp",
        "path": "cam-3",
        "remote_addr": "192.168.1.102:54322",
        "bytes_received": 2048000,
        "bytes_sent": 2048000,
    },
    {
        "id": "sess-hls-1",
        "type": "hls",
        "path": "cam-1",
        "remote_addr": "192.168.1.103:8080",
        "bytes_received": 0,
        "bytes_sent": 1024000,
    },
]


def load_mock_paths() -> dict:
    return {k: v.copy() for k, v in MOCK_PATHS.items()}


def load_mock_streams() -> list:
    return [s.copy() for s in MOCK_STREAMS]


def load_mock_sessions() -> list:
    return [s.copy() for s in MOCK_SESSIONS]
