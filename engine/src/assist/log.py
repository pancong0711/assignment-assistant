"""loguru 统一配置。迁移自 _legacy/2603paperDesign/src/paperdesign/log_config.py（简化）。"""

import sys

from loguru import logger

_sink_installed = False


def setup_logging(verbose: bool = False, log_file: str | None = None) -> None:
    """配置终端 + 可选文件日志；verbose 打 DEBUG。幂等。"""
    global _sink_installed
    if _sink_installed:
        return
    logger.remove()
    level = "DEBUG" if verbose else "INFO"
    logger.add(sys.stderr, level=level, colorize=True,
               format="<level>{time:HH:mm:ss}</level> [{name}] {message}")
    if log_file:
        logger.add(log_file, level=level, rotation="5 MB")
    _sink_installed = True
