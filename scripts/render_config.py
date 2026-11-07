#!/usr/bin/env python3
"""Render config/odoo.conf from the template and the current environment."""

import os
import stat
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ("ODOO_MASTER_PASSWORD", "POSTGRES_PASSWORD")


def main() -> None:
    missing = [key for key in REQUIRED if not os.environ.get(key)]
    if missing:
        raise SystemExit("Missing environment values: " + ", ".join(missing))
    rendered = (ROOT / "config" / "odoo.conf.template").read_text(encoding="utf-8")
    for key in REQUIRED:
        rendered = rendered.replace("${" + key + "}", os.environ[key])
    if "${" in rendered:
        raise SystemExit("odoo.conf template still has an unsubstituted variable")
    target = ROOT / "config" / "odoo.conf"
    target.write_text(rendered, encoding="utf-8")
    # The Odoo process inside the container runs as a different user.
    target.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)


if __name__ == "__main__":
    main()
