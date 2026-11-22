"""Carga inicial: catálogo GUIOS desde CSV y usuario administrador opcional.

Uso: ``python -m guiospro.models.seed`` (después de ``alembic upgrade head``).
"""

from ..core.catalog import get_catalog
from ..core.constants import Rol
from ..services.auth import MIN_PASSWORD_LENGTH, hash_password
from ..settings import get_settings
from . import repository as repo
from .session import session_scope


def run() -> None:
    settings = get_settings()
    with session_scope() as session:
        created = repo.seed_catalog(session, get_catalog())
        print(f"Catálogo: {created} factores creados" if created else "Catálogo ya cargado.")
        email = settings.admin_email.strip()
        if email and settings.admin_password:
            if len(settings.admin_password) < MIN_PASSWORD_LENGTH:
                raise SystemExit(f"ADMIN_PASSWORD debe tener al menos {MIN_PASSWORD_LENGTH} caracteres.")
            if repo.get_user_by_email(session, email) is None:
                repo.create_user(
                    session, "Administrador", email, hash_password(settings.admin_password), rol=Rol.ADMIN
                )
                print(f"Administrador creado: {email}")
        else:
            print("ADMIN_EMAIL/ADMIN_PASSWORD vacíos: el primer usuario registrado será admin.")


if __name__ == "__main__":
    run()
