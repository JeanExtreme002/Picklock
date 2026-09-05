# -*- coding: utf-8 -*-
"""Sphinx configuration for Picklock's documentation.

Pages are written in Markdown through the MyST parser, with reStructuredText
directives where they earn their keep (``{toctree}``, admonitions). The Read
the Docs theme gives the left-sidebar HTML build people expect from Python
docs.

One page is not written at all: ``reference/commands.md`` is generated from
the command registry at the start of every build, so the reference and the
shell's own ``help`` cannot say different things.
"""

import os
import subprocess
import sys
from datetime import datetime

# Make the package importable — the reference generator reads the registry.
sys.path.insert(0, os.path.abspath(".."))

# -- Generated pages ---------------------------------------------------------

_REPO_ROOT = os.path.abspath("..")
_GENERATOR = os.path.join(_REPO_ROOT, "scripts", "generate_command_reference.py")

if os.path.exists(_GENERATOR):
    # Run it in a subprocess rather than importing it: the generator imports
    # every command module, and a build should not inherit whatever that
    # leaves behind in this process.
    subprocess.run([sys.executable, _GENERATOR], check=True, cwd=_REPO_ROOT)

# -- Project information -----------------------------------------------------

project = "Picklock"
author = "Jean Loui Bernard Silva de Jesus"
copyright = f"{datetime.now().year}, {author}"

try:
    from picklock import __version__ as release
except Exception:  # pragma: no cover - docs can build without the package installed
    release = "0.2.3"

version = ".".join(release.split(".")[:2])

# -- General configuration ---------------------------------------------------

extensions = [
    "myst_parser",
    "sphinx.ext.intersphinx",
    "sphinx_copybutton",
    "sphinx_design",
]

source_suffix = {
    ".md": "markdown",
    ".rst": "restructuredtext",
}

master_doc = "index"

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# -- MyST configuration ------------------------------------------------------

myst_enable_extensions = [
    "colon_fence",
    "deflist",
    "fieldlist",
    "html_image",
    "html_admonition",
    "linkify",
    "replacements",
    "smartquotes",
    "substitution",
    "tasklist",
]

myst_heading_anchors = 3

# -- HTML output -------------------------------------------------------------

html_theme = "sphinx_rtd_theme"
html_title = "Picklock"

html_theme_options = {
    "logo_only": False,
    "collapse_navigation": False,
    "sticky_navigation": True,
    "navigation_depth": 3,
    "includehidden": True,
    "titles_only": False,
    "prev_next_buttons_location": "bottom",
    "style_external_links": True,
}

# Wire up the theme's native "Edit on GitHub" link (top-right of every page),
# plus the data the custom sidebar "Star on GitHub" call-to-action reads.
html_context = {
    "display_github": True,
    "github_user": "JeanExtreme002",
    "github_repo": "Picklock",
    "github_version": "main",
    "conf_py_path": "/docs/",
}

# `../assets` is copied in alongside the sheet, so the terminal capture is
# served from the build rather than fetched from GitHub — the docs render the
# same offline, on a branch, and before the image reaches `main`.
html_static_path = ["_static", "../assets"]
html_css_files = ["custom.css"]

# -- Intersphinx mappings ----------------------------------------------------

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
}

# -- copybutton --------------------------------------------------------------

# Strip the shell prompts so a copied line is a line you can paste. Picklock's
# own prompt carries the target — `picklock [game.exe:41902]>` — so the pattern
# has to allow that middle part.
copybutton_prompt_text = r"\$ |picklock(?: \[[^\]]*\])?> "
copybutton_prompt_is_regexp = True
