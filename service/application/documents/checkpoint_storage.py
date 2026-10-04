"""Private checkpoint/source anchoring that travels with atomic project replacement."""

from __future__ import annotations

import shlex

LOCAL_CHECKPOINT = ".gpthub-document/authoring-checkpoint.json"


def checkpoint_digest_command(project: str) -> str:
    # Relative names make the anchor invariant when a project is staged elsewhere.
    # A shell pipeline can report success after find/sha256sum failed, silently
    # anchoring only the readable subset. Keep the existing digest encoding but
    # check every subprocess and reject symlinks/special files before hashing.
    script = (
        "import hashlib,os,stat,subprocess,sys\n"
        "try:\n"
        " project=sys.argv[1]\n"
        " if os.path.islink(project): raise ValueError()\n"
        " os.chdir(project)\n"
        " scan=subprocess.run(['find','.','(','-type','d','(','-name','.git','-o','-name',"
        "'.gpthub-document','-o','-name','artifacts',')',')','-prune','-o','!',"
        "'-type','d','-print0'],check=True,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)\n"
        " names=sorted(name for name in scan.stdout.split(b'\\0') if name)\n"
        " for name in names:\n"
        "  if not stat.S_ISREG(os.stat(name,follow_symlinks=False).st_mode): raise ValueError()\n"
        " inventory=b''.join(name+b'\\0' for name in names)\n"
        " hashed=subprocess.run(['xargs','-0','sha256sum'],input=inventory,check=True,"
        "stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)\n"
        " print(hashlib.sha256(hashed.stdout).hexdigest())\n"
        "except (OSError,ValueError,subprocess.CalledProcessError):\n"
        " raise SystemExit(1)\n"
    )
    return f"python -c {shlex.quote(script)} {shlex.quote(project)}"


def checkpoint_rebase_command(stage: str) -> str:
    destination = f"{stage}/{LOCAL_CHECKPOINT}"
    script = (
        "import json,os,sys; "
        "path,digest=sys.argv[1:3]; "
        "value=json.load(open(path,encoding='utf-8')); "
        "assert len(digest)==64; bytes.fromhex(digest); "
        "value['source_digest']=digest; "
        "temporary=path+'.tmp'; "
        "output=open(temporary,'w',encoding='utf-8'); "
        "json.dump(value,output,ensure_ascii=False,sort_keys=True,separators=(',',':')); "
        "output.close(); os.chmod(temporary,0o600); os.replace(temporary,path)"
    )
    return (
        f"checkpoint_digest=$({checkpoint_digest_command(stage)}); "
        f"python -c {shlex.quote(script)} {shlex.quote(destination)} "
        '"$checkpoint_digest"; '
    )
