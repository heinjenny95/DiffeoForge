"""Allow ``python -m diffeoforge`` to behave like the CLI command."""

from diffeoforge.cli import main

raise SystemExit(main())
