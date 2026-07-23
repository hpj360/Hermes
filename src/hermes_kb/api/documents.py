"""文档管理端点（list/import-text/upload/delete/get/raw/metadata/upload-batch）。"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlmodel import select

from hermes_kb.api.deps import get_importer, require_auth
from hermes_kb.config import get_settings
from hermes_kb.database import get_session
from hermes_kb.models import Chunk, Document, DocumentTag, Tag
from hermes_kb.rag import ImportService

router = APIRouter(prefix="/api/documents", tags=["documents"])


def _safe_upload_path(tmp_dir: Path, filename: str) -> Path:
    """构造安全的上传临时路径，防御路径穿越（CWE-22）。

    仅取 basename 剥离所有目录前缀（含 ``..``），并校验 resolve 后仍在
    ``tmp_dir`` 内。客户端 filename 不可信，禁止直接拼接。
    """
    safe_name = Path(filename).name  # 剥离所有目录前缀（含 ../）
    if not safe_name or safe_name in (".", ".."):
        raise HTTPException(status_code=400, detail="非法文件名")
    path = tmp_dir / f"{int(time.time() * 1000)}_{safe_name}"
    # 双重保险：resolve 后必须仍在 tmp_dir 内
    if not path.resolve().is_relative_to(tmp_dir.resolve()):
        raise HTTPException(status_code=400, detail="非法文件名")
    return path


class ImportTextReq(BaseModel):
    title: str = Field(..., max_length=200)
    content: str = Field(default="")
    source_type: str = Field(default="local", max_length=32)
    file_type: str = Field(default="txt", max_length=16)
    category: str = Field(default="", max_length=32)  # M2-06


# M2-06：文档元信息更新
class DocMetadataReq(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=32)
    tag_ids: list[int] | None = Field(default=None)


@router.get("", dependencies=[Depends(require_auth)])
async def list_documents(
    category: str | None = None,
    tag_id: int | None = None,
) -> dict[str, Any]:
    with get_session() as session:
        stmt = select(Document)
        if category:
            stmt = stmt.where(Document.category == category)
        if tag_id:
            # 通过 DocumentTag 关联筛选
            doc_ids_stmt = select(DocumentTag.doc_id).where(
                DocumentTag.tag_id == tag_id
            )
            # SQLModel 单列 select 直接返回值（非 tuple）
            doc_ids = list(session.exec(doc_ids_stmt).all())
            if doc_ids:
                stmt = stmt.where(Document.doc_id.in_(doc_ids))
            else:
                # 该 tag 无关联文档，直接返回空
                return {"total": 0, "items": []}
        docs = session.exec(stmt.order_by(Document.created_at.desc())).all()
        # 预取所有 tag 关联（避免 N+1）
        all_doc_ids = [d.doc_id for d in docs]
        tag_map: dict[str, list[dict]] = {d.doc_id: [] for d in docs}
        if all_doc_ids:
            tag_rows = session.exec(
                select(DocumentTag, Tag).join(
                    Tag, DocumentTag.tag_id == Tag.id, isouter=True
                ).where(DocumentTag.doc_id.in_(all_doc_ids))
            ).all()
            for dt, t in tag_rows:
                if t and dt.doc_id in tag_map:
                    tag_map[dt.doc_id].append(
                        {"id": t.id, "name": t.name, "color": t.color}
                    )
        return {
            "total": len(docs),
            "items": [
                {
                    "doc_id": d.doc_id,
                    "title": d.title,
                    "source_type": d.source_type,
                    "file_type": d.file_type,
                    "chunk_count": d.chunk_count,
                    "category": d.category,
                    "tags": tag_map.get(d.doc_id, []),
                    "created_at": d.created_at.isoformat()
                    if d.created_at
                    else None,
                }
                for d in docs
            ],
        }


@router.post("/import-text", dependencies=[Depends(require_auth)])
async def import_text(
    req: ImportTextReq, importer: ImportService = Depends(get_importer)
) -> dict[str, Any]:
    # P2-3: category 随 doc 原子落库（消除两阶段非原子）
    result = importer.import_text(
        content=req.content,
        title=req.title,
        source_type=req.source_type,
        file_type=req.file_type,
        category=req.category or "",
    )
    if req.category:
        result["category"] = req.category
    return result


@router.post("/upload", dependencies=[Depends(require_auth)])
async def upload_file(
    file: UploadFile = File(...),
    title: str | None = None,
    importer: ImportService = Depends(get_importer),
) -> dict[str, Any]:
    settings = get_settings()
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名为空")
    suffix = Path(file.filename).suffix.lower().lstrip(".")
    if suffix not in ("txt", "md", "pdf"):
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {suffix}（仅支持 txt/md/pdf）",
        )
    # 保存到临时文件后由 parser 处理（PDF 需要二进制）
    tmp_dir = Path(settings.db_path).parent / "uploads"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = _safe_upload_path(tmp_dir, file.filename)
    with tmp_path.open("wb") as f:
        f.write(await file.read())
    try:
        return importer.import_file(tmp_path, title=title or file.filename)
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


@router.delete("/{doc_id}", dependencies=[Depends(require_auth)])
async def delete_document(
    doc_id: str, importer: ImportService = Depends(get_importer)
) -> dict[str, Any]:
    ok = importer.delete_document(doc_id)
    if not ok:
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"doc_id": doc_id, "status": "deleted"}


# M2-03：文档详情
@router.get("/{doc_id}", dependencies=[Depends(require_auth)])
async def get_document(doc_id: str) -> dict[str, Any]:
    """文档详情：元信息 + 全部 chunks。"""
    with get_session() as session:
        doc = session.get(Document, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="文档不存在")
        chunks = session.exec(
            select(Chunk).where(Chunk.doc_id == doc_id).order_by(Chunk.idx)
        ).all()
        tags = session.exec(
            select(Tag).join(
                DocumentTag, DocumentTag.tag_id == Tag.id, isouter=True
            ).where(DocumentTag.doc_id == doc_id)
        ).all()
        return {
            "doc": {
                "doc_id": doc.doc_id,
                "title": doc.title,
                "source_type": doc.source_type,
                "file_type": doc.file_type,
                "chunk_count": doc.chunk_count,
                "category": doc.category,
                "content_length": len(doc.content or ""),
                "created_at": doc.created_at.isoformat() if doc.created_at else None,
            },
            "tags": [{"id": t.id, "name": t.name, "color": t.color} for t in tags],
            "chunks": [
                {
                    "rowid": c.id,
                    "idx": c.idx,
                    "text": c.text,
                    "char_start": c.char_start,
                    "char_end": c.char_end,
                }
                for c in chunks
            ],
        }


@router.get("/{doc_id}/raw", dependencies=[Depends(require_auth)])
async def get_document_raw(doc_id: str):
    """原始内容下载（MD/txt 文件）。"""
    with get_session() as session:
        doc = session.get(Document, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="文档不存在")
        ext = doc.file_type or "txt"
        media = {
            "md": "text/markdown; charset=utf-8",
            "txt": "text/plain; charset=utf-8",
            "pdf": "application/pdf",
        }.get(ext, "text/plain; charset=utf-8")
        filename = f"{doc.title}.{ext}"
        # RFC 5987：filename* 用 UTF-8 percent-encoding（兼容中文）
        # filename 用 ASCII 兜底（latin-1 不支持中文）
        filename_star = quote(filename)
        ascii_fallback = filename.encode("ascii", "ignore").decode("ascii") or "download"
        return Response(
            content=doc.content or "",
            media_type=media,
            headers={
                "Content-Disposition": (
                    f"attachment; filename=\"{ascii_fallback}\"; "
                    f"filename*=UTF-8''{filename_star}"
                )
            },
        )


# M2-06：文档元信息更新
@router.put("/{doc_id}/metadata", dependencies=[Depends(require_auth)])
async def update_doc_metadata(doc_id: str, req: DocMetadataReq) -> dict[str, Any]:
    """M2-06：更新文档元信息（title/category/tags）。"""
    with get_session() as session:
        doc = session.get(Document, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="文档不存在")
        if req.title is not None:
            if not req.title.strip():
                raise HTTPException(status_code=400, detail="标题不能为空")
            doc.title = req.title.strip()
        if req.category is not None:
            doc.category = req.category
        if req.tag_ids is not None:
            # 替换关联
            old_links = session.exec(
                select(DocumentTag).where(DocumentTag.doc_id == doc_id)
            ).all()
            for link in old_links:
                session.delete(link)
            for tid in req.tag_ids:
                # 校验 tag 存在
                if not session.get(Tag, tid):
                    continue
                session.add(DocumentTag(doc_id=doc_id, tag_id=tid))
        session.add(doc)
        session.commit()
        return {"doc_id": doc_id, "status": "updated"}


# M2-05：批量导入
@router.post("/upload-batch", dependencies=[Depends(require_auth)])
async def upload_batch(
    files: list[UploadFile] = File(...),
    importer: ImportService = Depends(get_importer),
) -> dict[str, Any]:
    """批量上传（≤ 20 文件）。"""
    settings = get_settings()
    if len(files) > 20:
        raise HTTPException(
            status_code=400,
            detail=f"单次最多 20 个文件，当前 {len(files)} 个",
        )
    results: list[dict[str, Any]] = []
    tmp_dir = Path(settings.db_path).parent / "uploads"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    for f in files:
        if not f.filename:
            results.append(
                {"filename": "", "status": "failed", "error": "文件名为空"}
            )
            continue
        suffix = Path(f.filename).suffix.lower().lstrip(".")
        if suffix not in ("txt", "md", "pdf"):
            results.append(
                {
                    "filename": f.filename,
                    "status": "failed",
                    "error": f"不支持的类型: {suffix}",
                }
            )
            continue
        tmp_path = _safe_upload_path(tmp_dir, f.filename)
        try:
            content = await f.read()
            tmp_path.write_bytes(content)
            r = importer.import_file(tmp_path, title=f.filename)
            results.append(
                {
                    "filename": f.filename,
                    "status": "imported",
                    "doc_id": r.get("doc_id"),
                    "chunk_count": r.get("chunk_count", 0),
                }
            )
        except Exception as e:
            results.append(
                {"filename": f.filename, "status": "failed", "error": str(e)}
            )
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
    ok = sum(1 for r in results if r["status"] == "imported")
    return {
        "total": len(files),
        "imported": ok,
        "failed": len(files) - ok,
        "results": results,
    }
