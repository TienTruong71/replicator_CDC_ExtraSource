"""
Build script to create CDC_Replicator.exe
This replaces the old executable with our new multi-source version
"""

import os
import sys
import subprocess

def install_pyinstaller():
    """Install PyInstaller if not available"""
    try:
        import PyInstaller
        print("PyInstaller: OK")
        return True
    except ImportError:
        print("Installing PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        print("PyInstaller installed successfully")
        return True

def create_spec_file():
    """Create PyInstaller spec file for better control"""
    spec_content = '''
# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

# Add all source files
a = Analysis(
    ['auto_setup.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('.env', '.'),
        ('replicator/src/*.py', 'replicator/src/'),
    ],
    hiddenimports=[
        'pyodbc',
        'dotenv',
        'decimal',
        'threading',
        'collections',
        'hashlib',
        'json',
        'datetime',
        'time',
        'os',
        'sys'
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='CDC_Replicator',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
'''
    
    with open('CDC_Replicator.spec', 'w', encoding='utf-8') as f:
        f.write(spec_content)
    
    print("Created CDC_Replicator.spec")

def build_executable():
    """Build the executable using PyInstaller"""
    try:
        print("Building CDC_Replicator.exe...")
        print("This may take several minutes...")
        
        # Build using spec file
        cmd = [
            sys.executable, '-m', 'PyInstaller',
            '--clean',
            '--noconfirm',
            'CDC_Replicator.spec'
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            print("Build completed successfully!")
            
            # Check if exe exists
            exe_path = os.path.join('dist', 'CDC_Replicator.exe')
            if os.path.exists(exe_path):
                file_size = os.path.getsize(exe_path) / (1024*1024)  # MB
                print(f"Created: {exe_path}")
                print(f"Size: {file_size:.1f} MB")
                return True
            else:
                print("ERROR: Executable not found after build")
                return False
        else:
            print("Build failed!")
            print("STDOUT:", result.stdout)
            print("STDERR:", result.stderr)
            return False
            
    except Exception as e:
        print(f"Build error: {e}")
        return False

def create_simple_build():
    """Create simple one-file executable"""
    try:
        print("Creating simple build...")
        
        cmd = [
            sys.executable, '-m', 'PyInstaller',
            '--onefile',
            '--name', 'CDC_Replicator',
            '--add-data', '.env;.',
            '--add-data', 'replicator/src;replicator/src',
            '--hidden-import', 'pyodbc',
            '--hidden-import', 'dotenv',
            '--hidden-import', 'uuid',
            '--console',
            'auto_setup.py'
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            exe_path = os.path.join('dist', 'CDC_Replicator.exe')
            if os.path.exists(exe_path):
                file_size = os.path.getsize(exe_path) / (1024*1024)
                print(f"SUCCESS: Created CDC_Replicator.exe ({file_size:.1f} MB)")
                return True
        
        print("Simple build failed:", result.stderr)
        return False
        
    except Exception as e:
        print(f"Simple build error: {e}")
        return False

def main():
    print("=" * 60)
    print("CDC Replicator - Build to Executable")
    print("=" * 60)
    
    # Check current directory
    if not os.path.exists('auto_setup.py'):
        print("ERROR: auto_setup.py not found")
        print("Please run this from the tool_sync_dimenson_extra directory")
        return False
    
    # Install PyInstaller
    if not install_pyinstaller():
        return False
    
    # Try simple build first
    print("\nAttempting simple build...")
    if create_simple_build():
        print("\n" + "=" * 60)
        print("BUILD SUCCESSFUL!")
        print("=" * 60)
        print("Your new CDC_Replicator.exe is ready in the 'dist' folder")
        print("")
        print("Usage:")
        print("  CDC_Replicator.exe                    # Auto setup and run")
        print("  CDC_Replicator.exe --manual           # Manual mode")
        print("")
        print("The exe includes:")
        print("  - Auto setup (triggers, initial sync)")
        print("  - Multi-source support") 
        print("  - Insert-only mode with deduplication")
        print("  - Crash recovery")
        print("  - Performance optimizations")
        return True
    
    # If simple build fails, try advanced build
    print("\nSimple build failed, trying advanced build...")
    create_spec_file()
    
    if build_executable():
        print("Advanced build successful!")
        return True
    
    print("All build attempts failed.")
    print("You may need to:")
    print("1. Install Microsoft Visual C++ Redistributable")
    print("2. Install Python development headers")
    print("3. Check that all dependencies are installed")
    
    return False

if __name__ == "__main__":
    main()
