"""Build a native portable application, dependency inventory and integrity manifest."""
import argparse
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from version import VERSION
from runtime_paths import source_build_info


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'dist')
    parser.add_argument('--skip-build',action='store_true',help='Recreate manifests/archive after native signing')
    args=parser.parse_args();output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    if not args.skip_build:
        build_record=ROOT/'build/build-info.json'
        build_record.parent.mkdir(parents=True,exist_ok=True)
        build_record.write_text(json.dumps(source_build_info(ROOT),ensure_ascii=False,indent=2),encoding='utf-8')
        subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--clean','--distpath',str(output),
                        '--workpath',str(ROOT/'build/pyinstaller'),str(ROOT/'packaging/PaperForge.spec')],cwd=ROOT,check=True)
    bundle=output/('PaperForge.app' if sys.platform=='darwin' else 'PaperForge')
    if not bundle.is_dir():raise RuntimeError('Native application was not built.')
    # Adjacent release documents do not change a signed .app's sealed resources.
    notices=output/'release-notes';notices.mkdir(exist_ok=True)
    shutil.copy2(ROOT/'LICENSE',notices/'LICENSE')
    shutil.copy2(ROOT/'PACKAGING.md',notices/'PACKAGING.md')
    shutil.copy2(ROOT/'FIXES_2026-11-12.md',notices/'FIXES_2026-11-12.md')
    shutil.copy2(ROOT/'REVIEW_CONTINUED_2026-11-12.md',notices/'REVIEW_CONTINUED_2026-11-12.md')
    shutil.copy2(ROOT/'packaging/DESKTOP_ACCEPTANCE.md',notices/'DESKTOP_ACCEPTANCE.md')
    shutil.copy2(ROOT/'packaging/windows-clean-check.ps1',notices/'windows-clean-check.ps1')
    inventory=[];licenses=notices/'third-party-licenses';licenses.mkdir(exist_ok=True)
    for dist in sorted(metadata.distributions(),key=lambda d:d.metadata['Name'].lower()):
        name=dist.metadata['Name'];inventory.append({'name':name,'version':dist.version})
        for file in dist.files or []:
            if file.name.lower().startswith(('license','copying','notice')) and '.dist-info' in str(file):
                src=Path(dist.locate_file(file))
                if src.is_file():
                    target=licenses/name/Path(*file.parts[1:]);target.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copy2(src,target)
    try:commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    except (OSError,subprocess.SubprocessError):commit=None
    manifest={'version':VERSION,'platform':sys.platform,'architecture':platform.machine(),
              'python':platform.python_version(),'source_commit':commit,
              'source_dirty':bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip()) if commit else None,
              'dependencies':inventory,'files':{}}
    records=list(bundle.rglob('build-info.json'))
    if not records:raise RuntimeError('Package is missing its build identity.')
    manifest['build']=json.loads(records[0].read_text(encoding='utf-8'))
    if manifest['build']['version']!=VERSION:raise RuntimeError('Package version differs from the release source.')
    for path in sorted(bundle.rglob('*')):
        if path.is_file():
            with path.open('rb') as stream:
                manifest['files'][path.relative_to(output).as_posix()]=hashlib.file_digest(stream,'sha256').hexdigest()
    (notices/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    name=f'PaperForge-{VERSION}-{sys.platform}-{platform.machine()}'
    if sys.platform=='darwin':
        # ditto preserves executable modes, framework links and the signed app bundle.
        archive=output/(name+'.zip')
        subprocess.run(['ditto','-c','-k','--sequesterRsrc','--keepParent',str(bundle),str(archive)],check=True)
        with zipfile.ZipFile(archive,'a',zipfile.ZIP_DEFLATED) as zip:
            for path in sorted(notices.rglob('*')):
                if path.is_file():zip.write(path,path.relative_to(output))
    elif sys.platform=='linux':
        archive=output/(name+'.tar.gz')
        with tarfile.open(archive,'w:gz') as tar:
            tar.add(bundle,arcname=bundle.name);tar.add(notices,arcname=notices.name)
    else:
        archive=output/(name+'.zip')
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as zip:
            for folder in (bundle,notices):
                for path in sorted(folder.rglob('*')):
                    if path.is_file():zip.write(path,path.relative_to(output))
    with archive.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    archive.with_suffix(archive.suffix+'.sha256').write_text(digest+'  '+archive.name+'\n',encoding='ascii')
    print(str(archive));print('SHA256 '+digest)


if __name__=='__main__':main()
