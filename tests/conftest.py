"""
pytest 配置：确保 AEE 项目的模块路径正确。
"""
import sys
from pathlib import Path

# AEE/tests/conftest.py → 向上两级到达 AEE/
_AEE = Path(__file__).parent.parent.resolve()
_ROOT = _AEE.parent  # XIA/

for _p in (_ROOT, _AEE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
