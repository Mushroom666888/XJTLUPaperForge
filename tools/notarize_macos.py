"""Sign, notarize and staple a native .app using an existing Keychain profile."""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('app',type=Path)
    parser.add_argument('--identity',required=True,help='Developer ID Application identity')
    parser.add_argument('--keychain-profile',required=True,help='Previously configured notarytool credentials')
    args=parser.parse_args()
    if sys.platform!='darwin':raise SystemExit('Signing and notarization must run on macOS.')
    app=args.app.resolve()
    if app.suffix!='.app' or not app.is_dir():raise SystemExit('Expected a built .app directory.')
    entitlements=Path(__file__).resolve().parents[1]/'packaging/macos-entitlements.plist'
    # Sign actual nested code first, including Playwright's Node executable.
    # Do not rely on --deep to discover unconventional dependency locations.
    magic = {bytes.fromhex(value) for value in ('feedface','cefaedfe','feedfacf','cffaedfe','cafebabe','bebafeca','cafebabf','bfbafeca')}
    targets = []
    for path in app.rglob('*'):
        if path.is_symlink() or not path.is_file(): continue
        with path.open('rb') as stream:
            if stream.read(4) in magic: targets.append(path)
    targets += sorted((path for path in app.rglob('*') if path.is_dir() and not path.is_symlink()
                       and path.suffix in ('.framework','.app','.xpc')), key=lambda path:len(path.parts), reverse=True)
    for target in [*targets,app]:
        subprocess.run(['codesign','--force','--options','runtime','--timestamp','--entitlements',str(entitlements),'--sign',args.identity,str(target)],check=True)
    subprocess.run(['codesign','--verify','--deep','--strict','--verbose=2',str(app)],check=True)
    with tempfile.TemporaryDirectory(prefix='paperforge-notarize-') as temporary:
        archive=Path(temporary)/'PaperForge.zip'
        subprocess.run(['ditto','-c','-k','--sequesterRsrc','--keepParent',str(app),str(archive)],check=True)
        subprocess.run(['xcrun','notarytool','submit',str(archive),'--keychain-profile',args.keychain_profile,'--wait','--timeout','20m'],check=True)
    subprocess.run(['xcrun','stapler','staple',str(app)],check=True)
    subprocess.run(['xcrun','stapler','validate',str(app)],check=True)
    subprocess.run(['spctl','--assess','--type','execute','--verbose=2',str(app)],check=True)
    print('Signed, notarized and stapled. Recreate the release archive with build_package.py --skip-build.')


if __name__=='__main__':main()
