"""Allow ``python -m cce`` to invoke the CLI entrypoint."""

from cce.cli import entrypoint

if __name__ == "__main__":
    entrypoint()
