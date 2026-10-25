from pathlib import Path
import ezdxf
import pytest
from fastapi.testclient import TestClient
from app.converter import classify, parse_dxf, reconstruct, validate
from app.main import app

FIXTURES = Path(__file__).parent.parent / "fixtures"

def make_doc():
    doc=ezdxf.new("R2010");m=doc.modelspace()
    m.add_line((0,0),(100,0),dxfattribs={"layer":"A-WALL"})
    m.add_lwpolyline([(0,0),(50,0),(50,50)],format="xyb",dxfattribs={"layer":"DOORS"})
    m.add_circle((20,20),5,dxfattribs={"layer":"HYDRANT"})
    m.add_text("EXIT",dxfattribs={"layer":"ANNO","insert":(90,90)})
    return doc

def bytes_doc(doc):
    import io
    b=io.StringIO();doc.write(b);return b.getvalue().encode()

def test_classification_aliases_case_insensitive():
    assert classify("a-wall", "LINE")=="wall"
    assert classify("fire-hydrant", "CIRCLE")=="hydrant"
    assert classify("mystery", "SPLINE")=="other"
    assert classify("CUSTOM", "LINE", {"custom_category": ("CUSTOM",)})=="custom_category"

def test_parse_preserves_local_coordinates_and_entities():
    parsed=parse_dxf(bytes_doc(make_doc()))
    assert parsed["metadata"]["entity_count"]==4
    assert parsed["metadata"]["bbox"]==[0,0,100,90]
    assert parsed["metadata"]["coordinate_system"].startswith("Local DXF")
    assert len(parsed["features"])==4

def test_full_reconstruction_roundtrip_supported_entities():
    original=parse_dxf(bytes_doc(make_doc())); rebuilt=parse_dxf(reconstruct(original)); report=validate(original,rebuilt)
    assert len(original["features"])==4
    assert report["missing_entities"]==0 and report["extra_entities"]==0
    assert report["status"]=="PASSED"

def test_tactical_filter_is_non_destructive_for_100_features():
    base=parse_dxf(bytes_doc(make_doc())); feature=base["features"][0]
    full=[{**feature,"properties":{**feature["properties"],"tactical":i<25}} for i in range(100)]
    collection={**base,"features":full}; display=[f for f in collection["features"] if f["properties"]["tactical"]]
    assert len(display)==25 and len(collection["features"])==100
    assert parse_dxf(reconstruct(collection))["metadata"]["entity_count"]==100

def test_unsupported_entities_are_reported_and_not_passed():
    doc=make_doc();doc.modelspace().add_spline([(1,1),(3,4),(7,1)],dxfattribs={"layer":"OTHER"})
    parsed=parse_dxf(bytes_doc(doc));rebuilt=parse_dxf(reconstruct(parsed));report=validate(parsed,rebuilt)
    assert parsed["metadata"]["unsupported_count"]==1
    assert parsed["metadata"]["unsupported"]=={"SPLINE":1}
    assert report["status"]!="PASSED"

def test_bulge_round_trip():
    doc=ezdxf.new();doc.modelspace().add_lwpolyline([(0,0,1),(20,0,0)],format="xyb",dxfattribs={"layer":"WALL"})
    original=parse_dxf(bytes_doc(doc));rebuilt=parse_dxf(reconstruct(original))
    assert original["features"][0]["properties"]["has_bulges"]
    assert rebuilt["features"][0]["properties"]["bulges"][0]==pytest.approx(1)

def test_invalid_dxf_raises():
    with pytest.raises(ValueError): parse_dxf(b"not a dxf")

def test_five_synthetic_building_fixtures():
    paths=list(FIXTURES.glob("*.dxf"))
    assert len(paths)>=5
    for path in paths: assert parse_dxf(path.read_bytes())["metadata"]["entity_count"]>0

def test_api_workflow_and_invalid_upload():
    client=TestClient(app)
    r=client.post("/api/convert",files={"file":("plan.dxf",bytes_doc(make_doc()),"application/dxf")})
    assert r.status_code==200 and len(r.json()["features"])==4
    r=client.post("/api/validate",files={"file":("plan.dxf",bytes_doc(make_doc()),"application/dxf")})
    assert r.status_code==200 and r.json()["report"]["status"]=="PASSED"
    assert r.json()["report"]["original_category_counts"]==r.json()["report"]["reconstructed_category_counts"]
    assert r.json()["report"]["original_layer_counts"]==r.json()["report"]["reconstructed_layer_counts"]
    collection=r.json()["reconstructed"]
    rebuilt=client.post("/api/reconstruct",json=collection)
    assert rebuilt.status_code==200 and rebuilt.headers["content-type"]=="application/dxf"
    assert parse_dxf(rebuilt.content)["metadata"]["entity_count"]==4
    assert client.post("/api/convert",files={"file":("bad.dxf",b"broken","application/dxf")}).status_code==422
