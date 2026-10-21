"""Per-process credentials. Never persist or return values to clients."""
import threading
from contextlib import contextmanager
from contextvars import ContextVar

_LOCK = threading.RLock()
_VALUES = {}
_SCOPE = ContextVar("boardscope_credentials", default=None)


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
    scope=_SCOPE.get()
    if scope is not None and scope[0]==board_id:return scope[1].get(key)
    with _LOCK:
        return _VALUES.get(board_id, {}).get(key)


def credential_status(board_id):
    with _LOCK:
        return {key: bool(_VALUES.get(board_id, {}).get(key)) for key in ('ssh_password','uart_password','sudo_password','ssh_private_key','ssh_key_passphrase')}


def clear_credentials():
    with _LOCK:
        _VALUES.clear()


def redact(value):
    if isinstance(value, str):
        with _LOCK:
            values={v for row in _VALUES.values() for v in row.values() if v}
            scope=_SCOPE.get()
            if scope is not None:values.update(v for v in scope[1].values() if v)
            secrets=sorted(values,key=len,reverse=True)
        for secret in secrets:
            value = value.replace(secret, '[REDACTED]')
        return value
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def sudo_secret(board,transport):
    key=(transport+'_password') if board.get('sudo_password_source','login')=='login' else 'sudo_password'
    password=get_secret(board.get('id'),key)
    if not password:
        raise RuntimeError('Sudo password is missing for this session. Enter it in Connect / settings.')
    if any(c in password for c in ('\r','\n')):
        raise RuntimeError('Sudo passwords cannot contain newline characters')
    return password


@contextmanager
def credential_scope(board_id):
    """A run owns a volatile snapshot until cleanup; never serialize this scope."""
    with _LOCK:values=dict(_VALUES.get(board_id,{}))
    token=_SCOPE.set((board_id,values))
    try:yield
    finally:
        _SCOPE.reset(token)
        values.clear()
