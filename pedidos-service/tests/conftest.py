import os
import sys
import tempfile

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ.pop("REDIS_URL", None)
os.environ.pop("INTERNAL_TOKEN", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
