"""Optional development log compression; not a product runtime dependency."""
import json
from pathlib import Path
import sys

from headroom.transforms.log_compressor import LogCompressor, LogCompressorConfig

compressor = LogCompressor(LogCompressorConfig(max_total_lines=35, enable_ccr=False))
for name in sys.argv[1:]:
    source = Path(name)
    raw = source.read_bytes()
    encoding = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
    result = compressor.compress(raw.decode(encoding), context="Find failures and actual test summary")
    source.with_suffix(".headroom.txt").write_text(result.compressed, "utf-8")
    stats = {"source": source.name, "original_lines": result.original_line_count,
             "compressed_lines": result.compressed_line_count,
             "tokens_saved_estimate": result.tokens_saved_estimate,
             "compression_ratio": result.compression_ratio, "stats": result.stats}
    source.with_suffix(".headroom.json").write_text(json.dumps(stats, indent=2), "utf-8")
    print(json.dumps(stats))
