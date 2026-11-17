"""入口包装：让 `python -I mt.py ...` 也能找到 mtbot 包。

  python -I E:\\Reverse\\auto_script\\mt.py --list
  python -I E:\\Reverse\\auto_script\\mt.py --profile daily
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mtbot.run import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
