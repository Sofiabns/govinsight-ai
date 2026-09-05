import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


def test_download_script_supports_windows_powershell_and_bounded_range(tmp_path: Path) -> None:
    shell = shutil.which("powershell") or shutil.which("pwsh")
    if shell is None:
        pytest.skip("PowerShell is unavailable")

    payload = b"numero_controle_PNCP,data_publicacao_pncp\n123,2026-01-01\n"

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            assert self.headers["Range"] == "bytes=0-63"
            self.send_response(206)
            self.send_header("Content-Type", "text/csv")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    output = tmp_path / "demo.csv"
    script = Path("scripts/download_demo_data.ps1").resolve()
    try:
        result = subprocess.run(
            [
                shell,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-Url",
                f"http://127.0.0.1:{server.server_port}/demo.csv",
                "-OutputPath",
                str(output),
                "-MaxBytes",
                "64",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    assert result.returncode == 0, result.stderr
    assert output.read_bytes() == payload
    assert output.with_suffix(".csv.metadata.json").exists()
