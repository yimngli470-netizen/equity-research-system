"""Explicit offline verification/retrieval or operator-directed import. No model calls.

verify CAPTURE_DIRECTORY PACK_JSON
show CAPTURE_DIRECTORY CAPTURE_ID
import CAPTURE_DIRECTORY PACK_JSON --database-url URL
Database import is opt-in and must use a reviewed migrated destination.
"""
import argparse
import asyncio
import json
from pathlib import Path
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.research_evidence.collect import load_captures
from app.research_evidence.records import Pack, validate_pack
from app.research_evidence.store import import_pack


async def ingest(url, pack, captures):
    engine=create_async_engine(url)
    try:
        async with async_sessionmaker(engine,expire_on_commit=False)() as db:
            row=await import_pack(db,pack,captures)
            await db.commit()
            return row.id
    finally:
        await engine.dispose()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['verify','show','import'])
    parser.add_argument('captures',type=Path)
    parser.add_argument('target')
    parser.add_argument('--database-url')
    args=parser.parse_args()
    captures=load_captures(args.captures)
    if args.command=='show':
        print(captures[args.target].model_dump_json(indent=2)); return
    pack=Pack.model_validate_json(Path(args.target).read_text())
    validate_pack(pack,captures)
    result={'status':'verified','captures':len(pack.capture_ids),'spans':len(pack.spans)}
    if args.command=='import':
        if not args.database_url: parser.error('Import requires an explicit reviewed database URL')
        result.update(status='imported',pack_id=asyncio.run(ingest(args.database_url,pack,captures)))
    print(json.dumps(result))


if __name__=='__main__':main()
