#!/usr/bin/env python3
"""Read-only independent recheck of an existing Agent learning package."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from package_audit import audit_package

parser = argparse.ArgumentParser(description="复核已生成学习包的原始资料覆盖、页面关联和资源哈希")
parser.add_argument("package", type=Path)
args = parser.parse_args()
report = audit_package(args.package, verify_manifest=True)
print(json.dumps(report, ensure_ascii=False, indent=2))
raise SystemExit(0 if report["status"] == "passed" else 2)
