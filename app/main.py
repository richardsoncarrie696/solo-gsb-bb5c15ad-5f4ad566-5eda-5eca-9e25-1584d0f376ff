"""FastAPI 入口：提供解析、重新编码 API 与静态前端。"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .diff import diff_results
from .mime import encode_tree, parse_message

app = FastAPI(
    title="MIME Multipart 报文检查器",
    description="按 RFC 2046 解析嵌套 multipart，编辑后按原 boundary 规则重新编码。",
    version="1.0.0",
)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


class ParseRequest(BaseModel):
    raw: str = Field(default="", description="原始报文（multipart body 或完整 MIME 报文）")
    raw_base64: str | None = Field(default=None, alias="rawBase64",
                                  description="可选：原始报文的 base64，二进制无损通道")
    content_type: str | None = Field(default=None, alias="contentType",
                                    description="可选：完整 Content-Type 头值")
    boundary: str | None = Field(default=None, description="可选：独立 boundary（可带引号）")

    model_config = {"populate_by_name": True}


class EncodeRequest(BaseModel):
    tree: dict
    include_headers: bool = Field(default=True, alias="includeHeaders")
    filename: str | None = None

    model_config = {"populate_by_name": True}


class DiffSample(BaseModel):
    tree: dict = Field(default_factory=dict, description="一份 /api/parse 返回的 tree")
    issues: list[dict] = Field(default_factory=list,
                               description="同一次解析返回的 issues（用于诊断代码对比）")


class DiffRequest(BaseModel):
    a: DiffSample
    b: DiffSample


@app.get("/api/health")
def health():
    return {"ok": True}


@app.post("/api/parse")
def api_parse(req: ParseRequest):
    result = parse_message(req.raw, req.content_type, req.boundary, req.raw_base64)
    # 解析即使有 error 也返回 200，错误体现在 issues 里；只有致命异常才 500
    return JSONResponse(result)


@app.post("/api/encode")
def api_encode(req: EncodeRequest):
    result = encode_tree(req.tree, req.include_headers)
    return JSONResponse(result)


@app.post("/api/diff")
def api_diff(req: DiffRequest):
    result = diff_results(req.a.model_dump(), req.b.model_dump())
    return JSONResponse(result)


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
