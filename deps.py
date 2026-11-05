from functools import lru_cache
from config import settings
from mediamtx_client import MediaMTXClient


def get_mediamtx_client():
    return MediaMTXClient()
