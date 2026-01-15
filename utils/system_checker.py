"""
System Checker - Pre-flight system validation.
No LLM calls, just pure Python checks.
"""

import logging
import shutil
import subprocess
import platform
from typing import Tuple, List

logger = logging.getLogger(__name__)


class SystemChecker:
    """Performs system pre-flight checks before starting analysis."""

    def __init__(self):
        self.os_type = platform.system()
        self.chip_info = self._get_detailed_chip_info()

    def _get_detailed_chip_info(self) -> str:
        """Detect specific chip model (e.g., Apple M4)."""
        if self.os_type == "Darwin":
            try:
                # macOS specific command to get CPU brand
                command = ["sysctl", "-n", "machdep.cpu.brand_string"]
                chip = subprocess.check_output(command).decode().strip()
                return f"macOS ({platform.machine()}) - {chip}"
            except Exception:
                return f"macOS ({platform.machine()})"
        elif self.os_type == "Linux":
             return f"Linux ({platform.machine()})"
        else:
            return f"{self.os_type} ({platform.machine()})"

    def check_nvidia_gpu(self) -> dict:
        """Check for NVIDIA GPU using nvidia-smi."""
        try:
            # query-gpu=name,driver_version,memory.total
            cmd = ["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            
            if result.returncode == 0 and result.stdout.strip():
                # Example output: "Tesla T4, 450.51.06, 15109 MiB"
                lines = result.stdout.strip().split('\n')
                gpus = []
                for line in lines:
                    parts = [x.strip() for x in line.split(',')]
                    if len(parts) >= 3:
                        gpus.append({
                            "name": parts[0],
                            "driver": parts[1],
                            "memory": parts[2]
                        })
                return {"type": "nvidia", "count": len(gpus), "details": gpus}
        except FileNotFoundError:
            pass  # nvidia-smi not found
        except Exception as e:
            logger.warning(f"NVIDIA check failed: {e}")
            
        return None

    def check_macos_gpu(self) -> dict:
        """Check for macOS GPU using system_profiler."""
        if self.os_type != "Darwin":
            return None
            
        try:
            # Get display info in JSON format (more reliable if available, but parsing text is safer across versions)
            # We'll use text parsing for broader compatibility or try JSON if possible.
            # Let's use simple grep for basic info first to avoid huge output parsing
            cmd = ["system_profiler", "SPDisplaysDataType"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                output = result.stdout
                # Naive parse for Chipset / Metal Support
                gpu_name = "Unknown"
                metal_support = "Unknown"
                
                for line in output.split('\n'):
                    line = line.strip()
                    if line.startswith("Chipset Model:"):
                        gpu_name = line.replace("Chipset Model:", "").strip()
                    elif line.startswith("Metal Support:"):
                        metal_support = line.replace("Metal Support:", "").strip()
                
                if gpu_name != "Unknown":
                    return {
                        "type": "apple_silicon" if "Apple" in gpu_name else "amd/intel", 
                        "name": gpu_name, 
                        "metal": metal_support
                    }
        except Exception as e:
            logger.warning(f"macOS GPU check failed: {e}")
            
        return None

    def check_conda_installed(self) -> Tuple[bool, str]:
        """
        Check if conda is installed and accessible.
        """
        try:
            if not (shutil.which("conda") or shutil.which("mamba")):
                return False, "Conda is not installed or not in PATH."

            result = subprocess.run(
                ["conda", "--version"],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0:
                version = result.stdout.strip()
                return True, f"Conda installed: {version}"
            else:
                return False, "Conda command failed to execute."

        except subprocess.TimeoutExpired:
            return False, "Conda command timed out."
        except Exception as e:
            logger.error(f"Error checking conda: {e}")
            return False, f"Error checking conda: {str(e)}"

    def check_disk_space(self, required_gb: float = 5.0) -> Tuple[bool, str]:
        """Check if enough disk space available."""
        try:
            stat = shutil.disk_usage(".")
            free_gb = stat.free / (1024 ** 3)

            if free_gb >= required_gb:
                return True, f"Disk space: {free_gb:.1f} GB available"
            else:
                return False, f"Insufficient disk space: {free_gb:.1f} GB available"
        except Exception:
            return True, "Disk space check skipped"

    def check_python_version(self) -> Tuple[bool, str]:
        """Check if Python version is compatible."""
        import sys
        version = sys.version_info
        version_str = f"{version.major}.{version.minor}.{version.micro}"

        if version.major >= 3 and version.minor >= 7:
            return True, f"Python {version_str}"
        else:
            return False, f"Python {version_str} is too old. Python 3.7+ required."

    def run_all_checks(self) -> Tuple[bool, List[str], dict]:
        """
        Run all system checks before starting.
        Returns: (all_passed, messages, system_info_dict)
        """
        messages = []
        all_passed = True
        
        system_details = {
            "os": self.os_type,
            "chip": self.chip_info,
            "gpu": None
        }

        # 1. System Context Detection
        messages.append(f"💻 System Detected: {self.chip_info}")
        
        # Check for GPU
        nvidia_gpu = self.check_nvidia_gpu()
        macos_gpu = self.check_macos_gpu()
        
        if nvidia_gpu:
            system_details['gpu'] = nvidia_gpu
            gpu_names = ", ".join([g['name'] for g in nvidia_gpu['details']])
            messages.append(f"   🎮 NVIDIA GPU Detected: {gpu_names} (Driver: {nvidia_gpu['details'][0]['driver']})")
        elif macos_gpu:
            system_details['gpu'] = macos_gpu
            messages.append(f"   🍎 macOS GPU Detected: {macos_gpu['name']} (Metal: {macos_gpu['metal']})")
        else:
            messages.append("   ⚠️  No active GPU detected (Code analysis will determine needs)")

        if "Apple" in self.chip_info and "M" in self.chip_info:
             messages.append("   👉 Apple Silicon detected. Will prioritize 'conda-forge'.")

        # 2. Python Check
        success, msg = self.check_python_version()
        messages.append(("✓" if success else "✗") + f" {msg}")
        if not success: all_passed = False

        # 3. Conda Check
        success, msg = self.check_conda_installed()
        messages.append(("✓" if success else "✗") + f" {msg}")
        if not success: all_passed = False

        # 4. Disk Check
        success, msg = self.check_disk_space()
        messages.append(("✓" if success else "⚠") + f" {msg}")

        return all_passed, messages, system_details