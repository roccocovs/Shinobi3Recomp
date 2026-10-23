"""Expose the production bounded trace code to a standalone host unit test."""
from pathlib import Path
import sys

source = Path(sys.argv[1]).read_text()
start = source.index('#define RDB_SOUND_INDEX_SIZE')
end = source.index('/* =========================================================================', start)
chunk = source[start:end]
assert 'rdb_sound_write_trace' in chunk and 'rdb_sound_first_fault_format' in chunk
Path(sys.argv[2]).write_text(chunk)
