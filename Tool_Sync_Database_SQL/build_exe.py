import os
import subprocess
import shutil

def build_exe():
    print("=== Starting build process ===")
    
    project_dir = os.path.abspath("replicator")
    print(f"Checking dependencies in {project_dir}...")
    try:
        subprocess.run(["poetry", "install"], check=True, cwd=project_dir)
    except subprocess.CalledProcessError as e:
        print(f"Failed to install dependencies: {e}")
        return

    entry_point = os.path.join("src", "replicator.py")
    exe_name = "CDC_Replicator"

    command = [
        "poetry", "run", "pyinstaller",
        "--onefile",
        "--name", exe_name,
        "--clean",
        "--paths", "src",
        "--hidden-import", "dotenv",
        "--hidden-import", "pyodbc",
        "--hidden-import", "db_utils",
        "--hidden-import", "setup_triggers",
        "--hidden-import", "logger",
        entry_point
    ]

    print(f"Running PyInstaller command...")

    try:
        subprocess.run(command, check=True, cwd=project_dir)
        
        source_exe = os.path.join(project_dir, "dist", f"{exe_name}.exe")
        target_exe = os.path.abspath(f"{exe_name}.exe")
        
        if os.path.exists(source_exe):
            shutil.copy2(source_exe, target_exe)
            print(f"\n[SUCCESS] Build complete!")
            print(f"Executable is ready at: {target_exe}")
            print("\nIMPORTANT: Please ensure the '.env' file is in the same folder as the EXE")
            print("otherwise it won't be able to connect to the database.")
        else:
            print(f"\n[ERROR] Build finished but could not find {source_exe}")
            
    except subprocess.CalledProcessError as e:
        print(f"\n[FAILED] Build failed with error: {e}")
        exit(1)

if __name__ == "__main__":
    build_exe()
