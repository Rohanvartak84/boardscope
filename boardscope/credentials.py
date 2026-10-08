"""Per-process credentials. Never persist or return values to clients."""
import threading

_LOCK = threading.RLock()
_VALUES = {}


def set_credentials(board_id, **values):
    with _LOCK:
        current = _VALUES.setdefault(board_id, {})
        for key, value in values.items():
            if value is not None:
                if value:
                    current[key] = value
                else:
                    current.pop(key, None)


def get_secret(board_id, key):
    with _LOCK:
        return _VALUES.get(board_id, {}).get(key)


def credential_status(board_id):
    with _LOCK:
        return {key: bool(_VALUES.get(board_id, {}).get(key)) for key in ('ssh_password','uart_password')}


def clear_credentials():
    with _LOCK:
        _VALUES.clear()


def redact(value):
    if isinstance(value, str):
        with _LOCK:
            secrets = sorted({v for row in _VALUES.values() for v in row.values() if v}, key=len, reverse=True)
        for secret in secrets:
            value = value.replace(secret, '[REDACTED]')
        return value
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value
