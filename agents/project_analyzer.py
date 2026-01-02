"""
Project Analyzer Agent.
Uses OpenAI to analyze project files and extract dependency information,
with strong safeguards against context overflow.

Key improvements:
- Exclude noisy directories (tests/docs/benchmarks/etc.)
- Prefer PRIMARY dependency declaration files (pyproject/requirements/setup*)
- Sample a limited number of code files for context
- Scan ALL code files locally to build an import summary (LLM sees only summary)
- Enforce strict total input budget to prevent context_length_exceeded
"""

import logging
import json
import ast
import sys
from collections import Counter
from typing import Dict, List, Tuple

from openai import OpenAI

from config.settings import settings
from utils.memory import Memory

logger = logging.getLogger(__name__)


class ProjectAnalyzer:
    """Analyzes project files using OpenAI to extract dependencies."""

    # --- Scope controls (reduce noise) ---
    EXCLUDE_DIR_PREFIXES = (
        "tests/", "test/",
        "docs/", "doc/",
        "benchmarks/", "benchmark/",
        ".github/", ".git/",
        "examples/", "example/",
        "scripts/", "script/",
        "release/", "dist/", "build/",
        "__pycache__/",
    )

    # Files that most reliably declare dependencies
    PRIMARY_FILES = (
        "pyproject.toml",
        "requirements.txt",
        "requirements-dev.txt",
        "requirements-dev.in",
        "requirements.in",
        "setup.py",
        "setup.cfg",
        "Pipfile",
        "Pipfile.lock",
        "poetry.lock",
        "environment.yml",
        "environment.yaml",
        "conda.yml",
        "conda.yaml",
    )

    # Hard caps to prevent context overflows
    MAX_FILES_TOTAL = 60                  # primary + other + sampled code + import summary
    MAX_CODE_FILES = 30                   # sampled .py files
    MAX_CHARS_PER_PRIMARY = 12000         # configs can be larger
    MAX_CHARS_PER_CODE = 1800             # code samples trimmed aggressively
    MAX_TOTAL_CHARS = 110_000             # overall payload cap (approx)

    # Import summary controls
    TOP_IMPORTS_N = 60

    # Common module -> package mappings (reduce LLM confusion)
    MODULE_TO_PACKAGE = {
        "yaml": "pyyaml",
        "PIL": "pillow",
        "sklearn": "scikit-learn",
        "cv2": "opencv-python",
        "Crypto": "pycryptodome",
        "Cryptodome": "pycryptodome",
        "bs4": "beautifulsoup4",
        "dateutil": "python-dateutil",
        "pkg_resources": "setuptools",
    }

    # Prompt kept compact; emphasizes primary files and conservative inference
    ANALYSIS_PROMPT = """
You are a Python project dependency analyzer.

Goal: produce a minimal, correct environment spec.

Priority:
1) PRIMARY: pyproject.toml / requirements*.txt / setup.py / setup.cfg / Pipfile / poetry.lock
2) SECONDARY: import usage (sampled code + import summary)

Rules:
- Prefer explicit versions from PRIMARY files.
- If a dependency is only inferred from imports, choose a conservative stable version.
- Do NOT include test-only/dev-only tools unless explicitly required by PRIMARY files.
- Only declare CUDA/cuDNN if there is direct evidence (torch.cuda / tensorflow GPU / etc).
- If the project is pure Python, prefer pip packages; use conda only when clearly beneficial.

Output JSON schema:
{
  "project_name": "...",
  "packages": [{"name":"...", "version":"...", "source":"conda|pip", "reason":"..."}],
  "python_version": "3.x",
  "cuda_version": "11.8|null",
  "cudnn_version": "8.x|null",
  "system_dependencies": [],
  "analysis_notes": "..."
}

Project files (selected):
"""

    def __init__(self):
        self.client = OpenAI(api_key=settings.api_key)
        logger.info("ProjectAnalyzer initialized")

    def analyze(self, files_content: Dict[str, str], memory: Memory) -> None:
        logger.info("Starting project analysis...")

        # 1) Local scan of imports across ALL code files (LLM receives only summary)
        import_summary_text = self._build_import_summary(files_content)

        # 2) Select bounded subset of files for LLM context
        selected_files = self._select_relevant_files(files_content)

        # 3) Add import summary as a virtual file for LLM
        selected_files["__import_summary__"] = import_summary_text

        # 4) Format prompt payload with strict budget enforcement
        files_text = self._format_files_content(selected_files)

        try:
            response = self.client.chat.completions.create(
                model="gpt-4-turbo-preview",
                messages=[
                    {"role": "system", "content": "You are an expert Python project dependency analyzer."},
                    {"role": "user", "content": self.ANALYSIS_PROMPT + files_text},
                ],
                temperature=0.2,
                response_format={"type": "json_object"},
            )

            result_text = response.choices[0].message.content
            logger.info("Received response from OpenAI")

            result = json.loads(result_text)

            memory.project_name = result.get("project_name", "my_project")

            packages = result.get("packages", [])
            if packages and isinstance(packages[0], dict):
                memory.package_list = [
                    f"{pkg['name']}=={pkg['version']}" if pkg.get("version") else pkg["name"]
                    for pkg in packages
                ]
            else:
                memory.package_list = packages

            memory.python_version = result.get("python_version", "3.9")
            memory.cuda_version = result.get("cuda_version")
            memory.cudnn_version = result.get("cudnn_version")
            memory.system_dependencies = result.get("system_dependencies", [])
            memory.raw_analysis = result.get("analysis_notes", "")

            logger.info(f"Analysis complete: {memory}")

        except Exception as e:
            logger.error(f"Error during analysis: {e}")
            raise

    # ----------------------------
    # File selection / filtering
    # ----------------------------
    def _select_relevant_files(self, files_content: Dict[str, str]) -> Dict[str, str]:
        """
        Select a bounded subset of files to avoid context overflow:
        - include PRIMARY files first (config/lock/requirements)
        - exclude noisy dirs (tests/docs/benchmarks/...)
        - sample a limited number of library code files
        - include small relevant text files (README)
        """
        primary: List[Tuple[str, str]] = []
        code: List[Tuple[str, str]] = []
        other: List[Tuple[str, str]] = []

        for path, content in files_content.items():
            norm = path.replace("\\", "/")

            # Skip noise
            if any(norm.startswith(pfx) for pfx in self.EXCLUDE_DIR_PREFIXES):
                continue

            base = norm.split("/")[-1]

            # Import summary is injected later; ignore if present in repo content
            if base == "__import_summary__" or norm == "__import_summary__":
                continue

            # PRIMARY dependency declaration files
            if base in self.PRIMARY_FILES:
                primary.append((norm, content))
                continue

            # Optional: keep small readme
            if base.lower() in ("readme.md", "readme.rst"):
                other.append((norm, content))
                continue

            # Sample code files
            if norm.endswith(".py"):
                code.append((norm, content))
                continue

        primary.sort(key=lambda x: x[0])
        other.sort(key=lambda x: x[0])
        code.sort(key=lambda x: x[0])

        code_sample = code[: self.MAX_CODE_FILES]

        merged: List[Tuple[str, str]] = []
        merged.extend(primary)
        merged.extend(other)
        merged.extend(code_sample)

        merged = merged[: self.MAX_FILES_TOTAL]
        selected = {k: v for k, v in merged}

        logger.info(
            "Selected files for analysis: primary=%d other=%d code_sample=%d total=%d",
            len(primary), len(other), len(code_sample), len(selected)
        )
        return selected

    # ----------------------------
    # Prompt payload formatting
    # ----------------------------
    def _format_files_content(self, files_content: Dict[str, str]) -> str:
        formatted_parts: List[str] = []
        total = 0

        for filename in sorted(files_content.keys()):
            content = files_content[filename]
            base = filename.split("/")[-1]
            is_primary = (
                base in self.PRIMARY_FILES
                or filename.startswith("__import_summary__")
                or filename.startswith("__import_summary__")
            )

            per_file_cap = self.MAX_CHARS_PER_PRIMARY if is_primary else self.MAX_CHARS_PER_CODE
            clipped = content if len(content) <= per_file_cap else (content[:per_file_cap] + "\n... (truncated)\n")

            block = f"--- {filename} ---\n{clipped}\n\n"

            if total + len(block) > self.MAX_TOTAL_CHARS:
                formatted_parts.append("\n--- [TRUNCATED: input budget reached] ---\n")
                break

            formatted_parts.append(block)
            total += len(block)

        logger.info("Formatted prompt payload size (chars): %d", total)
        return "\n" + "".join(formatted_parts)

    # ----------------------------
    # Import summary (local scan)
    # ----------------------------
    def _build_import_summary(self, files_content: Dict[str, str]) -> str:
        """
        Scan ALL .py files locally (excluding noise dirs) and build a compact import summary.
        LLM sees only the summary, not full code.
        """
        counter = Counter()

        for path, content in files_content.items():
            norm = path.replace("\\", "/")

            if any(norm.startswith(pfx) for pfx in self.EXCLUDE_DIR_PREFIXES):
                continue
            if not norm.endswith(".py"):
                continue

            # Avoid pathological parse time on very large files
            snippet = content if len(content) <= 80_000 else content[:80_000]

            mods = self._extract_top_level_imports(snippet)
            for m in mods:
                pkg = self._normalize_module_to_package(m)
                if pkg:
                    counter[pkg] += 1

        if not counter:
            return "Import Summary: no imports detected from Python source files (after filtering)."

        top = counter.most_common(self.TOP_IMPORTS_N)
        other_count = max(0, len(counter) - len(top))

        lines: List[str] = []
        lines.append("Import Summary (scanned locally from all .py files)")
        lines.append(f"- unique_nonstdlib_packages: {len(counter)}")
        lines.append(f"- top_{self.TOP_IMPORTS_N}:")
        for name, freq in top:
            lines.append(f"  - {name}: {freq}")
        if other_count > 0:
            lines.append(f"- other_unique_packages_not_listed: {other_count}")
        lines.append("")
        lines.append("Notes:")
        lines.append("- Counts are frequency across files, not exact runtime requirement.")
        lines.append("- stdlib imports are removed. Common module→package mappings are normalized.")

        return "\n".join(lines)

    def _extract_top_level_imports(self, source: str) -> List[str]:
        """
        Extract top-level modules via AST parsing:
        - 'pandas.core' -> 'pandas'
        - from x.y import z -> 'x'
        """
        mods: List[str] = []

        try:
            tree = ast.parse(source)
        except Exception:
            # Fallback: simple regex parsing (less accurate)
            import re
            for m in re.findall(r"^\s*import\s+([a-zA-Z0-9_\.]+)", source, flags=re.MULTILINE):
                mods.append(m.split(".")[0])
            for m in re.findall(r"^\s*from\s+([a-zA-Z0-9_\.]+)\s+import\s+", source, flags=re.MULTILINE):
                if not m.startswith("."):
                    mods.append(m.split(".")[0])
            return mods

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = (alias.name or "").split(".")[0]
                    if name:
                        mods.append(name)
            elif isinstance(node, ast.ImportFrom):
                if node.module and not (node.level and node.level > 0):
                    name = node.module.split(".")[0]
                    if name:
                        mods.append(name)

        return mods

    def _normalize_module_to_package(self, module_name: str) -> str:
        """
        Normalize module name to a likely pip package name:
        - drop stdlib modules
        - apply common module->package mappings
        """
        if not module_name:
            return ""

        if module_name.startswith("."):
            return ""

        # Remove stdlib modules (Python 3.10+ usually provides sys.stdlib_module_names)
        try:
            stdlib = getattr(sys, "stdlib_module_names", set())
            if module_name in stdlib:
                return ""
        except Exception:
            pass

        # Apply common mapping
        if module_name in self.MODULE_TO_PACKAGE:
            return self.MODULE_TO_PACKAGE[module_name]

        return module_name
