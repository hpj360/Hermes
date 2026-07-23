"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-07-23 04:50:23.139751+00:00

首版迁移：建立全部 SQLModel 表 + FTS5 全文检索虚拟表 + 同步触发器 + 向量表。

覆盖对象（与 database.py 原 create_all + _init_fts + _init_vec_table 完全对齐）：
- SQLModel 表：document / chunk / tag / documenttag / querylog / recipestats /
  ingredientsubstitute / missingingredientstats / recipevariant
- FTS5 虚拟表：chunks_fts（unicode61 分词）
- 触发器：chunk_ai / chunk_ad / chunk_au（chunk ↔ chunks_fts 同步）
- 向量表：chunk_vec（JSON 数组存储，Python 层余弦相似度）
- 索引：idx_chunk_vec_doc_id

注：表名为 SQLModel 默认（类名小写，无下划线），如 documenttag / querylog 等，
与 SQLModel.metadata 一致；FTS5/触发器/向量表用 op.execute() 原始 SQL
（alembic autogenerate 不支持 FTS5 虚拟表）。
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === SQLModel 表（autogenerate 生成，与 metadata 一致）===
    op.create_table('document',
        sa.Column('doc_id', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column('title', sqlmodel.sql.sqltypes.AutoString(length=200), nullable=False),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('source_type', sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column('file_type', sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column('source_path', sqlmodel.sql.sqltypes.AutoString(length=512), nullable=True),
        sa.Column('chunk_count', sa.Integer(), nullable=False),
        sa.Column('category', sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column('source', sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column('source_id', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True),
        sa.Column('verified', sa.Boolean(), nullable=False),
        sa.Column('season', sqlmodel.sql.sqltypes.AutoString(length=16), nullable=True),
        sa.Column('hidden', sa.Boolean(), nullable=False),
        sa.Column('status', sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column('image_url', sqlmodel.sql.sqltypes.AutoString(length=512), nullable=True),
        sa.Column('metadata', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('doc_id')
    )
    with op.batch_alter_table('document', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_document_category'), ['category'], unique=False)
        batch_op.create_index(batch_op.f('ix_document_source'), ['source'], unique=False)
        batch_op.create_index(batch_op.f('ix_document_title'), ['title'], unique=False)

    op.create_table('ingredientsubstitute',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('canonical', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column('substitute', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column('source', sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('canonical', 'substitute', name='uq_ingredient_substitute')
    )
    with op.batch_alter_table('ingredientsubstitute', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ingredientsubstitute_canonical'), ['canonical'], unique=False)

    op.create_table('missingingredientstats',
        sa.Column('canonical', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column('missing_count', sa.Integer(), nullable=False),
        sa.Column('last_missing_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('canonical')
    )
    op.create_table('querylog',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('query', sqlmodel.sql.sqltypes.AutoString(length=2000), nullable=False),
        sa.Column('answer', sa.Text(), nullable=True),
        sa.Column('citations', sa.Text(), nullable=True),
        sa.Column('model_used', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column('latency_ms', sa.Integer(), nullable=False),
        sa.Column('feedback', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('querylog', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_querylog_created_at'), ['created_at'], unique=False)

    op.create_table('tag',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column('color', sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('tag', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_tag_name'), ['name'], unique=True)

    op.create_table('chunk',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('doc_id', sa.Text(), nullable=True),
        sa.Column('idx', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), nullable=True),
        sa.Column('char_start', sa.Integer(), nullable=False),
        sa.Column('char_end', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['doc_id'], ['document.doc_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('chunk', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_chunk_doc_id'), ['doc_id'], unique=False)

    op.create_table('documenttag',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('doc_id', sa.Text(), nullable=True),
        sa.Column('tag_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['doc_id'], ['document.doc_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tag_id'], ['tag.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('documenttag', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_documenttag_doc_id'), ['doc_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_documenttag_tag_id'), ['tag_id'], unique=False)

    op.create_table('recipestats',
        sa.Column('doc_id', sa.Text(), nullable=False),
        sa.Column('match_count', sa.Integer(), nullable=False),
        sa.Column('view_count', sa.Integer(), nullable=False),
        sa.Column('weekly_match_count', sa.Integer(), nullable=False),
        sa.Column('last_matched_at', sa.DateTime(), nullable=True),
        sa.Column('last_viewed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['doc_id'], ['document.doc_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('doc_id')
    )
    op.create_table('recipevariant',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('base_doc_id', sa.Text(), nullable=True),
        sa.Column('variant_doc_id', sa.Text(), nullable=True),
        sa.Column('variant_note', sqlmodel.sql.sqltypes.AutoString(length=200), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['base_doc_id'], ['document.doc_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['variant_doc_id'], ['document.doc_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('recipevariant', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_recipevariant_base_doc_id'), ['base_doc_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_recipevariant_variant_doc_id'), ['variant_doc_id'], unique=False)

    # === FTS5 虚拟表 + 同步触发器（autogenerate 不支持 FTS5，用原始 SQL）===
    # 与 database.py._init_fts 完全一致
    op.execute(
        "CREATE VIRTUAL TABLE chunks_fts USING fts5("
        "text, doc_id UNINDEXED, chunk_rowid UNINDEXED, "
        "tokenize='unicode61'"
        ")"
    )
    op.execute(
        "CREATE TRIGGER chunk_ai AFTER INSERT ON chunk BEGIN "
        "INSERT INTO chunks_fts(text, doc_id, chunk_rowid) "
        "VALUES (new.text, new.doc_id, new.id); "
        "END"
    )
    op.execute(
        "CREATE TRIGGER chunk_ad AFTER DELETE ON chunk BEGIN "
        "DELETE FROM chunks_fts WHERE chunk_rowid = old.id; "
        "END"
    )
    op.execute(
        "CREATE TRIGGER chunk_au AFTER UPDATE ON chunk BEGIN "
        "DELETE FROM chunks_fts WHERE chunk_rowid = old.id; "
        "INSERT INTO chunks_fts(text, doc_id, chunk_rowid) "
        "VALUES (new.text, new.doc_id, new.id); "
        "END"
    )

    # === 向量表 chunk_vec（与 database.py._init_vec_table 一致）===
    op.execute(
        "CREATE TABLE chunk_vec ("
        "chunk_rowid INTEGER PRIMARY KEY, "
        "doc_id TEXT REFERENCES document(doc_id) ON DELETE CASCADE, "
        "vec TEXT NOT NULL"
        ")"
    )
    op.execute(
        "CREATE INDEX idx_chunk_vec_doc_id ON chunk_vec(doc_id)"
    )


def downgrade() -> None:
    # === 向量表 / 触发器 / FTS5（逆序）===
    op.execute("DROP INDEX IF EXISTS idx_chunk_vec_doc_id")
    op.execute("DROP TABLE IF EXISTS chunk_vec")
    op.execute("DROP TRIGGER IF EXISTS chunk_au")
    op.execute("DROP TRIGGER IF EXISTS chunk_ad")
    op.execute("DROP TRIGGER IF EXISTS chunk_ai")
    op.execute("DROP TABLE IF EXISTS chunks_fts")

    # === SQLModel 表（逆序，autogenerate 生成）===
    with op.batch_alter_table('recipevariant', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_recipevariant_variant_doc_id'))
        batch_op.drop_index(batch_op.f('ix_recipevariant_base_doc_id'))

    op.drop_table('recipevariant')
    op.drop_table('recipestats')
    with op.batch_alter_table('documenttag', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_documenttag_tag_id'))
        batch_op.drop_index(batch_op.f('ix_documenttag_doc_id'))

    op.drop_table('documenttag')
    with op.batch_alter_table('chunk', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_chunk_doc_id'))

    op.drop_table('chunk')
    with op.batch_alter_table('tag', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_tag_name'))

    op.drop_table('tag')
    with op.batch_alter_table('querylog', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_querylog_created_at'))

    op.drop_table('querylog')
    op.drop_table('missingingredientstats')
    with op.batch_alter_table('ingredientsubstitute', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ingredientsubstitute_canonical'))

    op.drop_table('ingredientsubstitute')
    with op.batch_alter_table('document', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_document_title'))
        batch_op.drop_index(batch_op.f('ix_document_source'))
        batch_op.drop_index(batch_op.f('ix_document_category'))

    op.drop_table('document')
