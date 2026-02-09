from pathlib import Path
from jinja2 import Environment, FileSystemLoader


def create_jinja_env(templates_dir: Path) -> Environment:
    return Environment(
        loader=FileSystemLoader(templates_dir),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
