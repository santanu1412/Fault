import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
backend_local = os.path.abspath(os.path.join(current_dir, "..", "backend"))
backend_vercel = os.path.abspath(os.path.join(current_dir, "backend"))

if os.path.exists(backend_local):
    sys.path.insert(0, backend_local)
elif os.path.exists(backend_vercel):
    sys.path.insert(0, backend_vercel)

from app.main import app  # noqa: E402
