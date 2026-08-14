"""
Build script for Initial_Sync.exe - Fixed for older Python versions
Creates a standalone executable for initial data synchronization
"""

import os
import sys
import subprocess

def build_initial_sync_exe():
    """Build Initial_Sync.exe using PyInstaller"""
    
    print("=" * 60)
    print("Building Initial_Sync.exe")
    print("=" * 60)
    
    # Check if initial_sync.py exists
    if not os.path.exists('initial_sync.py'):
        print("ERROR: initial_sync.py not found")
        return False
    
    try:
        print("Installing PyInstaller if needed...")
        # Fixed: Use older subprocess syntax for compatibility
        result = subprocess.call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        
        if result != 0:
            print("WARNING: PyInstaller installation may have issues, continuing...")
        
        print("Building Initial_Sync.exe...")
        print("This may take several minutes...")
        
        # Build command
        cmd = [
            sys.executable, '-m', 'PyInstaller',
            '--onefile',
            '--name', 'Initial_Sync',
            '--add-data', '.env;.',
            '--add-data', 'replicator/src;replicator/src',
            '--hidden-import', 'pyodbc',
            '--hidden-import', 'dotenv',
            '--console',
            '--clean',
            '--noconfirm',
            'initial_sync.py'
        ]
        
        print("Running PyInstaller...")
        print("Command:", ' '.join(cmd))
        
        # Use older subprocess method for compatibility
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
                                 universal_newlines=True)
        stdout, stderr = process.communicate()
        
        if process.returncode == 0:
            exe_path = os.path.join('dist', 'Initial_Sync.exe')
            if os.path.exists(exe_path):
                file_size = os.path.getsize(exe_path) / (1024*1024)
                print(f"SUCCESS: Created Initial_Sync.exe ({file_size:.1f} MB)")
                
                print("\n" + "=" * 60)
                print("BUILD COMPLETED!")
                print("=" * 60)
                print("Files created:")
                print(f"  dist/Initial_Sync.exe    - Initial data sync tool")
                print("")
                print("Usage workflow:")
                print("  1. Run Initial_Sync.exe first (sync existing data)")
                print("  2. Then run CDC_Replicator.exe (continuous sync)")
                print("")
                print("This ensures no old data is missed!")
                
                return True
            else:
                print("ERROR: Executable not found after build")
                return False
        else:
            print("Build failed!")
            print("STDOUT:", stdout)
            print("STDERR:", stderr)
            return False
        
    except Exception as e:
        print(f"Build error: {e}")
        return False

def simple_build():
    """Try simple build without extra parameters"""
    try:
        print("\nTrying simple build method...")
        
        cmd = [
            sys.executable, '-m', 'PyInstaller',
            '--onefile',
            '--console',
            '--name', 'Initial_Sync',
            'initial_sync.py'
        ]
        
        print("Command:", ' '.join(cmd))
        result = subprocess.call(cmd)
        
        if result == 0:
            exe_path = os.path.join('dist', 'Initial_Sync.exe')
            if os.path.exists(exe_path):
                print("SUCCESS: Simple build completed!")
                return True
        
        return False
        
    except Exception as e:
        print(f"Simple build error: {e}")
        return False

def main():
    print("Checking Python version...")
    print(f"Python: {sys.version}")
    
    # Try main build first
    success = build_initial_sync_exe()
    
    # If failed, try simple build
    if not success:
        print("Main build failed, trying simple build...")
        success = simple_build()
    
    if success:
        print("\nInitial_Sync.exe is ready!")
        print("Note: You may need to copy .env and replicator/src folder")
        print("to the same directory as the executable for it to work.")
    else:
        print("\nAll build attempts failed.")
        print("You can still use: python initial_sync.py")

if __name__ == "__main__":
    main()
