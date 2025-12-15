"""
Build script for Microsoft Backup Suite installers
Creates standalone Windows executables using PyInstaller
"""

import subprocess
import sys
import os
import shutil
from pathlib import Path

def build_executable(script_path, name, icon=None):
    """Build a single executable"""
    print(f"\n{'='*60}")
    print(f"Building {name}...")
    print(f"{'='*60}")
    
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--console",
        f"--name={name}",
        "--clean",
        str(script_path)
    ]
    
    if icon and Path(icon).exists():
        cmd.insert(4, f"--icon={icon}")
    
    result = subprocess.run(cmd, cwd=script_path.parent)
    
    if result.returncode == 0:
        print(f"✅ Successfully built {name}")
        return True
    else:
        print(f"❌ Failed to build {name}")
        return False

def main():
    base_dir = Path(__file__).parent
    dist_dir = base_dir / "dist"
    
    # Clean up old builds
    for cleanup_dir in ["build", "__pycache__"]:
        cleanup_path = base_dir / cleanup_dir
        if cleanup_path.exists():
            shutil.rmtree(cleanup_path)
    
    print("="*60)
    print("Microsoft Backup Suite - Installer Builder")
    print("="*60)
    print(f"Python: {sys.version}")
    print(f"Base directory: {base_dir}")
    
    # Build OneDrive Backup
    onedrive_script = base_dir / "onedrive-backup" / "onedrive_backup_enhanced.py"
    if onedrive_script.exists():
        # Change to the script's directory for the build
        os.chdir(onedrive_script.parent)
        success1 = build_executable(onedrive_script, "OneDrive-Backup")
        os.chdir(base_dir)
    else:
        print(f"⚠️ OneDrive script not found: {onedrive_script}")
        success1 = False
    
    # Build OneNote Exporter
    onenote_script = base_dir / "onenote-exporter" / "onenote_exporter.py"
    if onenote_script.exists():
        os.chdir(onenote_script.parent)
        success2 = build_executable(onenote_script, "OneNote-Exporter")
        os.chdir(base_dir)
    else:
        print(f"⚠️ OneNote script not found: {onenote_script}")
        success2 = False
    
    # Create combined dist folder
    combined_dist = base_dir / "dist"
    combined_dist.mkdir(exist_ok=True)
    
    # Copy executables to main dist folder
    print(f"\n{'='*60}")
    print("Collecting executables...")
    print(f"{'='*60}")
    
    executables_found = []
    
    onedrive_exe = base_dir / "onedrive-backup" / "dist" / "OneDrive-Backup.exe"
    if onedrive_exe.exists():
        dest = combined_dist / "OneDrive-Backup.exe"
        shutil.copy2(onedrive_exe, dest)
        executables_found.append(dest)
        print(f"✅ Copied: {dest}")
    
    onenote_exe = base_dir / "onenote-exporter" / "dist" / "OneNote-Exporter.exe"
    if onenote_exe.exists():
        dest = combined_dist / "OneNote-Exporter.exe"
        shutil.copy2(onenote_exe, dest)
        executables_found.append(dest)
        print(f"✅ Copied: {dest}")
    
    # Summary
    print(f"\n{'='*60}")
    print("BUILD COMPLETE!")
    print(f"{'='*60}")
    
    if executables_found:
        print(f"\n📁 Executables are in: {combined_dist}")
        print("\nFiles created:")
        for exe in executables_found:
            size_mb = exe.stat().st_size / (1024 * 1024)
            print(f"  • {exe.name} ({size_mb:.1f} MB)")
        
        print("\n🎉 You can now distribute these .exe files!")
        print("   Users don't need Python installed to run them.")
    else:
        print("\n❌ No executables were created. Check the errors above.")
    
    return 0 if executables_found else 1

if __name__ == "__main__":
    sys.exit(main())
