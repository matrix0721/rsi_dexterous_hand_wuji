"""Ship root-level assets without duplicating them in the source package."""
from pathlib import Path
from setuptools import setup
from setuptools.command.build_py import build_py

ROOT = Path(__file__).resolve().parent
ASSET_DIRS = ("agent_skills", "models", "library", "references")


class BuildPy(build_py):
    def run(self):
        super().run()
        for directory in ASSET_DIRS:
            for source in (ROOT / directory).rglob("*"):
                if (source.is_file() and source.suffix in (".json", ".md", ".txt")
                        and not source.name.endswith(".local.json")):
                    target = Path(self.build_lib) / "wujiimagine" / "_assets" / source.relative_to(ROOT)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    self.copy_file(str(source), str(target))


setup(cmdclass={"build_py": BuildPy})
