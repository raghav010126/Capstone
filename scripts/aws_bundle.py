"""Zip the Docker build context for CodeBuild: only what the Lambda image needs (a few MB)."""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def main(out: str) -> None:
    reqs = subprocess.run(["uv", "export", "--no-dev", "--no-hashes", "--no-emit-project", "--no-group", "ingest",
                           "--no-editable", "--python", "3.12"], cwd=REPO, check=True, capture_output=True, text=True).stdout
    cache = Path.home() / ".cache" / "medishield" / "policy_index"
    dst = Path(out)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("requirements-lambda.txt", reqs)
        for f in ("infra/Dockerfile", "infra/buildspec.yml"):
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
