import os

def getenv_str(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return v if v is not None and v != "" else default

def getenv_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default

def parse_topics(env_value: str) -> list[str]:
    if not env_value:
        return []
    return [t.strip() for t in env_value.split(",") if t.strip()]
