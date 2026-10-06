"""Zip the Docker build context for CodeBuild: only what the images need (a few MB).

Two images are built from it: the app image (``infra/Dockerfile``: AgentCore runtimes and the API Lambda, without Docling) and the
policy ingest Lambda (``infra/Dockerfile.ingest``: the app's dependencies plus Docling on CPU-only PyTorch).
"""

from __future__ import annotations

import re
import subprocess
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TORCH = re.compile(r"^(torch|torchvision)==")
GPU_ONLY = re.compile(r"^(triton|nvidia-[\w.-]+|cuda-[\w.-]+)==")     # pulled in by the PyPI torch wheels; several GB


def export(*args: str) -> str:
    return subprocess.run(["uv", "export", "--no-dev", "--no-hashes", "--no-emit-project", "--no-editable", "--python", "3.12",
                           *args], cwd=REPO, check=True, capture_output=True, text=True).stdout


def ingest_requirements() -> tuple[str, str]:
    """(torch pins, everything else) for the ingest image, from uv.lock. PyTorch is installed from its CPU-only index, so it and
    the CUDA packages are left out of the PyPI list."""
    lines = export().splitlines()                                  # the default groups include `ingest` (Docling)
    torch = [ln for ln in lines if TORCH.match(ln)]
    rest = [ln for ln in lines if not TORCH.match(ln) and not GPU_ONLY.match(ln)]
    if len(torch) != 2:
        raise SystemExit(f"expected torch and torchvision pins in the lock, found {torch}")
    return "\n".join(torch) + "\n", "\n".join(rest) + "\n"


def main(out: str) -> None:
    reqs = export("--no-group", "ingest")
    torch_reqs, ingest_reqs = ingest_requirements()
    cache = Path.home() / ".cache" / "medishield" / "policy_index"
    dst = Path(out)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("requirements-lambda.txt", reqs)
        z.writestr("requirements-torch.txt", torch_reqs)
        z.writestr("requirements-ingest.txt", ingest_reqs)
        for f in ("infra/Dockerfile", "infra/Dockerfile.ingest", "infra/buildspec.yml"):
            z.write(REPO / f, f)
        for root in ("backend/src/medishield", "data/official/records", "data/official/dataset/policies"):
            for p in sorted((REPO / root).rglob("*")):
                if p.is_file() and "__pycache__" not in p.parts:
                    z.write(p, p.relative_to(REPO).as_posix())
        for p in sorted((REPO / "docs" / "eval_results").glob("*.json")):
            z.write(p, f"docs/eval_results/{p.name}")
        for p in sorted(cache.glob("*.json")):
            z.write(p, f"policy_index_cache/{p.name}")
    print(f"{dst} {dst.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "build/source.zip")
