"""Sandboxed pytest runner.

SECURITY: this executes LLM-generated test code and PR-supplied source code. That
is arbitrary code execution by definition. Mitigations applied here:
  - runs in a one-shot subprocess (never in-process), so a crash/hang can't take
    down the agent;
  - executes inside a throwaway `tempfile.TemporaryDirectory()`;
  - a hard wall-clock timeout (default 60 s) via subprocess.run(timeout=...);
  - captured + length-capped output;
  - a scrubbed, minimal environment (no inherited secrets).

This is NOT a true security boundary. For untrusted PRs, run the agent itself
inside a disposable container/VM (see ENABLE_TEST_EXECUTION docs).
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

_OUTPUT_CAP = 6000  # chars of combined stdout/stderr returned


def _safe_join(base: Path, rel: str) -> Path | None:
    """Resolve `rel` under `base`, rejecting absolute paths and traversal."""
    candidate = (base / rel).resolve()
    try:
        candidate.relative_to(base.resolve())
    except ValueError:
        return None
    return candidate


def run_pytest(
    source_files: dict[str, str],
    test_code: str,
    *,
    timeout: int = 60,
) -> tuple[int, str]:
    """Write source files + a generated test into a temp dir and run pytest.

    Returns (returncode, combined_output). returncode 0 means all tests passed;
    5 means pytest collected no tests; non-zero otherwise. A timeout returns a
    synthetic non-zero code with an explanatory message.
    """
    with tempfile.TemporaryDirectory(prefix="bandwidth_") as tmp:
        base = Path(tmp)
        for rel, content in source_files.items():
            dest = _safe_join(base, rel)
            if dest is None:
                log.warning("test_runner: skipping unsafe path %r", rel)
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")

        (base / "test_bandwidth.py").write_text(test_code, encoding="utf-8")

        # Minimal, scrubbed environment. Keep PATH so the interpreter resolves;
        # drop everything else (API keys, tokens, etc.).
        env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1",
        }
        if sys.platform == "win32":
            # Python on Windows needs SYSTEMROOT to initialize.
            for key in ("SYSTEMROOT", "SystemRoot", "TEMP", "TMP"):
                if key in os.environ:
                    env[key] = os.environ[key]

        cmd = [sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider"]
        try:
            proc = subprocess.run(
                cmd,
                cwd=tmp,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            return 124, f"Tests exceeded the {timeout}s time limit and were killed."
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("test_runner: failed to launch pytest")
            return 1, f"Could not run pytest: {exc}"

        output = (proc.stdout or "") + (proc.stderr or "")
        output = output.strip() or "(no output)"
        if len(output) > _OUTPUT_CAP:
            output = output[:_OUTPUT_CAP] + "\n…(output truncated)"
        return proc.returncode, output
