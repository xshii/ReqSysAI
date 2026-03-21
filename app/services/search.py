"""SQLite FTS5 full-text search infrastructure."""

import logging

from flask import current_app
from sqlalchemy import text

from app.extensions import db

logger = logging.getLogger(__name__)


def init_fts(app):
    """Create FTS5 virtual table if not exists. Call during app creation."""
    with app.app_context():
        db.session.execute(text('''
            CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(
                entity_type, entity_id UNINDEXED, title, content, extra,
                tokenize='unicode61'
            )
        '''))
        db.session.commit()


def reindex_all():
    """Rebuild full search index from all entities."""
    db.session.execute(text('DELETE FROM search_index'))

    from app.models.requirement import Requirement
    for r in Requirement.query.all():
        _insert(r.id, 'requirement', r.title, r.description or '', r.number)

    from app.models.todo import Todo
    for t in Todo.query.all():
        _insert(t.id, 'todo', t.title, '', '')

    from app.models.project import Project
    for p in Project.query.all():
        _insert(p.id, 'project', p.name, p.description or '', '')

    from app.models.user import User
    for u in User.query.filter_by(is_active=True).all():
        _insert(u.id, 'user', u.name, u.pinyin or '', u.employee_id or '')

    db.session.commit()
    logger.info('Search index rebuilt')


def index_entity(entity_type, entity_id, title, content='', extra=''):
    """Upsert a single entity in the search index."""
    remove_entity(entity_type, entity_id)
    _insert(entity_id, entity_type, title, content, extra)
    db.session.commit()


def remove_entity(entity_type, entity_id):
    """Remove an entity from the search index."""
    db.session.execute(text(
        'DELETE FROM search_index WHERE entity_type = :t AND entity_id = :id'
    ), {'t': entity_type, 'id': str(entity_id)})


def search(query, limit=20):
    """Search FTS5 index. Returns list of dicts."""
    if not query or not query.strip():
        return []
    # Escape FTS5 special chars and add prefix matching
    q = query.strip().replace('"', '""')
    fts_query = f'"{q}"*'
    try:
        rows = db.session.execute(text('''
            SELECT entity_type, entity_id, title, extra,
                   snippet(search_index, 2, '<b>', '</b>', '...', 20) as snippet
            FROM search_index
            WHERE search_index MATCH :q
            ORDER BY rank
            LIMIT :limit
        '''), {'q': fts_query, 'limit': limit}).fetchall()
    except Exception:
        # Fallback: simple LIKE search if FTS fails
        rows = db.session.execute(text('''
            SELECT entity_type, entity_id, title, extra, '' as snippet
            FROM search_index
            WHERE title LIKE :q OR content LIKE :q OR extra LIKE :q
            LIMIT :limit
        '''), {'q': f'%{query.strip()}%', 'limit': limit}).fetchall()

    return [
        {'type': r[0], 'id': r[1], 'title': r[2], 'extra': r[3], 'snippet': r[4]}
        for r in rows
    ]


def _insert(entity_id, entity_type, title, content, extra):
    db.session.execute(text(
        'INSERT INTO search_index (entity_type, entity_id, title, content, extra) '
        'VALUES (:t, :id, :title, :content, :extra)'
    ), {'t': entity_type, 'id': str(entity_id), 'title': title,
        'content': content, 'extra': extra})
