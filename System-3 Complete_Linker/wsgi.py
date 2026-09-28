"""WSGI entry point for production servers (gunicorn): `gunicorn wsgi:app`."""
from app import app  # noqa: F401  (init_app runs migrations + demo seeding on import)
