"""Inspect Octave compatibility and actually attempt native data-dependent entry points."""

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

OUT = Path("/work/exports")
OUT.mkdir(exist_ok=True)
SOURCE = Path("/work/source")


def save(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2) + "\n")


def run(command, name, timeout=90):
    result = subprocess.run(
        command, capture_output=True, text=True, timeout=timeout, check=False
    )
    log = OUT / (name + ".log")
    log.write_text(result.stdout + result.stderr)
    return {
        "command": command,
        "exit_code": result.returncode,
        "log": log.name,
        "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest(),
    }, result.stdout


def inspect():
    names = ["smooth3", "nanmean", "gui_mainfcn", "imread", "imwrite"]
    # These functions are actually called in the pinned MATLAB files.
    body = "\n".join(path.read_text() for path in SOURCE.glob("*.m"))
    assert all(re.search(r"\b" + name + r"\s*\(", body) for name in names)
    octave_code = (
        "pkg load nan; "
        "assert(nanmean([1,NaN,3])==2); assert(isnan(nanmean([NaN,NaN]))); "
        "s=smooth3(ones(3,3,3)); assert(all(isfinite(s(:)))); assert(abs(s(2,2,2)-1)<1e-12); "
        "imwrite(uint8([0,255;128,64]),'/work/exports/dependency-roundtrip.png'); "
        "assert(isequal(imread('/work/exports/dependency-roundtrip.png'),uint8([0,255;128,64]))); "
    )
    octave_code += (
        "names={"
        + ",".join("'" + name + "'" for name in names)
        + "}; paths=cellfun(@which,names,'UniformOutput',false); "
    )
    octave_code += "value=struct('version',version(),'names',{names},'paths',{paths}); disp(['ASPA_JSON=',jsonencode(value)]);"
    call, text = run(
        ["octave", "--no-gui", "--quiet", "--eval", octave_code], "octave-compatibility"
    )
    assert call["exit_code"] == 0
    lines = [
        x.removeprefix("ASPA_JSON=")
        for x in text.splitlines()
        if x.startswith("ASPA_JSON=")
    ]
    assert len(lines) == 1
    info = json.loads(lines[0])
    missing = [
        name
        for name, path in zip(info["names"], info["paths"], strict=True)
        if not path
    ]
    expected = [
        "PMN to MN connectivity-matrix_correctroll.xlsx",
        "NT data 01 June.xlsx",
        "PMNs R L to MNs R L normalized v5_arefshare_1222.xlsx",
        "Track_gui_PC.fig",
    ]
    absent = [name for name in expected if not (SOURCE / name).is_file()]
    raw = list(SOURCE.rglob("*.tif")) + list(SOURCE.rglob("*.mat"))
    value = {
        "status": "blocked" if missing or absent else "requires_data_validation",
        "octave": info,
        "missing_called_functions": missing,
        "missing_author_files": absent,
        "registered_raw_tiff_or_mat": len(raw),
        "native_suite": False,
        "dependency_unit_fixtures": "nanmean, smooth3 and image roundtrip only; not SCAPE measurements",
        "scope": "Alternative Octave compatibility inspection, not a validated MATLAB-equivalent workflow",
        "call": call,
    }
    save("compatibility.json", value)
    print(json.dumps(value), flush=True)
    return 1 if missing else 0


def smoke():
    python, _ = run(
        [sys.executable, str(SOURCE / "pmn_mn_analysis_forescapemanu.py")],
        "native-python-attempt",
    )
    # The original script is run without replacing its raw-data path or inputs.
    expression = "run('/work/source/SCAPE_depthcode_revised_10_22_shiftwin.m');"
    octave, _ = run(
        ["octave", "--no-gui", "--quiet", "--eval", expression], "native-octave-attempt"
    )
    value = {
        "status": "blocked" if python["exit_code"] or octave["exit_code"] else "passed",
        "attempts": [python, octave],
        "synthetic_data_supplied": False,
        "source_modified": False,
        "scope": "Actual native entry attempts; a missing file or incompatibility is preserved as a blocker, not relabeled a successful calculation",
    }
    save("native-entry-attempts.json", value)
    print(json.dumps(value), flush=True)
    return 1 if value["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit({"inspect": inspect, "smoke": smoke}[sys.argv[1]]())
