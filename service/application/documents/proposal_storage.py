"""Неизменяемая private запись: fsync до публикации, повтор только читает тот же ID."""

STORE_SCRIPT = """
import os, stat, sys, uuid
from pathlib import Path

root = Path(sys.argv[1])
root.mkdir(parents=True, exist_ok=True)
assert not root.is_symlink() and not root.parent.is_symlink()
directory = os.open(str(root), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
name = sys.argv[2] + '.json'
data = sys.stdin.buffer.read(512001)
assert len(data) <= 512000

def existing():
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    except FileNotFoundError:
        return False
    with os.fdopen(fd, 'rb') as stream:
        assert stat.S_ISREG(os.fstat(stream.fileno()).st_mode)
        assert stream.read(512001) == data
    return True

temporary = None
try:
    if existing():
        print('reused')
    else:
        assert len([entry for entry in os.listdir(directory) if entry.endswith('.json')]) < 64
        temporary = '.pending-' + uuid.uuid4().hex
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=directory)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, name, src_dir_fd=directory, dst_dir_fd=directory,
                    follow_symlinks=False)
        except FileExistsError:
            assert existing()
            print('reused')
        else:
            os.fsync(directory)
            print('stored')
finally:
    if temporary is not None:
        os.unlink(temporary, dir_fd=directory)
    os.close(directory)
"""
