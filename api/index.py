import sys
import os

# Add root directory to sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from app.asgi import app

# Export app for Vercel ASGI
__all__ = ["app"]
