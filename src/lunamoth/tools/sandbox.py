from __future__ import annotations

from pathlib import Path


class SandboxViolation(ValueError):
    pass


class Sandbox:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.files_dir = (self.root / "files").resolve()
        self.logs_dir = (self.root / "logs").resolve()
        self.workspace_dir = (self.root / "workspace").resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.files_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

    def resolve_inside(self, relative: str | Path, base: Path | None = None) -> Path:
        rel = Path(relative)
        if rel.is_absolute():
            raise SandboxViolation("absolute paths are not allowed")
        target_base = (base or self.files_dir).resolve()
        target = (target_base / rel).resolve()
        if target != target_base and target_base not in target.parents:
            raise SandboxViolation("path escapes sandbox")
        return target

    # The chara has ONE working directory: workspace/. The terminal runs there,
    # and write_file/read_file/list_files all operate there too — so a file the
    # chara writes with write_file is the same file its `ls`/`cat` in the
    # terminal sees. (A separate files/ tree once existed and split the two,
    # which made write_file report success for a file the terminal couldn't
    # find. works.list still surfaces the legacy files/ tree for old charas.)
    def list_files(self) -> list[str]:
        names: list[str] = []
        for p in sorted(self.workspace_dir.rglob("*")):
            if p.is_file():
                names.append(str(p.relative_to(self.workspace_dir)))
        return names

    def read_file(self, filename: str, max_chars: int = 6000) -> str:
        path = self.resolve_inside(filename, base=self.workspace_dir)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(filename)
        text = path.read_text(encoding="utf-8", errors="replace")
        return text[:max_chars]

    def write_file(self, filename: str, text: str) -> None:
        path = self.resolve_inside(filename, base=self.workspace_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    # Back-compat aliases (the workspace IS the file space now).
    list_workspace = list_files
    read_workspace_file = read_file
