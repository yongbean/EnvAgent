#!/usr/bin/env python3
"""
EnvAgent - Automatic Conda environment.yml generator (v2.1).
Supports Monorepo & Recursive Setup Detection.
"""

import argparse
import logging
import os
import sys
from pathlib import Path

# Config & Utils
from config.settings import settings
from utils.system_checker import SystemChecker
from utils.file_filter import FileFilter
from utils import CondaExecutor, sanitize_env_name

# Agents
from agents.decision_agent import DecisionAgent
from agents.code_scanner import CodeScannerAgent
from agents.env_builder import EnvironmentBuilder  # Updated Agent
from agents.env_fixer import EnvironmentFixer

def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="EnvAgent v2.1")
    parser.add_argument("source", type=str, help="Source directory to analyze")
    parser.add_argument("destination", nargs="?", default="./env_output/environment.yml", help="Output path")
    parser.add_argument("-n", "--env-name", type=str, default=None, help="Conda env name")
    parser.add_argument("--python-version", type=str, default="3.9", help="Python version")
    parser.add_argument("--no-create", action="store_true", help="Skip creation")
    return parser.parse_args()

def validate_directory(path_str: str) -> Path:
    path = Path(path_str).resolve()
    if not path.exists() or not path.is_dir():
        print(f"Error: Invalid directory: {path}", file=sys.stderr)
        sys.exit(1)
    return path

def main() -> None:
    setup_logging()
    logger = logging.getLogger(__name__)

    print("=" * 60)
    print("EnvAgent - Conda Environment Generator v2.1")
    print("Monorepo Support & Auto-Discovery Enabled")
    print("=" * 60)
    print()

    args = parse_arguments()
    
    # 1. 루트 디렉토리 설정 (사용자 입력)
    root_path = validate_directory(args.source)
    print(f"📁 Root Project: {root_path}")

    # 2. 출력 경로 설정
    output_path = Path(args.destination).resolve()
    output_dir = output_path.parent
    os.makedirs(output_dir, exist_ok=True)

    # ------------------------------------------------------------
    # STEP 0: System Check
    # ------------------------------------------------------------
    print("🔍 Step 0/6: Checking system requirements...")
    checker = SystemChecker()
    passed, msgs = checker.run_all_checks()
    if not passed:
        print("❌ System check failed.")
        sys.exit(1)
    print("   ✓ System checks passed\n")

    # ------------------------------------------------------------
    # STEP 1: Decision Agent (Monorepo Detection)
    # ------------------------------------------------------------
    print("📋 Step 1/6: Analyzing project structure...")
    decision_agent = DecisionAgent()
    
    # [핵심] decide()가 분석 후 '진짜 경로(target_directory)'를 알려줍니다.
    decision = decision_agent.decide(str(root_path))
    
    # 루트와 다른 경로(하위 폴더)가 탐지되었는지 확인
    target_directory = Path(decision.get('target_directory', root_path))
    
    if target_directory != root_path:
        # AutoGPT처럼 하위 폴더에 진짜 코드가 있는 경우
        rel_path = target_directory.relative_to(root_path)
        print(f"   🚀 Monorepo Detected! Switching target to: ./{rel_path}")
    
    print(f"   Decision: {decision['reason']}")

    project_name = args.env_name if args.env_name else root_path.name
    sanitized_env_name = sanitize_env_name(project_name)

    # ------------------------------------------------------------
    # CASE A: Existing Files Found (setup.py, environment.yml)
    # ------------------------------------------------------------
    if decision["has_env_setup"] and not decision["proceed_with_analysis"]:
        print("\n" + "=" * 60)
        print("✅ Valid environment setup found!")
        print("=" * 60)
        print(f"Type: {decision['env_type']}")
        print(f"Target: {target_directory}")
        
        # 1. 내용 수집 (타겟 디렉토리 기준)
        collected_content = decision_agent.collect_env_files_content(str(target_directory))
        
        # 2. YAML 생성 (상대 경로 주입)
        print("\n🔨 Generating environment.yml...")
        builder = EnvironmentBuilder()
        
        env_content = builder.build_from_existing_files(
            collected_content=collected_content,
            project_name=project_name,
            python_version=args.python_version,
            target_directory=str(target_directory),  # 진짜 위치 (예: classic/original_autogpt)
            root_directory=str(root_path)            # 실행 위치 (예: AutoGPT)
        )
        
        builder.save_to_file(env_content, str(output_path))
        print(f"   ✓ Saved to: {output_path}")

    # ------------------------------------------------------------
    # CASE B: Deep Analysis Needed (Code Scanning)
    # ------------------------------------------------------------
    else:
        print(f"\n   ✓ Proceeding with code analysis in: {target_directory.name}")

        # STEP 2: Filter Files (타겟 디렉토리 기준)
        print("\n📁 Step 2/6: Filtering source files...")
        file_filter = FileFilter()
        relevant_files = file_filter.get_relevant_files(str(target_directory))
        
        if not relevant_files:
            print("   ⚠️  No Python files found in target directory.")
            sys.exit(1)
        print(f"   ✓ Found {len(relevant_files)} files to scan")

        # STEP 3: Scan Files
        print("\n🔬 Step 3/6: Scanning files for dependencies...")
        scanner = CodeScannerAgent(output_dir=str(output_dir))
        
        # CodeScannerAgent.scan_files (혹은 scan_all_files) 호출
        # 만약 CodeScannerAgent 메서드 이름이 scan_files라면 아래를 수정하세요.
        summary_path = scanner.scan_files(
            relevant_files, 
            target_directory, 
            project_name=sanitized_env_name
        )
        print(f"   ✓ Summary saved to: {summary_path.name}")

        # STEP 4: Build Environment
        print("\n🔨 Step 4/6: Generating environment.yml...")
        builder = EnvironmentBuilder()
        env_content = builder.build_from_summary(
            summary_path=str(summary_path),
            project_name=project_name,
            python_version=args.python_version,
            repo_root=str(target_directory) # 버전 추론용 경로
        )
        builder.save_to_file(env_content, str(output_path))
        print(f"   ✓ Saved to: {output_path}")

    # ------------------------------------------------------------
    # STEP 5: Create Conda Environment (Common)
    # ------------------------------------------------------------
    if not args.no_create:
        print(f"\n🚀 Step 5/6: Creating conda environment '{sanitized_env_name}'...")
        
        conda_executor = CondaExecutor()
        fixer = EnvironmentFixer()

        if conda_executor.environment_exists(sanitized_env_name):
            print(f"   ⚠️  Removing existing environment...")
            conda_executor.remove_environment(sanitized_env_name)

        current_yml = env_content
        error_history = []

        # Retry Loop
        for attempt in range(1, settings.MAX_RETRIES + 1):
            print(f"   [Attempt {attempt}/{settings.MAX_RETRIES}]")
            
            # Conda create 실행
            success, error = conda_executor.create_environment(str(output_path), sanitized_env_name)

            if success:
                print("\n" + "=" * 60)
                print("✅ SUCCESS! Environment created.")
                print("=" * 60)
                print(f"Activate: conda activate {sanitized_env_name}")
                break
            
            # 실패 시 Fixer 동작
            print(f"   ❌ Failed: {error[:200]}...")
            if attempt == settings.MAX_RETRIES:
                print("❌ Final failure.")
                sys.exit(1)
                
            print(f"   🔧 Applying fix...")
            from utils.memory import Memory
            memory = Memory()
            memory.error_history = error_history
            
            try:
                fixed_yml = fixer.fix(current_yml, error, memory)
                builder.save_to_file(fixed_yml, str(output_path))
                current_yml = fixed_yml
                error_history.append((error, "Applied fix"))
            except Exception as e:
                print(f"Fixer failed: {e}")
                sys.exit(1)
    else:
        print("\n✅ Skipped creation (--no-create).")
        print(f"Run: conda env create -f {output_path}")

if __name__ == "__main__":
    main()