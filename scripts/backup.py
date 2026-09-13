import argparse, sqlite3
from datetime import datetime, timezone
from pathlib import Path
parser=argparse.ArgumentParser(description='Backup consistente do SQLite via Backup API')
parser.add_argument('--source',default='data/affiliate_engine.db');parser.add_argument('--destination',default='data/backups')
args=parser.parse_args(); source=Path(args.source).resolve(); destination=Path(args.destination).resolve()
if not source.is_file(): raise SystemExit(f'Banco não encontrado: {source}')
destination.mkdir(parents=True,exist_ok=True); target=destination/f"affiliate_engine_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.db"
with sqlite3.connect(source) as src, sqlite3.connect(target) as dst: src.backup(dst)
print(target)
