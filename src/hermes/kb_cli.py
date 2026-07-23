"""hermes-kb CLI：知识库管理工具。

子命令：
  serve        启动 API 服务
  import-text  导入纯文本
  import-file  导入 txt/md/pdf 文件
  list-docs    列出所有文档
  delete-doc   删除指定文档
  ask          提问（同步输出答案）
  seed         导入 5 篇酒类种子知识
  health       健康检查
  reset        清空数据库（需 --force）

设计：直接 in-process 调用 ImportService / RAGEngine，无需 HTTP。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# 子命令实现
# ---------------------------------------------------------------------------
def cmd_serve(args: argparse.Namespace) -> int:
    """启动 uvicorn 服务。"""
    import uvicorn

    from hermes_kb.config import get_settings

    settings = get_settings()
    uvicorn.run(
        "hermes_kb.app:app",
        host=args.host or settings.host,
        port=args.port or settings.port,
        reload=False,
        log_level=args.log_level,
    )
    return 0


def cmd_import_text(args: argparse.Namespace) -> int:
    from hermes_kb.rag import ImportService

    content = args.content
    if args.file:
        content = Path(args.file).read_text(encoding="utf-8")
    if not content:
        print("[error] --content 或 --file 必须提供", file=sys.stderr)
        return 2
    result = ImportService().import_text(
        content=content,
        title=args.title,
        source_type=args.source_type,
        file_type=args.file_type,
    )
    _print_json(result)
    return 0


def cmd_import_file(args: argparse.Namespace) -> int:
    from hermes_kb.rag import ImportService

    p = Path(args.path)
    if not p.exists():
        print(f"[error] 文件不存在: {p}", file=sys.stderr)
        return 2
    result = ImportService().import_file(p, title=args.title)
    _print_json(result)
    return 0


def cmd_list_docs(_args: argparse.Namespace) -> int:
    from sqlmodel import select

    from hermes_kb.database import get_session
    from hermes_kb.models import Document

    with get_session() as session:
        docs = session.exec(select(Document).order_by(Document.created_at.desc())).all()
        items = [
            {
                "doc_id": d.doc_id,
                "title": d.title,
                "source_type": d.source_type,
                "file_type": d.file_type,
                "chunk_count": d.chunk_count,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in docs
        ]
    _print_json({"total": len(items), "items": items})
    return 0


def cmd_delete_doc(args: argparse.Namespace) -> int:
    from hermes_kb.rag import ImportService

    ok = ImportService().delete_document(args.doc_id)
    if not ok:
        print(f"[error] 文档不存在: {args.doc_id}", file=sys.stderr)
        return 1
    _print_json({"doc_id": args.doc_id, "status": "deleted"})
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    import asyncio

    from hermes_kb.rag import RAGEngine

    rag = RAGEngine()
    if args.stream:
        async def _run() -> None:
            async for chunk in rag.answer_stream(args.query, top_k=args.top_k):
                # SSE 行格式：data: {...}\n\n
                if chunk.startswith("data: "):
                    try:
                        payload = json.loads(chunk[6:].strip())
                        if payload.get("type") == "delta":
                            sys.stdout.write(payload.get("content", ""))
                            sys.stdout.flush()
                        elif payload.get("type") == "meta":
                            sys.stderr.write(
                                f"[meta] citations={len(payload.get('citations', []))} "
                                f"rejected={payload.get('rejected')} "
                                f"low_confidence={payload.get('low_confidence')}\n"
                            )
                        elif payload.get("type") == "done":
                            sys.stderr.write(
                                f"[done] latency_ms={payload.get('latency_ms')}\n"
                            )
                            sys.stdout.write("\n")
                    except json.JSONDecodeError:
                        pass
        asyncio.run(_run())
        return 0

    result = rag.answer(args.query, top_k=args.top_k)
    _print_json(result.to_dict())
    return 0


def cmd_seed(_args: argparse.Namespace) -> int:
    from hermes_kb.rag import ImportService
    from hermes_kb.seed import SEED_DOCS

    importer = ImportService()
    results: list[dict[str, Any]] = []
    for doc in SEED_DOCS:
        try:
            r = importer.import_text(
                content=doc["content"],
                title=doc["title"],
                source_type="seed",
                file_type="md",
            )
            results.append(r)
        except Exception as e:
            results.append({"title": doc["title"], "error": str(e), "status": "failed"})
    _print_json(
        {
            "seeded": len([x for x in results if x.get("status") == "imported"]),
            "failed": len([x for x in results if x.get("status") == "failed"]),
            "items": results,
        }
    )
    return 0


def cmd_health(_args: argparse.Namespace) -> int:
    from sqlmodel import select

    from hermes_kb.config import get_settings
    from hermes_kb.database import get_session
    from hermes_kb.models import Document

    settings = get_settings()
    doc_count = 0
    try:
        with get_session() as session:
            doc_count = len(session.exec(select(Document)).all())
    except Exception as e:
        print(f"[warn] 数据库查询失败: {e}", file=sys.stderr)
    _print_json(
        {
            "status": "ok",
            "service": "hermes-kb",
            "version": "0.2.0",
            "doc_count": doc_count,
            "llm_provider": settings.llm_provider,
            "llm_available": settings.llm_available,
            "embedding_provider": settings.embedding_provider,
            "embedding_available": settings.embedding_available,
            "auth_enabled": settings.auth_enabled,
            "age_gate_enabled": settings.age_gate_enabled,
            "db_path": settings.db_path,
        }
    )
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    if not args.force:
        print("[error] 重置数据库需 --force 确认", file=sys.stderr)
        return 2
    from hermes_kb.config import get_settings

    settings = get_settings()
    db_path = Path(settings.db_path)
    if not db_path.exists():
        print(f"[info] 数据库文件不存在: {db_path}")
        return 0
    # 关闭引擎连接
    from hermes_kb.database import _ENGINE  # type: ignore

    if _ENGINE is not None:
        _ENGINE.dispose()
    # 删除主 db + WAL/SHM
    for suffix in ("", "-wal", "-shm"):
        p = db_path.with_name(db_path.name + suffix)
        if p.exists():
            p.unlink()
            print(f"[info] 已删除 {p}")
    print("[info] 数据库已重置，下次访问将自动重建 schema")
    return 0


def cmd_migrate(_args: argparse.Namespace) -> int:
    """执行 alembic 数据库迁移到 head。

    生产环境用此命令显式升级 schema（替代启动期隐式 create_all）。
    连接串从 hermes_kb.config.get_settings().db_url 读取。
    """
    from hermes_kb.config import get_settings
    from hermes_kb.database import run_migrations

    settings = get_settings()
    print(f"[info] 数据库: {settings.db_path}")
    try:
        run_migrations()
    except Exception as e:  # noqa: BLE001
        print(f"[error] 迁移失败: {e}", file=sys.stderr)
        return 1
    print("[info] 迁移完成 (head)")
    return 0


# ---------------------------------------------------------------------------
# 参数解析
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hermes-kb",
        description="Hermes 知识库 CLI（M0+M1）",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # serve
    p = sub.add_parser("serve", help="启动 API 服务")
    p.add_argument("--host", help="监听地址（默认从配置读取）")
    p.add_argument("--port", type=int, help="监听端口（默认从配置读取）")
    p.add_argument(
        "--log-level", default="info", choices=["debug", "info", "warning", "error"]
    )
    p.set_defaults(func=cmd_serve)

    # import-text
    p = sub.add_parser("import-text", help="导入纯文本")
    p.add_argument("--title", required=True, help="文档标题")
    p.add_argument("--content", help="文档内容")
    p.add_argument("--file", help="从文件读取内容")
    p.add_argument("--source-type", default="local", help="来源类型")
    p.add_argument("--file-type", default="txt", choices=["txt", "md", "pdf"])
    p.set_defaults(func=cmd_import_text)

    # import-file
    p = sub.add_parser("import-file", help="导入 txt/md/pdf 文件")
    p.add_argument("path", help="文件路径")
    p.add_argument("--title", help="文档标题（默认用文件名）")
    p.set_defaults(func=cmd_import_file)

    # list-docs
    p = sub.add_parser("list-docs", help="列出所有文档")
    p.set_defaults(func=cmd_list_docs)

    # delete-doc
    p = sub.add_parser("delete-doc", help="删除指定文档")
    p.add_argument("doc_id", help="文档 ID")
    p.set_defaults(func=cmd_delete_doc)

    # ask
    p = sub.add_parser("ask", help="提问")
    p.add_argument("query", help="问题")
    p.add_argument("--top-k", type=int, default=None)
    p.add_argument("--stream", action="store_true", help="流式输出")
    p.set_defaults(func=cmd_ask)

    # seed
    p = sub.add_parser("seed", help="导入种子数据")
    p.set_defaults(func=cmd_seed)

    # health
    p = sub.add_parser("health", help="健康检查")
    p.set_defaults(func=cmd_health)

    # reset
    p = sub.add_parser("reset", help="清空数据库")
    p.add_argument("--force", action="store_true", help="确认清空")
    p.set_defaults(func=cmd_reset)

    # migrate
    p = sub.add_parser("migrate", help="执行 alembic 数据库迁移到 head")
    p.set_defaults(func=cmd_migrate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


def migrate_main(argv: list[str] | None = None) -> int:
    """``hermes-kb-migrate`` 脚本入口：等价于 ``hermes-kb migrate``。"""
    return main(["migrate", *(argv or [])])


if __name__ == "__main__":
    sys.exit(main())
