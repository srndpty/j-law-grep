import os
import sys
from pathlib import Path

import django

# Ensure the backend package directory is on sys.path so imports like
# `import search` work when running pytest from the repository root.
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.backend.settings")
django.setup()
