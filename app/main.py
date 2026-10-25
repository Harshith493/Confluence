from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from .converter import parse_dxf, reconstruct, validate

app = FastAPI(title="PlanOps · CAD to Tactical")

@app.post("/api/convert")
async def convert(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".dxf"):
        raise HTTPException(400, "Upload a DXF file.")
    try: return parse_dxf(await file.read())
    except ValueError as exc: raise HTTPException(422, str(exc))

@app.post("/api/reconstruct")
async def rebuild(collection: dict):
    try: return Response(reconstruct(collection), media_type="application/dxf", headers={"Content-Disposition":"attachment; filename=reconstructed.dxf"})
    except Exception as exc: raise HTTPException(422, f"Unable to reconstruct GeoJSON: {exc}")

@app.post("/api/validate")
async def round_trip(file: UploadFile = File(...)):
    try:
        original = parse_dxf(await file.read())
        reconstructed = parse_dxf(reconstruct(original))
        return {"report": validate(original, reconstructed), "reconstructed": reconstructed}
    except Exception as exc: raise HTTPException(422, f"Unable to validate DXF: {exc}")

app.mount("/", StaticFiles(directory=Path(__file__).parent.parent / "web", html=True), name="web")
