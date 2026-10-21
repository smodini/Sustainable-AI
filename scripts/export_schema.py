"""Write the Idleness Schema as JSON Schema so the Go controller can pin to it.

Usage:  python scripts/export_schema.py   (run from the repo root)
Output: greenops/schema/idleness-record.v<SCHEMA_VERSION>.json
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1] / "greenops"
sys.path.insert(0, str(ROOT))

from app.models.idleness import SCHEMA_VERSION, IdlenessRecord  # noqa: E402

out = ROOT / "schema" / f"idleness-record.v{SCHEMA_VERSION}.json"
out.parent.mkdir(exist_ok=True)
schema = IdlenessRecord.model_json_schema()
schema["$id"] = f"idleness-record.v{SCHEMA_VERSION}"
out.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
print(f"wrote {out}")
