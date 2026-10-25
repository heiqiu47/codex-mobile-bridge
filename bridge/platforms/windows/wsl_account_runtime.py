"""Verified WSL managed-daemon inspection and bounded graceful account handoff."""
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from bridge.platforms.windows import wsl
from bridge.resources import source_text


_RUNTIME_SOURCE = r'''
import hashlib,select,signal,time
root=Path(request['home']).resolve()
def inspect():
    rows=[]; blockers=[]; helpers=[]
    unix={}
    for line in Path('/proc/net/unix').read_text().splitlines()[1:]:
        f=line.split()
        if len(f)==8 and f[3]=='00010000': unix[f[6]]=f[7]
    for p in Path('/proc').iterdir():
        if not p.name.isdigit(): continue
        try:
            if p.stat().st_uid!=uid: continue
            args=(p/'cmdline').read_bytes().split(b'\0')
            if not any(Path(os.fsdecode(a)).name in ('codex','codex.js') or b'/@openai/codex/' in a for a in args[:3] if a): continue
            exe=os.readlink(p/'exe')
            env=dict(s.split(b'=',1) for s in (p/'environ').read_bytes().split(b'\0') if b'=' in s)
            selected=Path(os.fsdecode(env.get(b'CODEX_HOME',os.fsencode(Path(os.fsdecode(env.get(b'HOME',os.fsencode(home))))/'.codex'))))
            if not selected.is_absolute(): raise ValueError('WSL Codex 配置目录无法核验')
            if selected.resolve()!=root: continue
            expected_helper=next((item for item in (request.get('daemon') or {}).get('updaters',[]) if item['pid']==int(p.name)),None)
            helper=codex_updater(p,exe,args,env,root,expected_helper)
            if helper:
                helpers.append(helper); continue
            if (not exe.startswith('/') or exe.startswith('/mnt/') or exe.endswith('.exe') or
                    Path(exe).name!='codex' or b'app-server' not in args or b'--managed-daemon' not in args):
                blockers.append('此 WSL 配置仍有独立 Codex 客户端，请先在原终端正常退出'); continue
            if any(a in (b'-c',b'--config',b'--profile',b'-p') for a in args):
                blockers.append('WSL 共享服务包含启动覆盖，无法保留原设置'); continue
            if any(env.get(name) for name in (b'OPENAI_API_KEY',b'OPENAI_BASE_URL',b'CODEX_API_KEY')):
                blockers.append('WSL 共享服务环境覆盖认证，请先在原终端处理'); continue
            sockets=[]
            for fd in (p/'fd').iterdir():
                try: target=os.readlink(fd)
                except FileNotFoundError: continue
                path=unix.get(target[8:-1]) if target.startswith('socket:[') else None
                if not path: continue
                sock=Path(path); st=sock.lstat(); parent=sock.parent.lstat()
                if (not stat.S_ISSOCK(st.st_mode) or st.st_uid!=uid or st.st_mode&0o077 or
                        sock.parent!=Path('/tmp/codex-daemon-'+str(uid)) or
                        not stat.S_ISDIR(parent.st_mode) or parent.st_uid!=uid or parent.st_mode&0o022):
                    raise ValueError('WSL 共享服务套接字归属无法核验')
                sockets.append({'socket':path,'socketDevice':st.st_dev,'socketInode':st.st_ino})
            if len(sockets)!=1: raise ValueError('WSL 共享服务控制通道无法唯一核验')
            binary=Path(exe).stat()
            rows.append({'pid':int(p.name),'startTicks':(p/'stat').read_text().rsplit(')',1)[1].split()[19],
                         'executable':exe,'executableDevice':binary.st_dev,'executableInode':binary.st_ino,
                         'user':user,'uid':uid,'home':str(root),'cwd':os.readlink(p/'cwd'),
                         'commandIdentity':hashlib.sha256((p/'cmdline').read_bytes()).hexdigest(),**sockets[0]})
        except FileNotFoundError:
            if p.exists(): blockers.append('WSL Codex 进程身份读取期间变化，暂不能切换账号')
        except ValueError as error:
            blockers.append(str(error))
        except OSError:
            blockers.append('无法完整核验 WSL Codex 进程或控制通道')
    if len(rows)>1: blockers.append('此配置存在多个共享服务，无法核验完整归属；请先在原终端处理')
    for row in rows:
        row['updaters']=[item for item in helpers if (item['executableDevice'],item['executableInode'])==(row['executableDevice'],row['executableInode'])]
    if rows and any(not any(item in row['updaters'] for row in rows) for item in helpers):
        blockers.append('WSL 更新器与共享服务的原生程序身份不符')
    return {'daemons':rows,'blockers':list(dict.fromkeys(blockers))}
action=request['action']
if action=='inspect':
    result=inspect()
elif action=='stop':
    expected=request['daemon']; found=inspect()
    if found['blockers'] or found['daemons']!=[expected]: raise ValueError('WSL 共享服务身份或任务入口已变化，账号尚未切换')
    if not hasattr(os,'pidfd_open') or not hasattr(signal,'pidfd_send_signal'): raise ValueError('此 WSL 内核不支持安全的进程身份退出')
    descriptor=os.pidfd_open(expected['pid'],0)
    try:
        found=inspect()
        if found['blockers'] or found['daemons']!=[expected]: raise ValueError('WSL 共享服务身份已变化，账号尚未切换')
        signal.pidfd_send_signal(descriptor,signal.SIGTERM,None,0)
        signal_sent=True
        ready,_,_=select.select([descriptor],[],[],8)
        if not ready: raise ValueError('WSL 共享服务未正常退出；未强制结束，账号尚未切换')
    finally: os.close(descriptor)
    found=inspect()
    if found['blockers'] or found['daemons']: raise ValueError('WSL 原服务或其他客户端仍运行，账号尚未切换')
    result={'stopped':True}
elif action=='start':
    expected=request['daemon']; found=inspect()
    if found['blockers']: raise ValueError(found['blockers'][0])
    if found['daemons']:
        if request.get('terminationRequested') and any(row['pid']==expected['pid'] and row['startTicks']==expected['startTicks'] for row in found['daemons']):
            raise ValueError('原 WSL 共享服务尚未正常退出；不会再次发送退出信号')
        if any(row['executable']!=expected['executable'] for row in found['daemons']): raise ValueError('WSL 共享服务可执行文件已变化')
    else:
        binary=Path(expected['executable']).stat()
        if (binary.st_dev,binary.st_ino)!=(expected['executableDevice'],expected['executableInode']): raise ValueError('原 WSL Codex 程序身份已变化')
        environment=os.environ.copy(); environment['CODEX_HOME']=str(root)
        if any(environment.get(key) for key in ('OPENAI_API_KEY','OPENAI_BASE_URL','CODEX_API_KEY')): raise ValueError('WSL 环境覆盖认证，未恢复共享服务')
        completed=subprocess.run([expected['executable'],'app-server','daemon','start'],env=environment,
            cwd=expected['cwd'],capture_output=True,timeout=20)
        if completed.returncode: raise ValueError('原 WSL 共享服务未正常启动，请检查原终端')
        found=inspect()
    if found['blockers'] or len(found['daemons'])!=1: raise ValueError('WSL 共享服务启动后归属尚未核验')
    actual=found['daemons'][0]
    if (actual['executableDevice'],actual['executableInode'])!=(expected['executableDevice'],expected['executableInode']):
        raise ValueError('WSL 共享服务重启后的原生程序身份已变化')
    result={'started':True,'daemon':found['daemons'][0]}
else: raise ValueError('WSL 生命周期操作无效')
'''


def _source():
    return source_text('platforms/codex_process_identity.py')+'\n'+_RUNTIME_SOURCE


def _call(distribution, user, home, action, daemon=None, termination_requested=False):
    request = {'home': home, 'action': action, 'daemon': daemon, 'terminationRequested': termination_requested}
    source = wsl._INVENTORY + '\nrequest=' + repr(request) + '\nsignal_sent=False\n'
    source += 'try:\n exec(' + repr(_source()) + ')\n print(json.dumps({"ok":True,"value":result}))\nexcept Exception as error:\n print(json.dumps({"ok":False,"error":str(error),"signalSent":signal_sent}))\n'
    result = wsl.read(distribution, source, user, timeout=30, allow_start=False)
    if not isinstance(result, dict) or not result.get('ok'):
        if action == 'stop':
            raise HandoffError(result.get('error') if isinstance(result, dict) else 'WSL 退出结果尚未核验',
                               result.get('signalSent') if isinstance(result, dict) else None)
        raise ValueError(result.get('error') if isinstance(result, dict) else 'WSL 共享服务状态无法核验')
    return result['value']


class HandoffError(ValueError):
    def __init__(self, message, signal_sent=None):
        super().__init__(message)
        self.signal_sent = signal_sent


def inspect(distribution, user, home):
    return _call(distribution, user, home, 'inspect')


def stop(distribution, user, home, daemon):
    return _call(distribution, user, home, 'stop', daemon)


def start(distribution, user, home, daemon, termination_requested=False):
    return _call(distribution, user, home, 'start', daemon, termination_requested)


class OperationLock:
    """Hold Codex's native operation flock across stop and credential commit."""
    def __init__(self, distribution, user, home):
        self.distribution, self.user, self.home = distribution, user, home
        self.process = None

    def acquire(self):
        source = 'import os,sys,json,fcntl,stat\nfrom pathlib import Path\nroot=Path('+repr(self.home)+')/"app-server-daemon"\n'
        source += '''try:
 if root.is_symlink() or root.stat().st_uid!=os.getuid() or root.stat().st_mode&0o022: raise ValueError('WSL 原生生命周期锁目录归属无效')
 path=root/'daemon.lock'
 fd=os.open(path,os.O_RDWR|os.O_NOFOLLOW)
 info=os.fstat(fd)
 if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o022: raise ValueError('WSL 原生生命周期锁归属无效')
 fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
 print(json.dumps({'locked':True}),flush=True)
 sys.stdin.buffer.read()
except Exception:
 print(json.dumps({'locked':False}),flush=True)
'''
        command = wsl.command(self.distribution, self.user)
        self.process = subprocess.Popen(command+['-u', '-c', source], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, **wsl._options())
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(self.process.stdout.readline)
        try:
            result = json.loads(future.result(timeout=6))
            if result.get('locked') is not True:
                raise ValueError('原 WSL 共享服务正被其他生命周期操作使用，请稍后重试')
        except (OSError, ValueError, TimeoutError) as error:
            self.release()
            raise ValueError('无法取得原 WSL 共享服务生命周期锁，账号尚未切换') from error
        finally:
            pool.shutdown(wait=False)

    def release(self):
        if self.process is not None:
            process, self.process = self.process, None
            process.stdin.close()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired as error:
                raise ValueError('WSL 生命周期锁释放结果尚未核验') from error
            finally:
                process.stdout.close()
