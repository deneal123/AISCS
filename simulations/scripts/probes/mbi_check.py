"""Repeat supplemental MBI QC in an owned disposable Linux environment."""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from inventory import ROOT, WORK, load, save
from simctl import checked_work, phase


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    args = parser.parse_args()
    run = checked_work(args.run)
    if run.parent != WORK / "SIM-025":
        raise ValueError("Expected an owned SIM-025 run")
    core = load(run / "result.json")
    core_hash = hashlib.sha256((run / "result.json").read_bytes()).hexdigest()
    if not core["environment_volume"].get("absent"):
        raise ValueError("Wait for the original run to finish")
    if subprocess.check_output(
        ["docker", "ps", "-q", "--filter", "label=aspa.simulation.owner=simctl"],
        text=True,
    ).strip():
        raise ValueError("Another owned computation is still running")
    token = uuid.uuid4().hex[:10]
    supplement = run / ("supplement-" + token)
    probes = supplement / "probes"
    probes.mkdir(parents=True)
    output = "/work/" + supplement.name + "/exports"
    for name in ["mbi_probe.py", "mbi_metrics.py", "mbi_frequency.py"]:
        shutil.copyfile(Path(__file__).with_name(name), probes / name)
    module_path = f"sys.path.insert(0,'/work/{supplement.name}/probes')\n"
    (probes / "measurements.py").write_text(
        "import sys\nfrom pathlib import Path\n"
        + module_path
        + "import mbi_probe,mbi_metrics\n"
        + f"out=Path('{output}');out.mkdir(exist_ok=True)\n"
        + "mbi_probe.OUT=mbi_metrics.OUT=out\nmbi_probe.data();mbi_metrics.verify()\n",
        encoding="utf-8",
        newline="\n",
    )
    (probes / "frequency_worker.py").write_text(
        "import sys\nfrom pathlib import Path\n"
        + module_path
        + "import mbi_frequency\n"
        + f"mbi_frequency.OUT=Path('{output}')\nmbi_frequency.main()\n",
        encoding="utf-8",
        newline="\n",
    )
    launcher = (
        "import sys,hashlib,json,shutil,subprocess\nfrom pathlib import Path\n"
        f"sys.path.insert(0,'/work/{supplement.name}/probes')\n"
        f"out=Path('{output}');out.mkdir(exist_ok=True)\n"
        f"probes=Path('/work/{supplement.name}/probes')\n"
        "subprocess.run([sys.executable,str(probes/'measurements.py')],check=True)\n"
        "subprocess.run([sys.executable,str(probes/'frequency_worker.py')],check=True)\n"
        "values=(out/'frequency-values.csv').read_bytes()\n"
        "png=Path('/work/source/figures/clinc_spectrum_w_examples.png')\n"
        "image=png.read_bytes()\n"
        "shutil.copyfile(png,out/'frequency-first.png')\n"
        "shutil.copyfile(out/'frequency-values.csv',out/'frequency-first.csv')\n"
        "subprocess.run([sys.executable,str(probes/'frequency_worker.py')],check=True)\n"
        "assert values==(out/'frequency-values.csv').read_bytes()\n"
        "assert image==png.read_bytes()\n"
        "for name in ['clinc_spectrum.pdf','clinc_spectrum_w_examples.pdf','clinc_spectrum_w_examples.png']:\n"
        " shutil.copyfile(Path('/work/source/figures')/name,out/name)\n"
        "(out/'repeat.json').write_text(json.dumps({'status':'passed','repeat_equal':True,'csv_sha256':hashlib.sha256(values).hexdigest(),'png_sha256':hashlib.sha256(image).hexdigest(),'scope':'same fixed primary recording; adapted calculation, no new biological repetitions'})+'\\n')\n"
    )
    (probes / "verify.py").write_text(launcher, encoding="utf-8", newline="\n")
    volume = "aspa-sim-sim-025-check-env-" + token
    subprocess.run(
        [
            "docker",
            "volume",
            "create",
            "--label",
            "aspa.simulation.owner=simctl",
            "--label",
            "aspa.simulation.id=SIM-025",
            volume,
        ],
        check=True,
        capture_output=True,
    )
    profile = dict(core["profile"], _environment_volume=volume)
    install = (
        profile["install"]
        .replace(
            "/work/dependencies.lock.txt",
            f"/work/{supplement.name}/dependencies.lock.txt",
        )
        .replace(
            "/work/install-report.json", f"/work/{supplement.name}/install-report.json"
        )
    )
    stages = {
        "check_install_" + token: install,
        "check_recordings_" + token: "/work/env/bin/python -u /work/"
        + supplement.name
        + "/probes/verify.py",
    }
    profile.update(stages)
    report = {
        "status": "running",
        "phases": [],
        "core_result_sha256": core_hash,
        "scripts": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in probes.glob("*.py")
        },
        "environment_volume": {"name": volume},
    }
    receipt = supplement / "result.json"
    try:
        for stage in stages:
            print(stage, flush=True)
            item = phase({"id": "SIM-025"}, profile, stage, run, core["policy"])
            report["phases"].append(item)
            save(receipt, report)
            if item["status"] != "passed":
                break
        report["status"] = (
            "passed"
            if len(report["phases"]) == len(stages)
            and all(p["status"] == "passed" for p in report["phases"])
            else "failed"
        )
    finally:
        inspected = json.loads(
            subprocess.check_output(["docker", "volume", "inspect", volume], text=True)
        )[0]
        if inspected["Labels"].get("aspa.simulation.owner") != "simctl":
            raise ValueError("Refusing to remove an unowned volume")
        subprocess.run(
            ["docker", "volume", "rm", volume], check=True, capture_output=True
        )
        check = subprocess.run(
            ["docker", "volume", "inspect", volume],
            capture_output=True,
            text=True,
            check=False,
        )
        report["environment_volume"]["absent"] = (
            check.returncode != 0 and "no such volume" in check.stderr.lower()
        )
        if hashlib.sha256((run / "result.json").read_bytes()).hexdigest() != core_hash:
            raise ValueError("The original run receipt changed")
        save(receipt, report)
    print(receipt.relative_to(ROOT).as_posix(), report["status"], flush=True)
    if report["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
