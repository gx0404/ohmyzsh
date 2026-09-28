import argparse
import hashlib
import json
import lzma
import os
from pathlib import Path
import shutil
import subprocess
import urllib.request

parser=argparse.ArgumentParser()
parser.add_argument('--work',required=True)
parser.add_argument('--cache')
parser.add_argument('--verify-only',action='store_true')
parser.add_argument('--prepare-only',action='store_true')
parser.add_argument('--keyring',default='/usr/share/keyrings/ubuntu-archive-keyring.gpg')
args=parser.parse_args()
kit=Path(__file__).resolve().parent
work=Path(args.work).resolve()
work.mkdir(parents=True,exist_ok=False)
for name in ['home','tmp','downloads','logs','proot','rootfs']:(work/name).mkdir()
os.environ.update({'HOME':str(work/'home'),'TMPDIR':str(work/'tmp'),'TMPPREFIX':str(work/'tmp/zsh'),'XDG_CONFIG_HOME':str(work/'home/.config'),'XDG_CACHE_HOME':str(work/'home/.cache'),'XDG_DATA_HOME':str(work/'home/.local/share'),'XDG_STATE_HOME':str(work/'home/.local/state'),'CARGO_HOME':str(work/'home/.cargo')})
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda:source.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()
def checked(command,**kwargs):
    print('COMMAND',command,flush=True)
    subprocess.run(command,check=True,**kwargs)
def fetch(name,url,expected=None):
    target=work/'downloads'/name
    target.parent.mkdir(parents=True,exist_ok=True)
    cache=Path(args.cache)/name if args.cache else None
    if cache and cache.is_file():shutil.copyfile(cache,target)
    else:
        with urllib.request.urlopen(url,timeout=90) as source,target.open('wb') as output:shutil.copyfileobj(source,output)
    if expected:assert sha(target)==expected,(name,'SHA256 mismatch')
    return target

urls=json.loads((kit/'source-inputs-lock.json').read_text())
for entry in urls['metadata']:
    fetch(entry['file'],entry['url'],entry['sha256'])
for suite in ['focal','noble']:
    release=work/'downloads'/(suite+'-InRelease')
    checked(['gpgv','--keyring',args.keyring,str(release)])
    section=release.read_text().split('\nSHA256:\n',1)[1].split('\nSHA512:',1)[0]
    hashes={line.split()[2]:line.split()[0] for line in section.splitlines() if len(line.split())==3}
    for component in ['main','universe']:
        index=work/'downloads'/(suite+'-'+component+'-Packages.xz')
        assert sha(index)==hashes[component+'/binary-amd64/Packages.xz']
checked(['gpgv','--keyring',args.keyring,str(work/'downloads/ubuntu-base-SHA256SUMS.gpg'),str(work/'downloads/ubuntu-base-SHA256SUMS')])
base=urls['rootfs']
base_hash=next(line.split()[0] for line in (work/'downloads/ubuntu-base-SHA256SUMS').read_text().splitlines() if line.endswith('*'+base['file']))
assert base_hash==base['sha256']
base_path=fetch(base['file'],base['url'],base_hash)
package_indexes={}
for suite in ['focal','noble']:
    index={}
    for component in ['main','universe']:
        with lzma.open(work/'downloads'/(suite+'-'+component+'-Packages.xz'),'rt') as source:
            for paragraph in source.read().split('\n\n'):
                fields=dict(line.split(': ',1) for line in paragraph.splitlines() if ': ' in line and not line.startswith((' ','\t')))
                if 'Filename' in fields:index[fields['Filename']]=fields
    package_indexes[suite]=index
packages=json.loads((kit/'packages-lock.json').read_text())['packages']
for package in packages:
    fields=package_indexes[package['suite']][package['filename']]
    assert fields['SHA256']==package['sha256'] and fields['Version']==package['version']
    fetch('packages/'+package['suite']+'--'+Path(package['filename']).name,package['url'],package['sha256'])
assert sha(kit/'downloads/zsh-5.9.2.tar.xz')=='36fa734374b44783582cec09bcd67822e2f992c779ec1624ab5596df078d2f81'
assert sha(kit/'patches/zsh-5.9.2-metafied-paths.patch')=='230fc112b509bece56e97c1485b6de2ed32ca695b43af4628a697a8954a4107d'
(work/'verified.json').write_text(json.dumps({'packages':len(packages),'release_package_hash_chain':True,'rootfs_sha256':base_hash},indent=2)+'\n')
if args.verify_only:
    print('VERIFIED_ONLY',len(packages),flush=True)
    raise SystemExit(0)
checked(['tar','--no-same-owner','--exclude=./dev/*','--exclude=dev/*','-xzf',str(base_path),'-C',str(work/'rootfs')])
for package in packages:
    if package['suite']=='noble':
        checked(['dpkg-deb','-x',str(work/'downloads/packages'/('noble--'+Path(package['filename']).name)),str(work/'proot')])
(work/'rootfs/work').mkdir()
for relative in ['home/run','tmp']:(work/'rootfs/work'/relative).mkdir(parents=True,exist_ok=True)
env=os.environ.copy();env['LD_LIBRARY_PATH']=str(work/'proot/usr/lib/x86_64-linux-gnu');env['PROOT_TMP_DIR']=str(work/'tmp')
base_command=[str(work/'proot/usr/bin/proot'),'-0','-r',str(work/'rootfs'),'-b','/proc','-b','/dev','-b',str(work/'downloads/packages')+':/packages','-b',str(kit)+':/probe-input','-b',str(kit)+':/source-input','-w','/work','/usr/bin/env','-i','HOME=/work/home','TMPDIR=/work/tmp','TMPPREFIX=/work/tmp/zsh','XDG_CONFIG_HOME=/work/home/.config','XDG_CACHE_HOME=/work/home/.cache','XDG_DATA_HOME=/work/home/.local/share','XDG_STATE_HOME=/work/home/.local/state','XDG_RUNTIME_DIR=/work/home/run','CARGO_HOME=/work/home/.cargo','PATH=/usr/bin:/bin','LANG=C.UTF-8','LC_ALL=C.UTF-8','PYTHONDONTWRITEBYTECODE=1']
for script in ['populate_rootfs.sh']+([] if args.prepare_only else ['build_focal.sh']):
    with (work/'logs'/(script+'.log')).open('wb') as out:checked(base_command+['/bin/bash','/probe-input/'+script],env=env,stdout=out,stderr=subprocess.STDOUT)
print('PREPARED' if args.prepare_only else 'BUILT',work/'rootfs/work/stage-focal',flush=True)
