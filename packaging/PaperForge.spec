# Native builds only: each executable contains CPython and its platform libraries.
from pathlib import Path
import os
import sys
from PyInstaller.utils.hooks import collect_all, copy_metadata

root=Path(SPECPATH).parent
datas=[(str(root/'frontend'),'frontend'),(str(root/'LICENSE'),'.')]
datas.append((str(root/'build/build-info.json'),'.'))
for file in (root/'skill').rglob('*'):
    if file.is_file() and '__pycache__' not in file.parts and file.suffix in ('.md','.py','.yaml'):
        datas.append((str(file),str(file.parent.relative_to(root))))
python_license=Path(sys.base_prefix)/'LICENSE.txt'
if python_license.is_file():datas.append((str(python_license),'python-license'))
binaries=[]
hidden=['app','login','batch_capture','capture_canvas','folder_picker','doctor','synthetic_worker',
        'packaged_smoke','install','tkinter','tkinter.filedialog']
for package in ('rapidocr','onnxruntime','playwright'):
    data,binary,imports=collect_all(package)
    datas+=data;binaries+=binary;hidden+=imports
for distribution in ('rapidocr','onnxruntime','playwright','pikepdf','img2pdf','pypdf','Pillow'):
    datas+=copy_metadata(distribution)
a=Analysis([str(root/'bundle_entry.py')],pathex=[str(root)],binaries=binaries,datas=datas,
    hiddenimports=hidden,excludes=['pytest','IPython','matplotlib','torch','tensorflow','paddle'],noarchive=False)
pyz=PYZ(a.pure)
common=dict(exclude_binaries=True,debug=False,strip=False,upx=False,
            codesign_identity=os.environ.get('MACOS_SIGNING_IDENTITY'),
            entitlements_file=str(root/'packaging/macos-entitlements.plist') if sys.platform=='darwin' else None)
cli=EXE(pyz,a.scripts,[],name='paperforge-cli' if sys.platform=='win32' else 'paperforge',console=True,**common)
executables=[cli]
if sys.platform=='win32':
    gui=EXE(pyz,a.scripts,[],name='PaperForge',console=False,**common)
    executables.append(gui)
collection=COLLECT(*executables,a.binaries,a.datas,strip=False,upx=False,name='PaperForge')
if sys.platform=='darwin':
    bundle=BUNDLE(collection,name='PaperForge.app',bundle_identifier='io.github.xjtlupaperforge',
        info_plist={'CFBundleDisplayName':'PaperForge','NSHighResolutionCapable':True,
                    'CFBundleShortVersionString':'0.2.0','CFBundleVersion':'3'})
