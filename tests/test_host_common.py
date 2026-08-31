from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from keepygaga.host_common import captured_output, captured_streams, run_captured


def test_run_captured_decodes_utf8_when_locale_is_not_utf8(tmp_path: Path) -> None:
    child = tmp_path / "utf8-child.py"
    child.write_text(
        "import sys\n"
        "sys.stdout.buffer.write('已安装 keepygaga 0.6.0\\n'.encode('utf-8'))\n"
        "sys.stderr.buffer.write('Updated keepygaga\\n'.encode('utf-8'))\n"
        "raise SystemExit(1)\n",
        encoding="utf-8",
    )

    completed = run_captured([sys.executable, str(child)], timeout=10)

    assert completed.returncode == 1
    assert completed.stdout == "已安装 keepygaga 0.6.0\n"
    assert captured_output(completed) == "Updated keepygaga"


def test_captured_output_treats_missing_streams_as_empty() -> None:
    completed = subprocess.CompletedProcess(["uv"], 1, None, None)

    assert captured_output(completed) == ""
    assert captured_streams(completed) == "\n"
