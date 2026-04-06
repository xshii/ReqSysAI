from datetime import date

from app.extensions import db, _local_now


class RecurringCompletion(db.Model):
    """Lightweight record: a recurring todo was completed on a specific date."""
    __tablename__ = 'recurring_completions'

    id = db.Column(db.Integer, primary_key=True)
    recurring_id = db.Column(db.Integer, db.ForeignKey('recurring_todos.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    completed_date = db.Column(db.Date, nullable=False, default=date.today)
    created_at = db.Column(db.DateTime, default=_local_now)

    __table_args__ = (
        db.UniqueConstraint('recurring_id', 'user_id', 'completed_date', name='uq_recurring_completion'),
    )

    recurring = db.relationship('RecurringTodo', backref='completions')
