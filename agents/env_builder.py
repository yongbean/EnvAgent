"""
Environment Builder Agent (OS-Aware & Absolute Path).
- Detects OS: Skips CUDA on macOS (Darwin), enables it on Linux.
- Fixed Absolute Path: Uses absolute paths for pip install.
- Robust Logic: Maps packages and infers versions.
"""

import logging
import re
import yaml
import platform  # 👈 [New] OS 확인을 위해 추가
from pathlib import Path
from typing import Optional, Tuple, Any, Dict

from openai import OpenAI

from config.settings import settings
from utils import sanitize_env_name

logger = logging.getLogger(__name__)


class EnvironmentBuilder:
    """Builds a Conda environment.yml file from analysis results."""

    # ------------------------------------------------------------------
    # 🧠 PROMPT FOR SUMMARY (Mac/Linux 대응 추가)
    # ------------------------------------------------------------------
    BUILD_FROM_SUMMARY_PROMPT = """
You are a Senior DevOps Engineer.
Your task is to create a robust `environment.yml` file based on the provided dependency summary.

### PROJECT DETAILS
- **Project Name:** {project_name}
- **Python Version (target):** {python_version}
- **CUDA Requirement:** {cuda_version}

### DETECTED DEPENDENCIES (Summary)
{summary_content}

### 🚨 STRICT RULES

1. **CRITICAL: PACKAGE MAPPING (TRANSLATION):**
   - **`torch`** → **`pytorch`**
   - **`opencv-python`** / `cv2` → **`opencv`**
   - **`Pillow`** → **`pillow`**
   - **`scikit-learn`** → **`scikit-learn`**
   - **`protobuf`** → **`libprotobuf`**

2. **OS SPECIFIC RULES (CRITICAL):**
   - If CUDA Requirement says **"macOS"** or **"None"**:
     - **DO NOT** include `cudatoolkit`, `cuda`, `nvidia`, `ncc` packages.
     - **DO NOT** include `nvidia` channel.
     - Just install `pytorch` (It automatically supports MPS on macOS).

3. **CHANNEL PRIORITY:**
   - **`pytorch`**
   - **`nvidia`** (ONLY if CUDA is required and NOT macOS)
   - `conda-forge`
   - `defaults`

4. **OUTPUT FORMAT:**
   - Return ONLY raw YAML (no markdown).
"""

    # ------------------------------------------------------------------
    # 🧠 PROMPT FOR EXISTING FILES
    # ------------------------------------------------------------------
    BUILD_FROM_EXISTING_FILES_PROMPT = """
You are a Senior DevOps Engineer.
Your task is to convert existing environment file(s) into a unified Conda `environment.yml` file.

### PROJECT DETAILS
- **Project Name:** {project_name}
- **Python Version (target):** {python_version}

### EXISTING ENVIRONMENT FILES CONTENT
{collected_content}

### 🚨 STRICT RULES

1. **CRITICAL: PACKAGE NORMALIZATION:**
   - **`torch`** → **`pytorch`**
   - **`opencv-python`** → **`opencv`**
   - **`tensorflow-gpu`** → **`tensorflow`** (Let Conda handle GPU)

2. **OS SPECIFIC:**
   - If building for macOS (Implicit), do not force `cudatoolkit`.

3. **OUTPUT FORMAT:**
   - Return ONLY raw YAML.
   - No markdown.
"""

    # ---- Heuristic triggers for minimum Python versions ----
    _PY310_PATTERNS = [
        re.compile(r"^\s*match\s+.+:\s*$", re.MULTILINE),
        re.compile(r"^\s*case\s+.+:\s*$", re.MULTILINE),
    ]

    def __init__(self):
        self.client = OpenAI(api_key=settings.api_key)
        logger.info("EnvironmentBuilder initialized")

    # ----------------------------
    # Public API
    # ----------------------------
    def build_from_summary(
        self,
        summary_path: str,
        project_name: str = "my_project",
        python_version: Optional[str] = None,
        repo_root: Optional[str] = None,
    ) -> str:
        """
        Generate environment.yml content from a dependency summary file.
        """
        logger.info(f"Building environment.yml from summary: {summary_path}")

        summary_content = self._read_text(summary_path)
        sanitized_name = sanitize_env_name(project_name)
        logger.info(f"Using sanitized environment name: {sanitized_name}")

        # [New] CUDA hint with OS check
        cuda_version = self._infer_cuda(summary_content)

        # Python version inference
        inferred_py = self._infer_python_version(
            summary_content=summary_content,
            repo_root=repo_root
        )

        target_python = self._choose_python_version(python_version, inferred_py)
        logger.info(f"Target Python version selected: {target_python} (user={python_version}, inferred={inferred_py})")

        prompt = self.BUILD_FROM_SUMMARY_PROMPT.format(
            project_name=sanitized_name,
            python_version=target_python,
            cuda_version=cuda_version,
            summary_content=summary_content
        )

        env_content = self._call_llm(prompt)
        env_content = self._clean_markdown(env_content)
        env_content = self._ensure_python_dep(env_content, target_python)

        return env_content

    def build_from_existing_files(
        self,
        collected_content: str,
        project_name: str = "my_project",
        python_version: str = "3.9",
        target_directory: Optional[str] = None,
        root_directory: Optional[str] = None
    ) -> str:
        """
        Generate environment.yml content from existing environment files.
        Injects ABSOLUTE PATH installation command to prevent path errors.
        """
        logger.info("Building environment.yml from existing environment files...")

        sanitized_name = sanitize_env_name(project_name)
        logger.info(f"Using sanitized environment name: {sanitized_name}")

        prompt = self.BUILD_FROM_EXISTING_FILES_PROMPT.format(
            project_name=sanitized_name,
            python_version=python_version,
            collected_content=collected_content
        )

        # 1. Generate Raw YAML
        env_content = self._call_llm(prompt)
        env_content = self._clean_markdown(env_content)
        
        # 2. Inject Absolute Path Logic
        if target_directory:
            env_content = self._inject_relative_path_install(
                yaml_content=env_content, 
                target_dir=target_directory, 
                root_dir=root_directory
            )

        # 3. Ensure Python Version
        env_content = self._ensure_python_dep(env_content, python_version)

        logger.info("Successfully generated environment.yml from existing files")
        return env_content

    # ----------------------------
    # Helper: Monorepo Path Injection (ABSOLUTE PATH FIX)
    # ----------------------------
    def _inject_relative_path_install(self, yaml_content: str, target_dir: str, root_dir: Optional[str] = None) -> str:
        try:
            target_path = Path(target_dir).resolve()
            install_cmd = f"-e {str(target_path)}"
            logger.info(f"🔧 Monorepo: Injecting ABSOLUTE installation command '{install_cmd}'")

            data = yaml.safe_load(yaml_content)
            
            if "dependencies" not in data:
                data["dependencies"] = []
            
            pip_list = None
            for item in data["dependencies"]:
                if isinstance(item, dict) and "pip" in item:
                    pip_list = item["pip"]
                    break
            
            if pip_list is None:
                pip_list = []
                data["dependencies"].append({"pip": pip_list})

            if "-e ." in pip_list:
                pip_list.remove("-e .")
            
            if install_cmd not in pip_list:
                pip_list.append(install_cmd)
            
            return yaml.dump(data, sort_keys=False)

        except Exception as e:
            logger.error(f"Failed to inject absolute path: {e}")
            return yaml_content

    # ----------------------------
    # Helper: Inference Logic (OS 감지 추가됨!)
    # ----------------------------
    def _infer_cuda(self, summary_content: str) -> str:
        # [New] OS가 Mac(Darwin)이면 CUDA를 강제로 끕니다.
        if platform.system() == "Darwin":
            logger.info("🍎 macOS detected! Skipping CUDA requirements.")
            return "None (macOS detected - CUDA not supported, uses MPS/CPU)"
            
        if "CUDA Required: Yes" in summary_content or "True" in summary_content:
            return "CUDA 11.8 (Auto-detected)"
        return "Not specified"

    def _infer_python_version(self, summary_content: str, repo_root: Optional[str]) -> str:
        hint = self._extract_python_hint_from_summary(summary_content)
        if hint: return hint

        if repo_root:
            try:
                min_ver = self._scan_repo_for_min_python(repo_root)
                if min_ver: return min_ver
            except Exception as e:
                logger.warning(f"Python version inference scan failed: {e}")

        return "3.11"

    def _extract_python_hint_from_summary(self, summary_content: str) -> Optional[str]:
        m = re.search(r"Python\s+Version\s+Hint:\s*([0-9]+\.[0-9]+)", summary_content, re.IGNORECASE)
        if m: return m.group(1)

        m = re.search(r"Requires-Python:\s*>=\s*([0-9]+\.[0-9]+)", summary_content, re.IGNORECASE)
        if m: return m.group(1)
        return None

    def _scan_repo_for_min_python(self, repo_root: str) -> Optional[str]:
        try:
            root = Path(repo_root)
            if not root.exists(): return None

            candidates = []
            for p in [root / "conftest.py", root / "tests"]:
                if p.exists():
                    if p.is_file(): candidates.append(p)
                    else: candidates.extend(list(p.rglob("*.py")))

            if not candidates:
                candidates = list(root.rglob("*.py"))[:500]

            for pyfile in candidates:
                try:
                    text = self._read_text(str(pyfile))
                    if any(rx.search(text) for rx in self._PY310_PATTERNS):
                        return "3.10"
                except Exception:
                    continue
        except Exception:
            pass
        return None

    def _choose_python_version(self, user_version: Optional[str], inferred_version: str) -> str:
        if not user_version: return inferred_version
        try:
            u = self._parse_major_minor(user_version)
            i = self._parse_major_minor(inferred_version)
            return user_version if u >= i else inferred_version
        except Exception:
            return user_version

    def _parse_major_minor(self, v: str) -> Tuple[int, int]:
        parts = v.strip().split(".")
        return int(parts[0]), int(parts[1])

    # ----------------------------
    # LLM + YAML post-processing
    # ----------------------------
    def _call_llm(self, prompt: str) -> str:
        response = self.client.chat.completions.create(
            model="gpt-4-turbo-preview",
            messages=[
                {"role": "system", "content": "You are a Conda expert. You ALWAYS map 'torch' to 'pytorch' and 'opencv-python' to 'opencv'. Output ONLY valid YAML."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
        )
        return response.choices[0].message.content.strip()

    def _ensure_python_dep(self, env_yaml: str, python_version: str) -> str:
        if re.search(r"^\s*-\s*python\s*=", env_yaml, re.MULTILINE):
            return env_yaml

        lines = env_yaml.splitlines()
        out = []
        inserted = False
        for idx, line in enumerate(lines):
            out.append(line)
            if not inserted and re.match(r"^\s*dependencies:\s*$", line):
                out.append(f"  - python={python_version}")
                inserted = True

        if not inserted:
            out.append("dependencies:")
            out.append(f"  - python={python_version}")

        return "\n".join(out).strip() + "\n"

    def _clean_markdown(self, content: str) -> str:
        if content.startswith("```"):
            lines = content.split("\n")
            if lines and lines[0].startswith("```"): lines = lines[1:]
            if lines and lines[-1].startswith("```"): lines = lines[:-1]
            content = "\n".join(lines)
        return content.strip()

    def _read_text(self, path: str) -> str:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()

    def save_to_file(self, content: str, output_path: str) -> None:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"Environment.yml saved to: {output_path}")