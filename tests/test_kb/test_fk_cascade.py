"""外键 + 级联删除测试（A2-1）。"""
from __future__ import annotations

from sqlmodel import select

from hermes_kb.database import get_session, reset_engine
from hermes_kb.models import Chunk, Document, DocumentTag, RecipeStats, Tag
from hermes_kb.rag import ImportService


def _seed_doc_with_relations(title: str = "测试文档") -> str:
    """创建一个 doc + chunk + tag + stats，返回 doc_id。"""
    svc = ImportService()
    doc_id = svc.import_text(title=title, content="一段测试内容")["doc_id"]

    with get_session() as session:
        # 加 chunk（import_text 已加，再追加一个确保有多条）
        chunk = Chunk(doc_id=doc_id, idx=99, text="额外 chunk")
        session.add(chunk)

        # 加 tag + DocumentTag
        tag = Tag(name=f"tag-{doc_id[:8]}")
        session.add(tag)
        session.commit()
        session.refresh(tag)

        link = DocumentTag(doc_id=doc_id, tag_id=tag.id)
        session.add(link)

        # 加 RecipeStats
        stat = RecipeStats(doc_id=doc_id, match_count=5, weekly_match_count=2)
        session.add(stat)

        session.commit()
    return doc_id


def test_delete_document_cascades_to_chunks():
    """删除 Document 应级联删除其所有 Chunk。"""
    doc_id = _seed_doc_with_relations()
    with get_session() as session:
        # 删除前确认有 chunk
        chunks_before = session.exec(
            select(Chunk).where(Chunk.doc_id == doc_id)
        ).all()
        assert len(chunks_before) >= 1

        # 删除 Document
        doc = session.get(Document, doc_id)
        session.delete(doc)
        session.commit()

        # 删除后 Chunk 应被级联删除
        chunks_after = session.exec(
            select(Chunk).where(Chunk.doc_id == doc_id)
        ).all()
        assert len(chunks_after) == 0


def test_delete_document_cascades_to_document_tags():
    """删除 Document 应级联删除其所有 DocumentTag。"""
    doc_id = _seed_doc_with_relations()
    with get_session() as session:
        links_before = session.exec(
            select(DocumentTag).where(DocumentTag.doc_id == doc_id)
        ).all()
        assert len(links_before) >= 1

        doc = session.get(Document, doc_id)
        session.delete(doc)
        session.commit()

        links_after = session.exec(
            select(DocumentTag).where(DocumentTag.doc_id == doc_id)
        ).all()
        assert len(links_after) == 0


def test_delete_document_cascades_to_recipe_stats():
    """删除 Document 应级联删除其 RecipeStats。"""
    doc_id = _seed_doc_with_relations()
    with get_session() as session:
        stats_before = session.exec(
            select(RecipeStats).where(RecipeStats.doc_id == doc_id)
        ).all()
        assert len(stats_before) >= 1

        doc = session.get(Document, doc_id)
        session.delete(doc)
        session.commit()

        stats_after = session.exec(
            select(RecipeStats).where(RecipeStats.doc_id == doc_id)
        ).all()
        assert len(stats_after) == 0


def test_delete_tag_cascades_to_document_tags():
    """删除 Tag 应级联删除其所有 DocumentTag。"""
    doc_id = _seed_doc_with_relations()
    with get_session() as session:
        link = session.exec(
            select(DocumentTag).where(DocumentTag.doc_id == doc_id)
        ).first()
        assert link is not None
        tag_id = link.tag_id

        tag = session.get(Tag, tag_id)
        session.delete(tag)
        session.commit()

        links_after = session.exec(
            select(DocumentTag).where(DocumentTag.tag_id == tag_id)
        ).all()
        assert len(links_after) == 0


def test_delete_document_cascades_to_chunk_vec():
    """删除 Document 应级联删除其 chunk_vec 记录。"""
    from sqlalchemy import text as sa_text

    doc_id = _seed_doc_with_relations()
    with get_session() as session:
        # 用额外添加的 chunk（idx=99，没有对应的 chunk_vec 行）插入一条 chunk_vec
        chunk = session.exec(
            select(Chunk).where(Chunk.doc_id == doc_id, Chunk.idx == 99)
        ).first()
        assert chunk is not None
        chunk_rowid = chunk.id
        session.execute(sa_text(
            "INSERT INTO chunk_vec(chunk_rowid, doc_id, vec) "
            "VALUES (:rid, :did, '[]')"
        ), {"rid": chunk_rowid, "did": doc_id})
        session.commit()

        # 删除前确认有 chunk_vec
        vec_before = session.execute(sa_text(
            "SELECT COUNT(*) FROM chunk_vec WHERE doc_id = :did"
        ), {"did": doc_id}).scalar()
        assert vec_before >= 1

        # 删除 Document
        doc = session.get(Document, doc_id)
        session.delete(doc)
        session.commit()

        # 删除后 chunk_vec 应被级联删除
        vec_after = session.execute(sa_text(
            "SELECT COUNT(*) FROM chunk_vec WHERE doc_id = :did"
        ), {"did": doc_id}).scalar()
        assert vec_after == 0


def test_foreign_key_pragma_enabled():
    """SQLite 连接应启用 foreign_keys=ON。"""
    from sqlalchemy import text as sa_text

    with get_session() as session:
        result = session.execute(sa_text("PRAGMA foreign_keys")).scalar()
        assert result == 1, f"foreign_keys should be ON, got {result}"


def test_delete_document_endpoint_cleans_all_relations(client):
    """A2-2: DELETE /api/documents/{doc_id} 端点应通过级联清理所有关联表。"""
    from sqlalchemy import text as sa_text

    from hermes_kb.database import get_session
    from hermes_kb.recipe_stats import increment_match_count

    # 创建 doc + 关联数据
    svc = ImportService()
    doc_id = svc.import_text(title="端点删除测试", content="内容")["doc_id"]

    with get_session() as session:
        chunk = Chunk(doc_id=doc_id, idx=99, text="额外")
        session.add(chunk)
        tag = Tag(name=f"ep-tag-{doc_id[:8]}")
        session.add(tag)
        session.commit()
        session.refresh(tag)
        session.add(DocumentTag(doc_id=doc_id, tag_id=tag.id))
        session.commit()

    # 加 RecipeStats
    increment_match_count(doc_id)

    # 加 chunk_vec（用 idx=99 的额外 chunk，避免与 import_text 已插入的行冲突）
    with get_session() as session:
        chunk = session.exec(
            select(Chunk).where(Chunk.doc_id == doc_id, Chunk.idx == 99)
        ).first()
        session.execute(sa_text(
            "INSERT INTO chunk_vec(chunk_rowid, doc_id, vec) "
            "VALUES (:rid, :did, '[]')"
        ), {"rid": chunk.id, "did": doc_id})
        session.commit()

    # 调端点删除
    resp = client.delete(f"/api/documents/{doc_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"

    # 验证所有关联表为空
    with get_session() as session:
        assert session.exec(select(Chunk).where(Chunk.doc_id == doc_id)).all() == []
        assert session.exec(select(DocumentTag).where(DocumentTag.doc_id == doc_id)).all() == []
        assert session.exec(select(RecipeStats).where(RecipeStats.doc_id == doc_id)).all() == []
        vec_count = session.execute(sa_text(
            "SELECT COUNT(*) FROM chunk_vec WHERE doc_id = :did"
        ), {"did": doc_id}).scalar()
        assert vec_count == 0
        # Document 本身也应不存在
        assert session.get(Document, doc_id) is None


def test_delete_tag_endpoint_cleans_document_tags(client):
    """A2-2: DELETE /api/tags/{tag_id} 端点应通过级联清理 DocumentTag。"""
    from hermes_kb.database import get_session

    svc = ImportService()
    doc_id = svc.import_text(title="标签删除测试", content="内容")["doc_id"]

    with get_session() as session:
        tag = Tag(name=f"tg-{doc_id[:8]}")
        session.add(tag)
        session.commit()
        session.refresh(tag)
        tag_id = tag.id
        session.add(DocumentTag(doc_id=doc_id, tag_id=tag_id))
        session.commit()

    # 调端点删除 tag
    resp = client.delete(f"/api/tags/{tag_id}")
    assert resp.status_code == 200

    # DocumentTag 应被级联清理
    with get_session() as session:
        links = session.exec(
            select(DocumentTag).where(DocumentTag.tag_id == tag_id)
        ).all()
        assert links == []
        # Tag 本身也应不存在
        assert session.get(Tag, tag_id) is None
