"""PlanOps FastAPI Backend with DXF conversion, validation, and tactical route planning."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .converter import MAX_DXF_SIZE, parse_dxf, reconstruct, validate
from .routing import plan_route

app = FastAPI(
    title="PlanOps · CAD to Tactical Interface",
    description="Firefighter tactical floor-plan engine with CAD conversion and hazard-aware route planning.",
    version="2.0.0",
)


class RouteRequest(BaseModel):
    collection: dict[str, Any] = Field(..., description="GeoJSON FeatureCollection of the floor plan")
    start: list[float] = Field(..., description="Start [X, Y] coordinates in drawing units", min_length=2, max_length=2)
    destination: list[float] | str = Field(..., description="Destination [X, Y] coordinates or 'nearest_exit'")
    hazard_mode: Literal["avoid", "block", "ignore"] = Field("avoid", description="Policy for hazard navigation")
    hazard_penalty: float = Field(5.0, ge=1.0, le=100.0, description="Cost multiplier when traversing hazard zones")
    floor: str | None = Field(None, description="Optional floor identifier")


@app.post("/api/convert")
async def convert(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".dxf"):
        raise HTTPException(status_code=400, detail="Invalid file type. Please upload a DXF file.")
    try:
        content = await file.read()
        if len(content) > MAX_DXF_SIZE:
            raise HTTPException(status_code=400, detail=f"File exceeds maximum allowed size of {MAX_DXF_SIZE // (1024*1024)} MB.")
        return parse_dxf(content)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Unable to parse DXF: {str(exc)}")


@app.post("/api/reconstruct")
async def rebuild(collection: dict[str, Any]):
    try:
        dxf_bytes = reconstruct(collection)
        return Response(
            content=dxf_bytes,
            media_type="application/dxf",
            headers={"Content-Disposition": "attachment; filename=reconstructed.dxf"},
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Unable to reconstruct GeoJSON to DXF: {str(exc)}")


@app.post("/api/validate")
async def round_trip(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".dxf"):
        raise HTTPException(status_code=400, detail="Invalid file type. Please upload a DXF file.")
    try:
        content = await file.read()
        if len(content) > MAX_DXF_SIZE:
            raise HTTPException(status_code=400, detail=f"File exceeds maximum allowed size of {MAX_DXF_SIZE // (1024*1024)} MB.")
        original = parse_dxf(content)
        reconstructed = parse_dxf(reconstruct(original))
        return {"report": validate(original, reconstructed), "reconstructed": reconstructed}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Unable to validate DXF: {str(exc)}")


@app.post("/api/route")
async def calculate_route(request: RouteRequest):
    try:
        result = plan_route(
            collection=request.collection,
            start=request.start,
            destination=request.destination,
            hazard_mode=request.hazard_mode,
            hazard_penalty=request.hazard_penalty,
            floor=request.floor,
        )
        return JSONResponse(status_code=200, content=result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Routing calculation failed: {str(exc)}")


# Mount static web frontend
app.mount("/", StaticFiles(directory=Path(__file__).parent.parent / "web", html=True), name="web")
