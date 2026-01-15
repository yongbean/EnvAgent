"""
Environment Fixer Agent.
Uses OpenAI GPT-4 to fix conda environment errors.
"""

import logging
import re
from openai import OpenAI

from config.settings import settings
from utils.memory import Memory
from typing import Any

logger = logging.getLogger(__name__)


class EnvironmentFixer:
    """Fixes conda environment errors using AI."""

    # -------------------------------------------------------------------------
    # 🧠 INTELLIGENT AGENT PROMPT (Context-Aware Inference)
    # -------------------------------------------------------------------------
    FIX_PROMPT = """You are an expert DevOps Engineer specializing in Python environments.
A conda environment creation FAILED.
Your goal is to fix the `environment.yml` not just by reacting to errors, but by **INFERRING the correct project context**.

### 💻 EXECUTION CONTEXT (CRITICAL)
- **Current Hardware:** {system_context}
- **Rule:** If the hardware is **Apple Silicon (M1/M2/M3/M4)**:
  1. **Conflict Resolution:** If a package fails to build or install, try switching channel to `conda-forge`.
  2. **Binary Preference:** For `dlib`, `numpy`, `scipy`, `pandas`, ALWAYS use `conda` packages (avoid pip build errors).
  3. **Python Version:** Prefer 3.10 or 3.11 over 3.9 for better ARM64 support.

## 📄 CURRENT environment.yml:
{current_yml}

## ❌ ERROR LOG:
{error_message}

## 📜 FIX HISTORY:
{error_history}

## 🧠 INTELLIGENT REASONING STRATEGY:

### 1. 🕵️‍♂️ INFER PYTHON VERSION (Dynamic & Intelligent)
- If build errors occur (`gcc`, `Python.h`, `wheel`, `Py_UNICODE`), the Python version is likely incompatible.
- **STRATEGY:** Analyze the error message to determine the best Python version:
  - If error mentions "requires python >=3.X", use that version
  - For Apple Silicon (M1/M2), try python=3.10 or python=3.11
  - **NEVER hardcode** a specific version without checking the error context
- **ACTION:** Only change Python version if there's clear evidence it will help

### 2. 🔄 PIP TO CONDA MIGRATION (Crucial for Build Errors)
- **Problem:** A package in the `- pip:` section failed to build (e.g., packages with C/C++ extensions).
- **Reason:** Pip tries to compile from source, which fails if system libs (like CMake, gcc) are missing or incompatible. Conda provides pre-compiled binaries.
- **Your Job:** **MOVE the failing package from `- pip:` to the main `dependencies:` section.**
  - Example: If `package-x` fails to build, remove it from `pip:` and add it to the top-level list.
  - Action: Remove version constraints (e.g., `package==1.2.3` -> `package`) to let Conda find the best binary.

### 3. 🧩 RESOLVE CONFLICTS (UnsatisfiableError)
- **Problem:** Specific versions (`numpy==1.21.0`) conflict with dependencies.
- **Your Job:** Identify the conflicting package and **RELAX** the constraint.
  - Action: Change `numpy==1.21.0` → `numpy` (Let the solver choose).

### 4. 🔬 BLAS/LAPACK CONFLICTS
- **Problem:** `netlib` vs `openblas` conflict.
- **STRATEGY:** Identify the conflicting package and move it to `pip:` ONLY if necessary. 
- **CRITICAL:** Keep scientific packages (`numpy`, `scipy`) in conda when possible.

### 5. 🚨 PRESERVE EDITABLE INSTALLS
- **CRITICAL:** Lines like `- -e /path/to/project` are editable installs.
- **ACTION:** NEVER modify or remove these lines. Keep them EXACTLY as-is.

## 📝 OUTPUT RULES:
1. Return **ONLY** the fixed YAML content.
2. NO Markdown code blocks (```).
3. NO Explanations or Comments.
"""

    def __init__(self):
        """Initialize the EnvironmentFixer with OpenAI client."""
        self.client = OpenAI(api_key=settings.api_key)
        logger.info("EnvironmentFixer initialized")

    def fix(self, current_yml: str, error_message: str, memory: Memory, system_context: Any = "Unknown") -> str:
        """
        Generate a fixed environment.yml based on the error.
        """
        logger.info("=" * 70)
        logger.info("🔧 FIXER AGENT STARTING DIAGNOSIS...")
        logger.info(f"   Context: {system_context}")
        logger.info("=" * 70)

        # 1. Prepare History Context
        error_history_text = "None - this is the first attempt"
        if memory.error_history:
            history_lines = []
            for i, (err, fix_desc) in enumerate(memory.error_history, 1):
                history_lines.append(f"[Attempt {i}] Fix: {fix_desc}")
                history_lines.append(f"[Attempt {i}] Error Snippet: {err[:300]}...") 
            error_history_text = "\n".join(history_lines)

        # 2. Build Prompt
        prompt = self.FIX_PROMPT.format(
            system_context=system_context, # Context Injection
            current_yml=current_yml,
            error_message=error_message,
            error_history=error_history_text
        )

        try:
            logger.info("🤖 AI is analyzing dependencies to infer the best environment configuration...")
            
            response = self.client.chat.completions.create(
                model="gpt-4-turbo-preview",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a Python Dependency Expert. ANALYZE the error message carefully. For Apple Silicon (M1/M2/M4), prioritize 'conda-forge' and binary packages. Be surgical - only change what's necessary."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.2,
            )

            fixed_yml = response.choices[0].message.content.strip()
            fixed_yml = self._clean_markdown(fixed_yml)

            # 3. Validation
            if self._are_yamls_identical(current_yml, fixed_yml):
                logger.warning("⚠️  AI suggested no changes. Engaging Rule-Based Fallback Protocol...")
                fixed_yml = self._heuristic_fallback(current_yml, error_message)

            return fixed_yml

        except Exception as e:
            logger.error(f"❌ AI Inference Failed: {e}")
            logger.info("Engaging Rule-Based Fallback Protocol...")
            return self._heuristic_fallback(current_yml, error_message)

    def _clean_markdown(self, text: str) -> str:
        if "```" in text:
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            return "\n".join(lines).strip()
        return text

    def _are_yamls_identical(self, yml1: str, yml2: str) -> bool:
        def normalize(yml):
            lines = [line.strip() for line in yml.strip().split("\n") if line.strip() and not line.strip().startswith("#")]
            return "\n".join(sorted(lines))
        return normalize(yml1) == normalize(yml2)

    def _heuristic_fallback(self, yml: str, error: str) -> str:
        """Rule-Based Fallback: When AI fails, apply aggressive hard rules."""
        logger.info("🔧 [FALLBACK] Applying Aggressive Safety Net Rules...")

        lines = yml.split('\n')
        fixed_lines = []
        in_pip_section = False

        is_build_error = any(x in error for x in ["gcc", "g++", "Python.h", "build", "wheel", "cmake"])
        is_solver_error = any(x in error for x in ["LibMambaUnsatisfiableError", "UnsatisfiableError", "conflicts"])

        for line in lines:
            stripped = line.strip()

            if stripped.startswith("- pip:"):
                in_pip_section = True
                fixed_lines.append(line)
                continue
                
            if in_pip_section and stripped and not line.startswith(" ") and not line.startswith("\t"):
                in_pip_section = False

            if not stripped or stripped.startswith("#"):
                fixed_lines.append(line)
                continue

            if stripped.startswith("- python"):
                if is_solver_error and ("=" in stripped or ">" in stripped or "<" in stripped):
                    indent = line[:line.find("-")]
                    logger.info("💡 [FALLBACK] Removing Python version constraint")
                    fixed_lines.append(f"{indent}- python")
                else:
                    fixed_lines.append(line)
                continue
            
            # Relax standard packages (non-pip)
            if (is_solver_error and not in_pip_section and stripped.startswith("-") and ":" not in stripped and not stripped.startswith("- -e")):
                indent = line[:line.find("-")]
                pkg_line = stripped[1:].strip()
                pkg_name = pkg_line
                for sep in ["==", ">=", "<=", "!=", "~=", "="]:
                    if sep in pkg_name:
                        pkg_name = pkg_name.split(sep)[0].strip()
                        break
                
                if " " in pkg_name and not pkg_name.startswith("-"):
                    pkg_name = pkg_name.split()[0].strip()

                if pkg_name:
                    new_line = f"{indent}- {pkg_name}"
                    fixed_lines.append(new_line)
                    if line.strip() != new_line.strip():
                         logger.info(f"💡 [FALLBACK] Relaxing constraint: {line.strip()} -> {pkg_name}")
                else:
                    fixed_lines.append(line)
            else:
                fixed_lines.append(line)
        
        return '\n'.join(fixed_lines)

    def extract_fix_summary(self, original_yml: str, fixed_yml: str) -> str:
        return "AI applied fixes based on error log." # Simplified for brevity