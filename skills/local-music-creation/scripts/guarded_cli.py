"""Run one native CLI job under the upstream power/resource monitor."""
import sys
from pathlib import Path
from lyra.cli import main
from lyra.measure import ResourceMonitor

report, require_ac, *arguments = sys.argv[1:]
with ResourceMonitor(require_ac=require_ac == 'true', report_path=Path(report)):
    code = main(arguments)
raise SystemExit(code or 0)
