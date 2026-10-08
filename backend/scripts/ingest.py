"""CLI: sync a tenant's knowledge folder into Pinecone.   python -m scripts.ingest [--tenant zenshine]"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.config import get_settings
from app.core.logging import configure_logging
from app.services.ingest import sync_tenant
from app.services.vectorstore import PineconeStore


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", default=None)
    args = parser.parse_args()
    s = get_settings()
    configure_logging(s.log_level)
    store = PineconeStore(s)
    report = await sync_tenant(store, Path(s.knowledge_dir), args.tenant or s.default_tenant)
    print(json.dumps(report.as_dict(), indent=2))


if __name__ == "__main__":
    asyncio.run(main())
