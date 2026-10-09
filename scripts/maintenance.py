"""만료 프로젝트 삭제 + 멈춘 job 복구.

운영에서는 1시간마다 실행한다 (docker-compose.prod.yml 의 maintenance 서비스).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "apps" / "api")]

from worker.maintenance import cleanup_expired, recover_stuck  # noqa: E402


def main() -> int:
    stuck = recover_stuck()
    expired = cleanup_expired()
    print(f"멈춘 job 복구 {len(stuck)}개, 만료 프로젝트 삭제 {len(expired)}개")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
