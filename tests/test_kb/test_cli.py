"""CLI 子命令测试。"""

from __future__ import annotations

import json

from hermes.kb_cli import main


def test_cli_health(capsys):
    """health 子命令应返回 ok。"""
    rc = main(["health"])
    out = capsys.readouterr().out
    assert rc == 0
    data = json.loads(out)
    assert data["status"] == "ok"
    assert data["service"] == "hermes-kb"


def test_cli_list_docs_empty(capsys):
    """空库下列文档应返回 total=0。"""
    rc = main(["list-docs"])
    out = capsys.readouterr().out
    assert rc == 0
    data = json.loads(out)
    assert data["total"] == 0


def test_cli_import_text(capsys):
    """import-text 应成功导入。"""
    rc = main([
        "import-text",
        "--title", "CLI 测试",
        "--content", "金酒是杜松子酒。" * 50,
    ])
    out = capsys.readouterr().out
    assert rc == 0
    data = json.loads(out)
    assert data["status"] == "imported"
    assert data["title"] == "CLI 测试"


def test_cli_import_text_no_content(capsys):
    """缺 content/file 应返回 2。"""
    rc = main(["import-text", "--title", "t"])
    assert rc == 2


def test_cli_import_file_not_exist(capsys):
    """import-file 文件不存在应返回 2。"""
    rc = main(["import-file", "/nonexistent/path.txt"])
    assert rc == 2


def test_cli_seed(capsys):
    """seed 应导入 5 篇。"""
    rc = main(["seed"])
    out = capsys.readouterr().out
    assert rc == 0
    data = json.loads(out)
    assert data["seeded"] == 5
    assert data["failed"] == 0


def test_cli_ask_seeded(capsys):
    """seed 后 ask 应返回答案。"""
    main(["seed"])
    capsys.readouterr()  # 清空
    rc = main(["ask", "金酒的核心风味"])
    out = capsys.readouterr().out
    assert rc == 0
    data = json.loads(out)
    assert data["answer"]
    assert data["citations"]


def test_cli_delete_doc(capsys):
    """import → delete 应工作。"""
    main(["import-text", "--title", "待删", "--content", "x" * 100])
    doc_id = json.loads(capsys.readouterr().out)["doc_id"]
    rc = main(["delete-doc", doc_id])
    out = capsys.readouterr().out
    assert rc == 0
    assert json.loads(out)["status"] == "deleted"


def test_cli_delete_nonexistent(capsys):
    """删除不存在的文档应返回 1。"""
    rc = main(["delete-doc", "doc_not_exists"])
    assert rc == 1


def test_cli_reset_no_force(capsys):
    """reset 不带 --force 应返回 2。"""
    rc = main(["reset"])
    assert rc == 2


def test_cli_reset_force(capsys):
    """reset --force 应成功。"""
    main(["import-text", "--title", "t", "--content", "x" * 50])
    capsys.readouterr()
    rc = main(["reset", "--force"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "已重置" in out
