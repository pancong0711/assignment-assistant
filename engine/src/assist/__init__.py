"""assist — assignment-assistant engine.

来源合并自 _legacy/2603paperDesign 与 _legacy/2601playwright（见 docs/03、07）。
"""

from pathlib import Path

# engine/ 目录（package src/assist → 上3级）
ASSIST_ROOT = Path(__file__).resolve().parents[2]
ASSETS_DIR = ASSIST_ROOT / "assets"

__version__ = "0.1.0"
