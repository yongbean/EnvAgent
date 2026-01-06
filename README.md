# EnvAgent
Automatic Conda environment.yml generator that analyzes Python projects using AI-powered dependency analysis with automatic error fixing.
Stop manually managing conda environments! EnvAgent automatically scans your Python project, detects all dependencies, and creates a working conda environment with automatic error fixing.
Quick Start
bash# 1. Install dependencies
pip install -r requirements.txt

# 2. Add your OpenAI API key
cp .env.example .env
# Edit .env and add your API key

# 3. Run EnvAgent on your project
python main.py /path/to/your/project

# 4. Your conda environment is ready!
conda activate your_project_name
That's it! EnvAgent handles everything automatically.

Features

🔍 Smart Analysis - Scans Python files, requirements.txt, setup.py, and more
🤖 AI-Powered - Uses GPT-4 to intelligently detect dependencies and versions
📦 Conda Ready - Generates valid environment.yml files
🎯 ML/DL Support - Automatically detects CUDA/cuDNN requirements
🔄 Auto-Fix - Fixes conda errors automatically (up to 8 retry attempts)
🛠️ Error Recovery - AI diagnoses and resolves dependency conflicts
🚀 One Command - Simple CLI interface
📁 Monorepo Support - Directory Scoring algorithm finds true project root
🍎 OS-Aware - Auto-excludes CUDA packages on macOS (Apple Silicon)
🔗 Absolute Paths - Prevents path errors during conda creation
🔀 Hybrid Analysis - Combines AST parsing with config file hints

How It Works
EnvAgent v2.1 uses a hybrid multi-agent architecture that processes your project in 6 steps:

System Check - Verifies OS, Conda, Python version, and disk space
Decision Agent - Directory Scoring for Monorepo detection, finds true project root
File Filter - Selects relevant Python and config files (no LLM)
Code Scanner - AST parsing + Config Hint Extraction for dependency detection
Environment Builder - OS-aware filtering, absolute path injection, loose version constraints
Auto-Fix Loop - Creates conda environment with automatic error fixing (up to 8 retries)

Show Image
Key Innovations in v2.1
Directory Scoring Algorithm
EnvAgent intelligently identifies the true project root in complex Monorepo structures (e.g., AutoGPT, LangChain). It assigns scores based on configuration file presence:

setup.py, pyproject.toml, environment.yml: +10 points
requirements.txt: +5 points
Ties are broken by selecting the shallowest directory

Hybrid Dependency Analysis
Combines AST (Abstract Syntax Tree) parsing with Configuration Hint Extraction:

AST extracts import statements and detects GPU usage (e.g., torch.cuda)
Config hints from requirements.txt, setup.py supplement AST limitations
Cross-validation between AST results and config files improves accuracy

OS-Aware Package Filtering
Automatically detects the operating system and filters incompatible packages:

macOS (Apple Silicon): Excludes cudatoolkit, nvidia channel packages
Linux/Windows: Includes CUDA packages when GPU usage is detected

Absolute Path Injection
Converts relative paths to absolute paths in environment.yml:

Prevents FileNotFoundError when running conda env create from different directories
Prioritizes execution success over file portability

Token-Efficient Design
EnvAgent v2.1 processes files one-by-one with AST pre-filtering instead of sending everything to LLM at once, avoiding token limits and reducing API costs significantly.
Installation
Prerequisites

Python 3.8 or higher
Conda (Anaconda or Miniconda)
OpenAI API key (Get one here)

Setup Steps
bash# 1. Navigate to EnvAgent directory
cd EnvAgent

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Create .env file from template
cp .env.example .env

# 4. Edit .env and add your API key
# Replace "API KEY" with your actual OpenAI API key
nano .env   # or use your favorite editor
Your .env file should look like:
OPENAI_API_KEY=sk-proj-xxxxxxxxxxxxxxxxxxxxx
That's it! You're ready to use EnvAgent.
Usage
Basic Usage
bash# Analyze current directory and create conda environment
python main.py .

# Analyze specific project directory
python main.py /path/to/your/project

# Specify custom output location for environment.yml
python main.py /path/to/project custom_env.yml

# Specify custom environment name
python main.py /path/to/project -n my_custom_env_name

# Specify Python version (default: 3.9)
python main.py /path/to/project --python-version 3.10
Advanced Options
bash# Generate environment.yml WITHOUT creating conda environment
python main.py /path/to/project --no-create

# Output to subdirectory (auto-creates directory)
python main.py /path/to/project output/env.yml

# Combine options
python main.py ~/my_ml_project my_env.yml -n ml_project --python-version 3.9
Command Line Arguments
python main.py <source> [destination] [options]

Arguments:
  source                    Source directory to analyze (required)
  destination              Output path for environment.yml (default: ./environment.yml)

Options:
  -n, --env-name NAME      Custom environment name (default: project directory name)
  --python-version VERSION Python version to use (default: 3.9)
  --no-create             Generate yml only, skip conda environment creation
  -h, --help              Show help message
Complete Example
bash# Analyze ML project and create environment
python main.py ~/my_ml_project

# EnvAgent will:
# ✓ Check system requirements (OS, Conda, disk space)
# ✓ Find true project root (Directory Scoring)
# ✓ Analyze all Python files (AST + Config Hints)
# ✓ Detect dependencies (numpy, pandas, tensorflow, etc.)
# ✓ Filter OS-incompatible packages (CUDA on macOS)
# ✓ Generate environment.yml with absolute paths
# ✓ Create conda environment automatically
# ✓ Fix any errors that occur (up to 8 retries)

# Activate your new environment
conda activate my_ml_project

# Start coding!
python your_script.py
What Gets Analyzed?
EnvAgent scans your project for:
Configuration Files

requirements.txt - Python package requirements
setup.py - Package installation scripts
pyproject.toml - Modern Python project configs
environment.yml - Existing Conda configs
Pipfile - Pipenv configs

Source Code

All .py files in your project
Excludes: venv/, __pycache__/, .git/, node_modules/, build directories

What It Detects

Python package dependencies (numpy, pandas, tensorflow, etc.)
Package versions and version constraints
Python version requirements
CUDA/cuDNN requirements (for ML/DL projects)
GPU usage patterns (torch.cuda, tensorflow.device)
System-level dependencies
Dynamic imports (via Config Hint Extraction)

Example Output
yamlname: my_project
channels:
  - conda-forge
  - defaults
dependencies:
  - python=3.9
  - numpy
  - pandas
  - pip
  - pip:
    - tensorflow>=2.13.0
    - torch
    - -e /absolute/path/to/my_project
Note: On macOS, CUDA-related packages are automatically excluded.
Troubleshooting
"OPENAI_API_KEY not found"
Make sure you've created a .env file with your API key:
bashcp .env.example .env
# Edit .env and add: OPENAI_API_KEY=sk-your-key-here
"Directory does not exist"
Check your path is correct:
bash# Use absolute path
python main.py /full/path/to/project

# Or relative path from current directory
python main.py ../my_project
"conda: command not found"
Install Conda:

Anaconda: https://www.anaconda.com/download
Miniconda (lighter): https://docs.conda.io/en/latest/miniconda.html

Environment creation fails after 8 retries
The 8-retry limit is optimized based on experiments. If failures persist after 8 attempts, it typically indicates structural conflicts that cannot be resolved by LLM-based fixes alone.
If automatic fixing fails:

Check the generated environment.yml file
Look for incompatible version constraints
Try creating manually: conda env create -f environment.yml
Review error messages for hints
Consider removing problematic packages and installing them separately

Monorepo not detected correctly
EnvAgent uses Directory Scoring to find the true project root. If it selects the wrong directory:

Navigate directly to the correct subdirectory
Run EnvAgent from there: python main.py ./correct_subdir

CUDA packages causing errors on macOS
EnvAgent v2.1 automatically excludes CUDA packages on macOS. If you still encounter issues:

Check if any CUDA-related packages remain in environment.yml
Manually remove them and recreate the environment

API rate limits
If you hit OpenAI rate limits:

Wait a few minutes and try again
Check your API usage: https://platform.openai.com/usage
Consider upgrading your API tier

Project Structure
EnvAgent/
├── agents/                    # AI agents
│   ├── decision_agent.py     # Directory Scoring, Monorepo detection
│   ├── code_scanner.py       # AST parsing, Config Hint Extraction
│   ├── env_builder.py        # OS-aware filtering, absolute path injection
│   └── env_fixer.py          # Fixes conda errors iteratively
├── config/
│   └── settings.py           # Configuration (API keys, MAX_RETRIES=8)
├── utils/                    # Utility functions
│   ├── file_filter.py        # Filters relevant files
│   ├── conda_executor.py     # Executes conda commands
│   ├── system_checker.py     # Checks OS, Conda, disk space
│   └── helpers.py            # Helper functions
├── main.py                   # CLI entry point
├── requirements.txt          # Python dependencies
├── .env.example             # Template for API keys
└── README.md                # This file
Version History
v2.1 (Current)

Directory Scoring Algorithm for Monorepo support
OS-Aware Package Filtering (macOS CUDA exclusion)
Absolute Path Injection for reliable local package installation
Config Hint Extraction for hybrid dependency analysis
Improved error messages and troubleshooting

v2.0

Token-efficient architecture (file-by-file processing)
8-retry self-healing loop
Basic AST-based dependency detection

v1.0

Initial release
Full-code LLM analysis
Basic environment.yml generation

Contributing
Contributions are welcome! Please feel free to submit a Pull Request.
See CONTRIBUTING.md for guidelines.
Documentation

README.md - Main documentation (this file)
QUICKSTART.md - 5-minute quick start guide
USAGE.md - Detailed usage examples
ARCHITECTURE.md - Technical architecture details

