"""Runtime prompt templates, as a package so they ship in the wheel.

`prompt_loader` resolves paths relative to the repo/site-packages root, and
`prompts/` was a bare directory — `[tool.setuptools.package-data]` only applies
to packages, so the templates were left out of the built wheel entirely while
`prompt_loader.py` itself shipped. Nothing failed at install time; the first
`discover` call raised FileNotFoundError from `company.py`'s module-level load,
which is the MCP surface's flagship verb.

This file exists only to make setuptools see the directory. Nothing imports it.
"""
