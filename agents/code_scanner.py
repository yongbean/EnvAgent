import os
import ast
import logging
from pathlib import Path
from typing import List, Set, Dict, Tuple

logger = logging.getLogger(__name__)

class CodeScannerAgent:
    """
    Scans project structure to find the true project root (e.g., hidden setup.py),
    then extracts imports using static analysis.
    """

    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def analyze_project(self, input_root_dir: str, project_name: str = "project") -> Tuple[Path, Path]:
        """
        [New] Main Entry Point
        1. Finds the 'True Project Root' (handling monorepos like AutoGPT).
        2. Scans files only within that valid root.
        
        Returns:
            Tuple[Path, Path]: (true_root_path, summary_file_path)
        """
        root_path = Path(input_root_dir)
        
        # 1. 진짜 프로젝트 루트 찾기 (정찰병 로직)
        logger.info(f"🕵️‍♂️ Searching for true project root in: {root_path}")
        true_root = self._find_best_project_root(root_path)
        
        if true_root != root_path:
            logger.info(f"🎯 Monorepo detected! Switching root: {root_path} -> {true_root}")
        else:
            logger.info(f"✅ Using provided root as project root (No better subdir found).")

        # 2. 진짜 루트 내부의 파이썬 파일 수집
        target_files = []
        for root, _, files in os.walk(true_root):
            for file in files:
                # .py 파일 및 의존성 관련 파일 수집
                if file.endswith('.py') or file in ['requirements.txt', 'setup.py', 'pyproject.toml']:
                    target_files.append(Path(root) / file)

        # 3. 수집된 파일들로 기존 스캔 로직 실행
        summary_path = self.scan_files(target_files, true_root, project_name)
        
        return true_root, summary_path

    def _find_best_project_root(self, root_path: Path) -> Path:
        """
        [Fixed] Directory Scoring System
        - Only switches to a subdirectory if it contains STRONG evidence (setup.py, requirements.txt).
        - If no config files are found in subdirs, it sticks to the user-provided root.
        - This fixes the issue where 'nanoGPT/config' was selected just because it had .py files.
        """
        best_path = root_path
        max_score = 0
        
        # 탐색 깊이 제한 (너무 깊은 곳은 프로젝트 루트일 확률이 낮음)
        start_depth = len(root_path.parts)
        max_depth = 3

        for dirpath, dirnames, filenames in os.walk(root_path):
            current_path = Path(dirpath)
            current_depth = len(current_path.parts) - start_depth
            
            if current_depth > max_depth:
                dirnames[:] = [] 
                continue

            score = 0
            
            # 💎 설정 파일이 있어야만 점수를 부여 (단순 소스 파일 개수는 무시)
            # -> NanoGPT처럼 설정 파일이 없는 경우 엉뚱한 폴더로 가는 것을 방지
            if "setup.py" in filenames: score += 10
            if "pyproject.toml" in filenames: score += 10
            if "Pipfile" in filenames: score += 10
            if "environment.yml" in filenames: score += 10
            if "requirements.txt" in filenames: score += 5
            
            # 점수가 0점이면(설정 파일이 없으면) 후보 탈락 -> 그냥 지나감
            if score == 0:
                continue

            # 설정 파일이 발견된 경우에만 후보로 등록
            # 점수가 같으면 더 상위 폴더(깊이가 얕은 폴더)를 선호하거나 기존 유지
            if score > max_score:
                max_score = score
                best_path = current_path
                logger.info(f"✨ Better root candidate found: {best_path} (Score: {score})")

        return best_path

    def scan_files(self, file_paths: List[Path], root_dir: Path, project_name: str) -> Path:
        """
        Scans provided files for imports.
        """
        all_imports = set()
        cuda_required = False
        
        # setup.py나 pyproject.toml 내용도 간단히 텍스트로 긁어오면 좋음
        dependency_hints = []

        logger.info(f"Scanning {len(file_paths)} files in {root_dir.name}...")

        for file_path in file_paths:
            try:
                # 1. Python Import Scan
                if file_path.suffix == '.py':
                    imports, has_cuda = self._scan_python_file(file_path)
                    all_imports.update(imports)
                    if has_cuda:
                        cuda_required = True
                
                # 2. Config File Hint Collection (단순 읽기)
                if file_path.name in ['requirements.txt', 'setup.py', 'pyproject.toml']:
                    content = self._read_file_safe(file_path)
                    if content:
                        dependency_hints.append(f"--- Content of {file_path.name} ---")
                        # 파일이 너무 크면 앞부분만
                        dependency_hints.append(content[:2000]) 
                        dependency_hints.append("\n")

            except Exception as e:
                logger.warning(f"Failed to scan {file_path}: {e}")

        summary_filename = f"dependency_summary_{project_name}.txt"
        output_path = self.output_dir / summary_filename

        self._write_summary(output_path, all_imports, cuda_required, project_name, dependency_hints)
        
        return output_path

    def _scan_python_file(self, file_path: Path):
        """Extract imports using AST."""
        imports = set()
        has_cuda = False
        
        try:
            content = self._read_file_safe(file_path)
            if not content: return imports, has_cuda

            # Check for CUDA hints
            lower_content = content.lower()
            if "cuda" in lower_content or "gpu" in lower_content or "torch.device" in lower_content:
                has_cuda = True

            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for name in node.names:
                        imports.add(name.name.split('.')[0])
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imports.add(node.module.split('.')[0])
                        
        except Exception:
            pass
            
        return imports, has_cuda

    def _read_file_safe(self, path: Path) -> str:
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
        except:
            return ""

    def _write_summary(self, path: Path, imports: Set[str], cuda_required: bool, project_name: str, hints: List[str]):
        """Write the summary to a text file."""
        sorted_imports = sorted(list(imports))
        
        import sys
        std_lib = set(sys.builtin_module_names)
        std_lib.update(['os', 'sys', 're', 'math', 'json', 'time', 'random', 'pathlib', 'typing', 'collections', 'logging', 'unittest', 'shutil', 'subprocess', 'argparse', 'platform', 'datetime', 'copy', 'warnings'])
        
        filtered_imports = [imp for imp in sorted_imports if imp not in std_lib and not imp.startswith('_')]

        content = [
            f"# Dependency Summary for {project_name}",
            f"# Generated by EnvAgent CodeScanner",
            "",
            f"CUDA Required: {'Yes' if cuda_required else 'No'}",
            "",
            "## Detected Imports (from AST):",
        ]
        
        for imp in filtered_imports:
            content.append(f"- {imp}")
            
        content.append("")
        content.append("## Configuration File Hints:")
        content.extend(hints)

        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(content))
            
        logger.info(f"Summary saved to {path}")