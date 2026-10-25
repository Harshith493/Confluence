"""Small production build check and source archive packager."""
from pathlib import Path
import compileall
import zipfile

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "outputs" / "planops-cad-to-tactical.zip"

def main():
    required = [ROOT / "app" / "main.py", ROOT / "app" / "converter.py",
                ROOT / "app" / "routing.py",
                ROOT / "web" / "index.html", ROOT / "web" / "app.js",
                ROOT / "web" / "styles.css", ROOT / "app" / "classification.json",
                ROOT / "README.md"]
    missing = [str(p.relative_to(ROOT)) for p in required if not p.is_file()]
    if missing:
        raise SystemExit("Missing build inputs: " + ", ".join(missing))
    if not compileall.compile_dir(str(ROOT / "app"), quiet=1):
        raise SystemExit("Python source compilation failed")
    fixtures = sorted((ROOT / "fixtures").glob("*.dxf"))
    if len(fixtures) < 5:
        raise SystemExit(f"Expected at least five DXF fixtures, found {len(fixtures)}")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    candidates = [*ROOT.glob("app/*"), *ROOT.glob("web/*"), *ROOT.glob("tests/*.py"),
                  *ROOT.glob("scripts/*.py"), *fixtures, ROOT / "README.md",
                  ROOT / "requirements.txt", ROOT / "pyproject.toml"]
    paths = [path for path in candidates if path.is_file()]
    with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            archive.write(path, Path("planops-cad-to-tactical") / path.relative_to(ROOT))
    print(f"Build successful: {len(paths)} project files -> {OUTPUT}")

if __name__ == "__main__":
    main()
