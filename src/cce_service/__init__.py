"""Production service surface for CCE.

Provides a REST API in front of ``cce score`` / ``cce verify`` with
OAuth2 client-credentials authentication, durable storage (Postgres for
jobs/users/audit; ClickHouse for records — REQ-D-2/REQ-D-5), and async
worker dispatch into Firecracker microVMs (see ``dispatch.firecracker``).

Modules are organised so the deterministic core (``cce.*``) is the only
hard dependency. FastAPI / SQLAlchemy / ClickHouse driver are imported
lazily inside their respective modules to keep the POC dev env light.
"""

__version__ = "0.1.0"
