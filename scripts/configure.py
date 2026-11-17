"""Configure this checkout with local tool and body-file paths."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from automation.config import default_config, save


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wolvenkit", type=Path, required=True)
    parser.add_argument("--blender", type=Path)
    parser.add_argument("--game", type=Path)
    for body in ("angel", "ebbrb"):
        parser.add_argument(f"--{body}-mesh", type=Path)
        parser.add_argument(f"--{body}-json", type=Path)
    args = parser.parse_args()
    config = default_config()
    config["python"]["executable"] = sys.executable
    config["python"]["version"] = sys.version.split()[0]
    updates = []
    for flag, section, key in (("wolvenkit", "wolvenkit", "cli"), ("blender", "blender", "exe")):
        value = getattr(args, flag)
        if value:
            value = value.resolve(strict=True)
            if not value.is_file():
                parser.error(f"--{flag} must name an executable file")
            config[section][key] = str(value)
    if args.game:
        game = args.game.resolve(strict=True)
        executable = game / "bin/x64/Cyberpunk2077.exe"
        if not executable.is_file():
            parser.error("--game must name a Cyberpunk 2077 installation")
        config["game"].update(dir=str(game), exe=str(executable), installed=True)
    for body in ("angel", "ebbrb"):
        mesh = getattr(args, f"{body}_mesh")
        serialized = getattr(args, f"{body}_json")
        if bool(mesh) != bool(serialized):
            parser.error(f"--{body}-mesh and --{body}-json must be supplied together")
        if mesh:
            mesh, serialized = mesh.resolve(strict=True), serialized.resolve(strict=True)
            if not mesh.is_file() or not serialized.is_file():
                parser.error("Body inputs must be files")
            profile_path = ROOT / f"config/bodies/{body.upper()}.json"
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            profile["source"].update(raw_mesh=str(mesh), mesh_json=str(serialized))
            updates.append((profile_path, profile))
    for path, profile in updates:
        path.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    save(config)
    print(ROOT / "config/workshop.json")


if __name__ == "__main__":
    main()
