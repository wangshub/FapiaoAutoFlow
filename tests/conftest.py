import sys
from pathlib import Path

# 确保 src 在路径上(pyproject 的 pythonpath 已配,这里兜底)
SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
