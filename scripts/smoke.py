"""Start and stop the assembled JHOC application without external services."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from jhoc.entrypoint import create_application


app = create_application()
health = app.start()
print(f"JHOC smoke: running={health.running} origin={health.origin_state} modules={health.module_count} legacy={health.legacy_runtime_connected}")
app.stop()
