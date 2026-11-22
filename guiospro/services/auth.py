"""Hash de contraseñas (bcrypt) y tokens de sesión firmados (itsdangerous)."""

import bcrypt
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from ..settings import get_settings

MIN_PASSWORD_LENGTH = 8
_SALT = "guiosad-session"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:
        return False


def _serializer() -> URLSafeTimedSerializer:
    secret = get_settings().auth_secret_key
    if not secret:
        raise RuntimeError("AUTH_SECRET_KEY no está configurada en .env")
    return URLSafeTimedSerializer(secret, salt=_SALT)


def create_session_token(user_id: int) -> str:
    return _serializer().dumps({"uid": user_id})


def read_session_token(token: str) -> int | None:
    if not token:
        return None
    try:
        data = _serializer().loads(token, max_age=get_settings().auth_session_minutes * 60)
    except (BadSignature, SignatureExpired):
        return None
    uid = data.get("uid") if isinstance(data, dict) else None
    return uid if isinstance(uid, int) else None
