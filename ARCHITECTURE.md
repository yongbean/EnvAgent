# EnvAgent Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                          EnvAgent v2.0                          │
│              AI-Powered Conda Environment Generator              │
│                    with Auto-Fix Capabilities                    │
└─────────────────────────────────────────────────────────────────┘
```

## Component Architecture

```
┌───────────────────────────────────────────────────────────────────────┐
│                              CLI Layer                                 │
│  ┌─────────────────────────────────────────────────────────────┐     │
│  │  main.py                                                     │     │
│  │  • Argument parsing (directory, --output, --env-name, etc.) │     │
│  │  • Orchestrates the 4-step workflow                         │     │
│  │  • Implements retry loop with MAX_RETRIES=5                 │     │
│  └─────────────────────────────────────────────────────────────┘     │
└───────────────────────────────────────────────────────────────────────┘
                                  │
                                  ↓
┌───────────────────────────────────────────────────────────────────────┐
│                           Config Layer                                 │
│  ┌─────────────────────────────────────────────────────────────┐     │
│  │  config/settings.py                                          │     │
│  │  • Loads OPENAI_API_KEY from .env                           │     │
│  │  • MAX_RETRIES = 5 (strict limit)                           │     │
│  │  • Global settings instance                                  │     │
│  └─────────────────────────────────────────────────────────────┘     │
└───────────────────────────────────────────────────────────────────────┘
                                  │
                                  ↓
┌───────────────────────────────────────────────────────────────────────┐
│                          Utilities Layer                               │
│  ┌──────────────────┐  ┌──────────────┐  ┌────────────────────┐     │
│  │ LocalReader      │  │   Memory     │  │  CondaExecutor     │     │
│  │                  │  │              │  │                    │     │
│  │ • Read files     │  │ • Project    │  │ • create_env()     │     │
│  │ • .py, .txt, md  │  │   metadata   │  │ • remove_env()     │     │
│  │ • Recursive      │  │ • Packages   │  │ • check_exists()   │     │
│  │ • Exclude venv   │  │ • Versions   │  │ • Subprocess calls │     │
│  │                  │  │ • Error hist │  │ • Timeout handling │     │
│  └──────────────────┘  └──────────────┘  └────────────────────┘     │
└───────────────────────────────────────────────────────────────────────┘
                                  │
                                  ↓
┌───────────────────────────────────────────────────────────────────────┐
│                            Agents Layer                                │
│  ┌──────────────────┐  ┌──────────────┐  ┌────────────────────┐     │
│  │ ProjectAnalyzer  │  │ EnvBuilder   │  │  EnvironmentFixer  │     │
│  │                  │  │              │  │                    │     │
│  │ • GPT-4 API      │  │ • GPT-4 API  │  │ • GPT-4 API        │     │
│  │ • Analyze files  │  │ • Generate   │  │ • Diagnose errors  │     │
│  │ • Extract deps   │  │   YAML       │  │ • Generate fixes   │     │
│  │ • Detect CUDA    │  │ • Channels   │  │ • Track history    │     │
│  │ • Find versions  │  │ • Format     │  │ • Smart retry      │     │
│  └──────────────────┘  └──────────────┘  └────────────────────┘     │
└───────────────────────────────────────────────────────────────────────┘
```

## Data Flow

### Step 1: File Reading

```
Project Directory
      │
      ↓
┌─────────────┐
│ LocalReader │
└─────────────┘
      │
      ↓
files_content: Dict[str, str]
{
  "README.md": "...",
  "requirements.txt": "...",
  "src/main.py": "...",
  ...
}
```

### Step 2: Analysis

```
files_content
      │
      ↓
┌──────────────────┐
│ ProjectAnalyzer  │ ──→ OpenAI GPT-4 API
└──────────────────┘
      │
      ↓
Memory object populated:
{
  project_name: "my_project",
  python_version: "3.9",
  package_list: ["numpy==1.24.0", ...],
  cuda_version: "11.8",
  error_history: []
}
```

### Step 3: Environment Generation

```
Memory
      │
      ↓
┌──────────────┐
│ EnvBuilder   │ ──→ OpenAI GPT-4 API
└──────────────┘
      │
      ↓
environment.yml content:
name: my_project
channels:
  - conda-forge
  - defaults
dependencies:
  - python=3.9
  - pip
  - pip:
    - numpy==1.24.0
```

### Step 4: Auto-Fix Loop (NEW!)

```
environment.yml
      │
      ↓
┌─────────────────────────────────────────────────────────┐
│                   Retry Loop (MAX 8)                    │
│                                                          │
│  Attempt 1:                                              │
│    ┌──────────────────┐                                 │
│    │ CondaExecutor    │ conda env create -f yml         │
│    └──────────────────┘                                 │
│           │                                              │
│           ├─→ SUCCESS? ──→ DONE!                        │
│           │                                              │
│           └─→ FAILED                                     │
│                 │                                        │
│                 ↓                                        │
│           ┌──────────────────┐                          │
│           │ EnvironmentFixer │ ──→ GPT-4: Analyze error │
│           └──────────────────┘                          │
│                 │                                        │
│                 ↓                                        │
│           Fixed environment.yml                          │
│                 │                                        │
│                 ↓                                        │
│  Attempt 2: (repeat with fixed yml)                     │
│    ...                                                   │
│                                                          │
│  Attempt 8: Last chance                                 │
│    SUCCESS? ──→ DONE!                                   │
│    FAILED? ──→ GIVE UP                                  │
└─────────────────────────────────────────────────────────┘
```

## Error History Tracking

```
Attempt 1: PackagesNotFoundError: invalid-pkg
           ↓
        ┌────────────────────────────────┐
        │ Memory.error_history.append()  │
        │ ("PackagesNotFoundError...",   │
        │  "Removed invalid package")    │
        └────────────────────────────────┘
           ↓
Attempt 2: VersionConflict: pkg1 vs pkg2
           ↓
        ┌────────────────────────────────┐
        │ Memory.error_history.append()  │
        │ ("VersionConflict...",         │
        │  "Loosened constraints")       │
        └────────────────────────────────┘
           ↓
        Error history sent to GPT-4 for context
```

## Module Dependencies

```
main.py
  ├─→ config.settings (MAX_RETRIES, api_key)
  ├─→ utils.LocalReader
  ├─→ utils.Memory
  ├─→ utils.CondaExecutor
  ├─→ agents.ProjectAnalyzer
  ├─→ agents.EnvironmentBuilder
  └─→ agents.EnvironmentFixer

agents/project_analyzer.py
  ├─→ openai (OpenAI client)
  ├─→ config.settings (api_key)
  └─→ utils.Memory

agents/env_builder.py
  ├─→ openai (OpenAI client)
  ├─→ config.settings (api_key)
  └─→ utils.Memory

agents/env_fixer.py
  ├─→ openai (OpenAI client)
  ├─→ config.settings (api_key)
  └─→ utils.Memory

utils/conda_executor.py
  └─→ subprocess

utils/local_reader.py
  └─→ pathlib, os

utils/memory.py
  └─→ dataclasses

config/settings.py
  └─→ dotenv
```

## API Call Flow

```
User runs: python main.py /path/to/project

API Call 1: ProjectAnalyzer
  ↓
Prompt: "Analyze these files and extract dependencies..."
Files: README, requirements.txt, *.py
  ↓
Response: JSON with packages, versions, CUDA, etc.

API Call 2: EnvironmentBuilder
  ↓
Prompt: "Generate environment.yml with these specs..."
Input: Memory (packages, versions, etc.)
  ↓
Response: Valid YAML content

[If conda create fails]

API Call 3: EnvironmentFixer (Attempt 1)
  ↓
Prompt: "Fix this error: PackagesNotFoundError..."
Input: Current yml + error message + history
  ↓
Response: Fixed YAML content

[If still fails]

API Call 4: EnvironmentFixer (Attempt 2)
  ↓
[... up to 8 attempts total ...]
```

## File System Interactions

```
Input:
  /path/to/project/
    ├── README.md           (read)
    ├── requirements.txt    (read)
    ├── setup.py            (read)
    ├── pyproject.toml      (read)
    └── src/
        ├── main.py         (read)
        └── utils.py        (read)

Output:
  ./environment.yml         (write, overwrite on each retry)

Conda:
  ~/.conda/envs/
    └── my_project/         (create or fail)
```

## State Machine

```
┌──────────┐
│  START   │
└──────────┘
     │
     ↓
┌──────────────┐
│ Read Files   │
└──────────────┘
     │
     ↓
┌──────────────┐
│   Analyze    │
└──────────────┘
     │
     ↓
┌──────────────┐
│  Generate    │
└──────────────┘
     │
     ↓
   ┌─────────────────┐
   │ --no-create?    │
   └─────────────────┘
     │              │
   YES             NO
     │              │
     ↓              ↓
┌────────┐   ┌──────────────┐
│  DONE  │   │ Attempt 1    │
└────────┘   └──────────────┘
                    │
                    ↓
              ┌───────────┐
              │ Success?  │
              └───────────┘
               │         │
              YES       NO
               │         │
               ↓         ↓
          ┌────────┐  ┌──────────┐
          │  DONE  │  │ Attempt  │
          └────────┘  │  <= 5?   │
                      └──────────┘
                       │        │
                      YES      NO
                       │        │
                       ↓        ↓
                   ┌──────┐  ┌──────┐
                   │ Fix  │  │ FAIL │
                   └──────┘  └──────┘
                       │
                       ↓
                   (retry)
```

## Configuration Flow

```
.env file
  ↓
load_dotenv()
  ↓
os.getenv("OPENAI_API_KEY")
  ↓
Settings class
  ↓
settings.api_key ──→ All agents
settings.MAX_RETRIES=8 ──→ main.py retry loop
```

## Logging Architecture

```
All components log to Python logging:

main.py:
  logger.info("Analyzing project: ...")
  logger.error("Unexpected error: ...")

agents/*:
  logger.info("ProjectAnalyzer initialized")
  logger.error("Error during analysis: ...")

utils/*:
  logger.info("Creating conda environment...")
  logger.warning("Failed to read file...")

Output:
  2025-12-31 10:00:00 - __main__ - INFO - Analyzing project...
  2025-12-31 10:00:15 - agents.project_analyzer - INFO - Analysis complete
```

## Summary

EnvAgent is a **modular, well-architected system** with:

- ✅ Clear separation of concerns
- ✅ Single Responsibility Principle
- ✅ Dependency injection
- ✅ Comprehensive error handling
- ✅ Detailed logging
- ✅ Type safety
- ✅ Retry mechanism with strict limits
- ✅ AI-powered intelligent fixes

---

## Token-Efficient Architecture

EnvAgent uses a **token-efficient architecture** that processes files **individually** instead of sending all files at once.

### Key Features
- ✅ Handles ANY project size by processing files individually
- ✅ No token limits even with 1000+ files
- ✅ Efficient 6-step pipeline

## Architecture Flow

```
┌──────────────────────────────────────────────────────┐
│ Step 0: System Pre-Check (NO LLM)                   │
│ - SystemChecker validates Conda, Python, disk space │
└────────────────┬─────────────────────────────────────┘
                 ↓
┌──────────────────────────────────────────────────────┐
│ Step 1: Decision Agent (LLM)                        │
│ - DecisionAgent reads README, checks existing files │
│ - Decides: Use existing OR Proceed with analysis    │
└────────────────┬─────────────────────────────────────┘
                 ↓
┌──────────────────────────────────────────────────────┐
│ Step 2: File Filter (NO LLM)                        │
│ - FileFilter excludes irrelevant dirs/files         │
│ - Returns only .py and dependency files             │
└────────────────┬─────────────────────────────────────┘
                 ↓
┌──────────────────────────────────────────────────────┐
│ Step 3: Code Scanner Agent (LLM - one-by-one)       │
│ - CodeScannerAgent processes each file individually │
│ - Extracts: imports, versions, GPU, Python ver      │
│ - Builds dependency_summary.txt                     │
└────────────────┬─────────────────────────────────────┘
                 ↓
┌──────────────────────────────────────────────────────┐
│ Step 4: Environment Builder (LLM)                   │
│ - EnvironmentBuilder reads summary (not all files!) │
│ - Generates environment.yml                         │
└────────────────┬─────────────────────────────────────┘
                 ↓
┌──────────────────────────────────────────────────────┐
│ Step 5: Conda Executor → Fixer Loop (same as v1.0)  │
│ - Try conda env create (max 5 retries)              │
└──────────────────────────────────────────────────────┘
```

---

## Components

### 1. SystemChecker (`utils/system_checker.py`)

**Purpose**: Pre-flight validation (NO LLM calls)

**Checks**:
- ✅ Conda installed and accessible
- ✅ Python version >= 3.7
- ⚠️  Disk space >= 5GB (warning)

**Example**:
```python
checker = SystemChecker()
passed, messages = checker.run_all_checks()
if not passed:
    sys.exit(1)
```

---

### 2. DecisionAgent (`agents/decision_agent.py`)

**Purpose**: Analyze project and decide next steps

**Input**: README.md + existing environment files

**Output**:
```python
{
    "has_env_setup": true/false,
    "env_type": "conda" | "pip" | "docker" | "none",
    "env_file": "path or null",
    "proceed_with_analysis": true/false,
    "reason": "explanation"
}
```

**Early Exit**: If `environment.yml` exists → recommend using it → exit!

---

### 3. FileFilter (`utils/file_filter.py`)

**Purpose**: Rule-based file filtering (NO LLM)

**Excludes**:
- Dirs: `__pycache__`, `.git`, `venv`, `node_modules`, `tests`, `docs`
- Files: `.md`, `.txt`, `.json`, images

**Includes**:
- `.py` files
- Dependency files: `requirements.txt`, `setup.py`, `pyproject.toml`

**Example**:
```python
filter = FileFilter()
files = filter.get_relevant_files("/path/to/project")
# Returns: [Path('main.py'), Path('utils.py'), ...]
```

---

### 4. CodeScannerAgent (`agents/code_scanner.py`)

**Purpose**: Scan files **one-by-one** (KEY INNOVATION!)

**Process**:
```python
for each_file in relevant_files:
    # Small LLM call (500-1000 tokens)
    info = scan_single_file(file)
    append_to_summary(info)

# Result: dependency_summary.txt
```

**Output Format** (`dependency_summary.txt`):
```
--- requirements.txt ---
VERSION_HINT: numpy==1.24.0
VERSION_HINT: torch>=2.0.0

--- main.py ---
IMPORT: torch
GPU: yes, found torch.cuda
PYTHON: >=3.8, uses typing.Literal

--- SCAN SUMMARY ---
Files scanned: 50
Unique imports: torch, numpy, pandas
```

**Benefit**: Each LLM call is SMALL → No token limits!

---

### 5. EnvironmentBuilder

**Key Method**: `build_from_summary(summary_path, project_name, python_version)`

**Input**: `dependency_summary.txt` (compact!)

**Efficiency**:
- Processes individual files with AST → Small token usage per file
- Sends summary only → ~3K tokens total

---

## Token Efficiency

EnvAgent's architecture ensures efficient token usage:

```
Call 1: DecisionAgent.decide(README)
  Input: ~1,000 tokens

Call 2-N: CodeScannerAgent (one per file)
  Input: ~500 tokens each
  N = number of files

Call N+1: EnvironmentBuilder.build_from_summary()
  Input: ~3,000 tokens

Total: 3+N calls, ALL are small
```

**Result**: Even with 1000 files, each call is ~500 tokens → NO LIMITS!

---

## Performance

| Project Size | Processing Time |
|-------------|-----------------|
| 10 files    | ~25s            |
| 50 files    | ~60s            |
| 100 files   | ~120s           |
| 500 files   | ~600s (10 min)  |
| 1000 files  | ~1200s (20 min) |

**Scales to any project size**

---

## Usage

```bash
python main.py ./my_project

# Options
python main.py ./my_project --python-version 3.10
python main.py ./my_project --no-create
python main.py ./my_project -n custom_env
```

---

## File Structure

```
EnvAgent/
├── agents/
│   ├── decision_agent.py        # Analyzes project structure
│   ├── code_scanner.py          # Scans files individually
│   ├── env_builder.py           # Generates environment.yml
│   └── env_fixer.py             # Auto-fixes errors
├── utils/
│   ├── system_checker.py        # Pre-flight validation
│   ├── file_filter.py           # Filters relevant files
│   ├── conda_executor.py        # Executes conda commands
│   ├── dependency_collector.py  # Collects dependencies
│   ├── helpers.py               # Helper functions
│   ├── local_reader.py          # File I/O
│   └── memory.py                # State management
├── config/
│   └── settings.py              # Configuration
└── main.py                      # CLI entry point
```

---

## Key Benefits

1. **Scalability**: Handles projects of ANY size
2. **Token Efficiency**: No token limit issues
3. **Early Exit**: Stops if environment file exists
4. **System Check First**: Validates before LLM calls
5. **Debuggability**: Generates `dependency_summary.txt`
6. **Self-Healing**: Auto-fixes errors with up to 8 retries
