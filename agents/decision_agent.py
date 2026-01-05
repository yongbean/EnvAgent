"""
Decision Agent (Final Version).
Analyzes project structure, finds true root (Monorepo), and collects env details.
"""

import logging
import json
import re  # 👈 정규식 처리를 위해 필요
from pathlib import Path
from typing import Dict, List, Optional
from openai import OpenAI

from config.settings import settings
from agents.code_scanner import CodeScannerAgent 

logger = logging.getLogger(__name__)


class DecisionAgent:
    """Analyzes project to determine if environment files exist and next steps."""

    DECISION_PROMPT = """You are a project environment analyzer. 
Your goal is to help create a local Conda environment (python).

Read the README.md and existing file list to determine the next steps.

README.md content:
{readme_content}

Existing files found in project (at {current_path}):
{existing_files}

Analyze the README and existing files to determine:
1. Is there a valid setup file for LOCAL development (requirements.txt, environment.yml, setup.py)?
2. If only Docker/Dockerfile is present, we still need to convert it to Conda.

Output JSON format:
{{
    "has_env_setup": true/false,
    "env_type": "conda" | "pip" | "docker" | "poetry" | "none",
    "env_file": "path/to/file or null",
    "proceed_with_analysis": true/false,
    "reason": "explanation of the decision"
}}

CRITICAL RULES:
1. If 'environment.yml', 'requirements.txt' (non-empty), or 'setup.py' exists -> has_env_setup=true, proceed_with_analysis=false (We can use them directly).
2. If ONLY 'Dockerfile' or 'docker-compose.yml' exists -> has_env_setup=true (type: docker), but **proceed_with_analysis=true**. (Reason: We need to extract dependencies from Docker to create a local Conda env).
3. If no setup files are found -> proceed_with_analysis=true.
4. If you see 'setup.py' in the file list, favor 'pip' over 'docker'.
"""

    ENV_FILES = [
        'environment.yml', 'environment.yaml', 'conda.yaml',
        'requirements.txt', 'requirements-dev.txt',
        'setup.py', 'pyproject.toml', 'Pipfile',
        'Dockerfile'
    ]

    def __init__(self):
        self.client = OpenAI(api_key=settings.api_key)
        self.scanner = CodeScannerAgent(output_dir="env_agent_logs")
        logger.info("DecisionAgent initialized")

    # ----------------------------------------------------------------
    # 1. Main Decision Logic (with Monorepo Support)
    # ----------------------------------------------------------------
    def decide(self, input_path: str) -> Dict:
        logger.info(f"Analyzing project starting from: {input_path}")
        input_dir = Path(input_path).resolve()

        # [STEP 1] 진짜 프로젝트 루트 찾기
        true_root = self.scanner._find_best_project_root(input_dir)
        
        if true_root != input_dir:
            logger.info(f"🚀 Monorepo detected! Redirecting analysis to: {true_root}")
            target_directory = true_root
        else:
            target_directory = input_dir

        # [STEP 2] 진짜 루트에서 파일 검사
        existing_files = self.check_existing_env_files(str(target_directory))

        # [STEP 3] Quick Decision (LLM 없이 판단)
        for file_info in existing_files:
            fname = file_info['name']
            if file_info['size'] > 50:
                if fname in ['environment.yml', 'environment.yaml', 'conda.yaml']:
                    return self._success_response("conda", file_info['path'], target_directory)
                
                # setup.py 우선순위 높음
                if fname == 'setup.py':
                    return self._success_response("pip", file_info['path'], target_directory, 
                                                reason="Found setup.py. Will install via 'pip install -e .'")

        # [STEP 4] LLM 판단
        readme_content = self.read_readme(str(target_directory))
        files_text = "\n".join([f"- {f['name']}" for f in existing_files]) if existing_files else "None"

        try:
            response = self.client.chat.completions.create(
                model="gpt-4-turbo-preview",
                messages=[
                    {"role": "system", "content": "You are an expert Python DevOps engineer."},
                    {"role": "user", "content": self.DECISION_PROMPT.format(
                        readme_content=readme_content[:15000] if readme_content else "No README",
                        existing_files=files_text,
                        current_path=target_directory.name
                    )}
                ],
                temperature=0.1,
                response_format={"type": "json_object"}
            )
            
            result = json.loads(response.choices[0].message.content)
            result['target_directory'] = str(target_directory) # 경로 정보 추가
            
            logger.info(f"Decision made: {result.get('reason', 'No reason provided')}")
            return result

        except Exception as e:
            logger.error(f"Error in LLM decision: {e}")
            return {
                "has_env_setup": False,
                "proceed_with_analysis": True,
                "target_directory": str(target_directory),
                "reason": "Error during analysis, proceeding with fallback."
            }

    # ----------------------------------------------------------------
    # 2. Helper Methods (The missing parts restored!)
    # ----------------------------------------------------------------
    def collect_env_files_content(self, project_path: str) -> str:
        """
        Collect content from environment files for LLM analysis.
        """
        logger.info(f"Collecting content from: {project_path}")
        project_dir = Path(project_path).resolve()
        consolidated_parts = []

        for env_file in self.ENV_FILES:
            file_path = project_dir / env_file
            if file_path.exists() and file_path.is_file():
                try:
                    if file_path.stat().st_size > 0:
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()

                        if env_file == 'setup.py':
                            deps = self._extract_setup_py_deps(content)
                            if deps:
                                consolidated_parts.append(f"=== {env_file} (install_requires) ===\n{deps}\n")
                        elif env_file == 'pyproject.toml':
                            deps = self._extract_pyproject_deps(content)
                            if deps:
                                consolidated_parts.append(f"=== {env_file} (dependencies) ===\n{deps}\n")
                        else:
                            consolidated_parts.append(f"=== {env_file} ===\n{content}\n")
                except Exception as e:
                    logger.warning(f"Error reading {env_file}: {e}")

        return "\n".join(consolidated_parts) if consolidated_parts else "No environment files content found."

    def _extract_setup_py_deps(self, content: str) -> str:
        """Extract install_requires from setup.py."""
        match = re.search(r'install_requires\s*=\s*\[(.*?)\]', content, re.DOTALL)
        if match:
            deps_text = match.group(1)
            deps = re.findall(r'["\']([^"\']+)["\']', deps_text)
            return '\n'.join(deps)
        return ""

    def _extract_pyproject_deps(self, content: str) -> str:
        """Extract dependencies from pyproject.toml."""
        match = re.search(r'dependencies\s*=\s*\[(.*?)\]', content, re.DOTALL)
        if match:
            deps_text = match.group(1)
            deps = re.findall(r'["\']([^"\']+)["\']', deps_text)
            return '\n'.join(deps)
        return ""

    def check_existing_env_files(self, project_path: str) -> List[Dict[str, str]]:
        project_dir = Path(project_path).resolve()
        found_files = []
        for env_file in self.ENV_FILES:
            file_path = project_dir / env_file
            if file_path.exists():
                found_files.append({
                    "name": env_file,
                    "path": str(file_path),
                    "size": file_path.stat().st_size
                })
        return found_files

    def read_readme(self, project_path: str) -> Optional[str]:
        project_dir = Path(project_path).resolve()
        for name in ['README.md', 'README.txt', 'README']:
            p = project_dir / name
            if p.exists():
                try:
                    with open(p, 'r', encoding='utf-8', errors='ignore') as f:
                        return f.read()
                except: pass
        return None

    def _success_response(self, env_type, env_file, target_dir, reason=None):
        if not reason:
            reason = f"Found valid {env_type} configuration: {Path(env_file).name}"
        return {
            "has_env_setup": True,
            "env_type": env_type,
            "env_file": env_file,
            "proceed_with_analysis": False,
            "target_directory": str(target_dir),
            "reason": reason
        }