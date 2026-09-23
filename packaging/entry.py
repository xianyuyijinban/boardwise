"""Entry point for the frozen exe (028 batch 3a).

One line of real work, and it is not redundant with ``src/boardwise/cli.py``'s
own ``__main__`` block: that file cannot be PyInstaller's entry point, because
it uses package-relative imports (``from . import resources``) which do not
resolve when the file is run as a script. This launcher imports the package the
way the installed console script does (``[project.scripts] boardwise =
"boardwise.cli:main"``), so the frozen build and the installed build enter
through the same door.
"""

from __future__ import annotations

import sys

from boardwise.cli import main

if __name__ == "__main__":
    sys.exit(main())
