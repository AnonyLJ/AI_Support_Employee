"""File tools: the worker's view of the company shared drive.

All paths are relative to the workspace folder and cannot escape it. The
worker can read everything there but may only write inside outbox/.
"""
from __future__ import annotations

from pathlib import Path

from . import Tool, ToolError, ToolResult, params

MAX_CHARS = 15_000
WRITABLE_DIR = "outbox"


class Workspace:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def resolve(self, path: str) -> Path:
        target = (self.root / path).resolve()
        if target != self.root and self.root not in target.parents:
            raise ToolError(f"'{path}' is outside the shared drive; use paths like 'inbox/invoices'")
        return target

    def list_files(self, path: str = ".") -> str:
        folder = self.resolve(path)
        if not folder.is_dir():
            raise ToolError(f"'{path}' is not a folder")
        lines = [f"{p.relative_to(self.root).as_posix()}  ({p.stat().st_size:,} bytes)"
                 for p in sorted(folder.rglob("*")) if p.is_file() and not p.name.startswith(".")]
        return "\n".join(lines) or f"(no files in {path})"

    def read_file(self, path: str) -> str:
        file = self.resolve(path)
        if not file.is_file():
            raise ToolError(f"File '{path}' does not exist. Use list_files to see what is there.")
        if file.suffix.lower() == ".pdf":
            from pypdf import PdfReader

            text = "\n".join(page.extract_text() or "" for page in PdfReader(file).pages)
            if not text.strip():
                raise ToolError(f"'{path}' is a scanned PDF with no text layer (OCR is not supported)")
        else:
            text = file.read_text(encoding="utf-8", errors="replace")
        if len(text) > MAX_CHARS:
            text = text[:MAX_CHARS] + f"\n... [truncated, file has {len(text):,} characters]"
        return text

    def write_file(self, path: str, content: str) -> str:
        file = self.resolve(path)
        if self.resolve(WRITABLE_DIR) not in file.parents:
            raise ToolError(f"You may only write inside '{WRITABLE_DIR}/', e.g. '{WRITABLE_DIR}/report.csv'")
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content, encoding="utf-8")
        return f"Saved {len(content):,} characters to {file.relative_to(self.root).as_posix()}"


def file_tools(workspace: Workspace, read_only: bool = False) -> list[Tool]:
    tools = [
        Tool("list_files", "List the files on the company shared drive (recursively).",
             params({"path": {"type": "string", "description": "Folder to list, e.g. 'inbox' (default: everything)"}},
                    required=[]),
             lambda path=".": ToolResult(workspace.list_files(path))),
        Tool("read_file", "Read a text or PDF file from the shared drive.",
             params({"path": {"type": "string", "description": "e.g. 'inbox/invoices/acme.txt'"}}),
             lambda path: ToolResult(workspace.read_file(path))),
    ]
    if not read_only:
        tools.append(Tool(
            "write_file", "Create or overwrite a file in outbox/ (e.g. a CSV or a summary for the user).",
            params({"path": {"type": "string"}, "content": {"type": "string"}}),
            lambda path, content: ToolResult(workspace.write_file(path, content)),
            describe_write=lambda args: f"Write file {args.get('path')} ({len(args.get('content', ''))} characters)",
        ))
    return tools
