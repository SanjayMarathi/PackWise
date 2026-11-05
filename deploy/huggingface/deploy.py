"""Deploy PackWise to a Hugging Face Docker Space.

The Space repository holds just two files: a Dockerfile that starts ``FROM`` the
published Docker Hub image (pinned to a tag here) and the Space's README card.
Committing them makes Hugging Face rebuild and restart the Space.

    python deploy/huggingface/deploy.py --space user/packwise \
        --image docker.io/user/packwise:<commit-sha> [--create]

Authentication: the ``HF_TOKEN`` environment variable, or a cached
``hf auth login`` token. Requires ``pip install huggingface_hub``.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from huggingface_hub import CommitOperationAdd, HfApi

HERE = Path(__file__).resolve().parent


def render_dockerfile(image: str) -> bytes:
    template = (HERE / "Dockerfile").read_text(encoding="utf-8")
    rendered, count = re.subn(r"(?m)^FROM\s+\S+", f"FROM {image}", template, count=1)
    if count != 1:
        raise SystemExit("deploy/huggingface/Dockerfile has no FROM line")
    return rendered.encode("utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--space", required=True, help="Space id, e.g. user/packwise")
    parser.add_argument("--image", required=True, help="Image reference to run, e.g. docker.io/user/packwise:<sha>")
    parser.add_argument("--create", action="store_true", help="Create the (public, Docker SDK) Space if missing")
    args = parser.parse_args()

    api = HfApi()
    if args.create:
        api.create_repo(args.space, repo_type="space", space_sdk="docker", exist_ok=True)
    commit = api.create_commit(
        repo_id=args.space,
        repo_type="space",
        operations=[
            CommitOperationAdd("Dockerfile", render_dockerfile(args.image)),
            CommitOperationAdd("README.md", (HERE / "README.md").read_bytes()),
        ],
        commit_message=f"Deploy {args.image}",
    )
    print(f"Deployed {args.image} to https://huggingface.co/spaces/{args.space} (commit {commit.oid[:10]})")


if __name__ == "__main__":
    main()
