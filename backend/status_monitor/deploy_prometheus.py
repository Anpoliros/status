"""Validate, preview and atomically deploy managed Prometheus File SD inventories."""
from __future__ import annotations

import argparse
import difflib
import json
import shlex
import subprocess
import tempfile
import time
from pathlib import Path

from .collectors import file_sd
from .config import load_config, repository_path
from .collector import fetch_json, _prometheus_url

# Executed remotely with an explicit JSON input. No configuration values become code.
REMOTE = r'''
import json,os,sys,tempfile,subprocess,shutil,fcntl
from pathlib import Path
p=json.load(sys.stdin); target=Path(p['target']); operation=p['operation']
if operation=='read':
 print(json.dumps({'content':target.read_text() if target.exists() else None})); sys.exit()
content=p['content']; expected=p['expected']
current=target.read_text() if target.exists() else None
if current!=expected: raise SystemExit('Remote inventory changed since preview; retry deployment')
target.parent.mkdir(parents=True,exist_ok=True)
lock=target.with_name(target.name+'.lock').open('a')
fcntl.flock(lock,fcntl.LOCK_EX)
current=target.read_text() if target.exists() else None
if current!=expected: raise SystemExit('Remote inventory changed while waiting for deployment lock')
fd,temporary=tempfile.mkstemp(dir=target.parent,prefix='.status-staged-',suffix='.json')
backup=target.with_name(target.name+'.previous')
try:
 with os.fdopen(fd,'w') as f: f.write(content)
 os.chmod(temporary,0o644)
 # Promtool validates the actual staged file through a temporary scrape config.
 with tempfile.TemporaryDirectory() as directory:
  wrapper=Path(directory)/'check.yml'
  wrapper.write_text('scrape_configs:\n  - job_name: '+json.dumps(p['job'])+'\n    file_sd_configs:\n      - files: ['+json.dumps(temporary)+']\n')
  subprocess.run([p['promtool'],'check','config',str(wrapper)],check=True,stdout=sys.stderr)
  subprocess.run([p['promtool'],'check','config',p['config_file']],check=True,stdout=sys.stderr)
 if current is not None: shutil.copy2(target,backup)
 os.replace(temporary,target)
 print(json.dumps({'installed':True}))
finally:
 if os.path.exists(temporary): os.unlink(temporary)
'''


def run(arguments, **kwargs):
    try:
        return subprocess.run(arguments,check=True,text=True,capture_output=True,timeout=45,**kwargs)
    except subprocess.CalledProcessError as error:
        raise RuntimeError((error.stderr or error.stdout or 'Command failed').strip()) from error


def remote(source,payload):
    result = run(['ssh','-o','BatchMode=yes',source.deploy['ssh_host'],
                  'python3 -c '+shlex.quote(REMOTE)],input=json.dumps(payload))
    if result.stderr:
        print(result.stderr.strip())
    return json.loads(result.stdout)


def validate(source, tool):
    """Validate with the same promtool version as the destination."""
    local_version = run([str(tool),'--version']).stdout.splitlines()[0]
    tool_remote = source.deploy.get('promtool','/usr/bin/promtool')
    remote_version = run(['ssh','-o','BatchMode=yes',source.deploy['ssh_host'],
                          shlex.quote(tool_remote)+' --version']).stdout.splitlines()[0]
    if local_version!=remote_version:
        raise ValueError('Local and destination promtool versions differ')
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory)/'targets.json'
        target.write_text(json.dumps(file_sd(source)))
        wrapper = Path(directory)/'check.yml'
        wrapper.write_text('scrape_configs:\n  - job_name: '+json.dumps(source.job)+
                           '\n    file_sd_configs:\n      - files: ['+json.dumps(str(target))+']\n')
        result = run([str(tool),'check','config',str(wrapper)])
        print(result.stdout.strip())


def verify(source, timeout):
    expected = {(server.id,server.target) for server in source.servers}
    deadline = time.monotonic()+timeout
    while True:
        payload = fetch_json(_prometheus_url(source,'/api/v1/targets',{'state':'active'}),8)
        targets = [item for item in payload['data']['activeTargets'] if item.get('labels',{}).get('job')==source.job]
        actual = {(item['labels'].get('status_id'),item['labels'].get('instance')) for item in targets}
        if actual==expected:
            print(f'Confirmed {len(expected)} targets and stable IDs in Prometheus')
            down = [item['labels']['instance'] for item in targets if item.get('health')!='up']
            if down:
                print('Targets not currently up (inventory remains installed): '+', '.join(down))
            return
        if time.monotonic()>=deadline:
            raise RuntimeError('Inventory verification timed out; inspect remote .previous backup before retrying')
        time.sleep(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',default='configs/general.json')
    parser.add_argument('--collector',required=True)
    parser.add_argument('--promtool',required=True,help='Local promtool matching the destination version')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply',action='store_true',help='Install after validation; default only previews')
    mode.add_argument('--dry-run',action='store_true')
    parser.add_argument('--allow-empty',action='store_true',help='Explicitly allow removing all targets')
    parser.add_argument('--verify-timeout',type=int,default=30)
    args = parser.parse_args()
    config = load_config(args.config)
    source = next((item for item in config.sources if item.id==args.collector),None)
    if source is None or not source.deploy:
        raise ValueError('Collector or deployment settings not found')
    if not source.servers and not args.allow_empty:
        raise ValueError('Refusing empty inventory; use --allow-empty for intentional removal')
    validate(source,repository_path(args.promtool))
    payload = {'target':source.deploy['target_file'],'operation':'read'}
    previous = remote(source,payload)['content']
    content = json.dumps(file_sd(source),ensure_ascii=False,indent=2)+'\n'
    print(''.join(difflib.unified_diff((previous or '').splitlines(True),content.splitlines(True),
                  fromfile='remote',tofile=source.file)) or 'Inventory unchanged')
    if not args.apply:
        print('Validated preview only; no remote files changed')
        return
    if previous!=content:
        remote(source,{**payload,'operation':'install','content':content,'expected':previous,
                       'job':source.job,'promtool':source.deploy.get('promtool','/usr/bin/promtool'),
                       'config_file':source.deploy.get('config_file','/etc/prometheus/prometheus.yml')})
    verify(source,args.verify_timeout)


if __name__=='__main__':
    main()
