from datetime import date, datetime, timedelta, timezone

from app.extensions import db

todo_requirements = db.Table('todo_requirements',
    db.Column('todo_id', db.Integer, db.ForeignKey('todos.id'), primary_key=True),
    db.Column('requirement_id', db.Integer, db.ForeignKey('requirements.id'), primary_key=True),
)


class Todo(db.Model):
    __tablename__ = 'todos'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(300), nullable=False)
    status = db.Column(db.String(20), default='todo')  # todo / done
    category = db.Column(db.String(20), default='work')  # work / team / personal
    source = db.Column(db.String(20), default='manual')  # manual / ai / help
    parent_id = db.Column(db.Integer, db.ForeignKey('todos.id'), nullable=True)
    sort_order = db.Column(db.Integer, default=0)
    due_date = db.Column(db.Date, nullable=True)
    created_date = db.Column(db.Date, default=date.today)
    done_date = db.Column(db.Date, nullable=True)
    need_help = db.Column(db.Boolean, default=False)  # 阻塞标记
    blocked_reason = db.Column(db.String(200), nullable=True)  # 阻塞原因
    started_at = db.Column(db.DateTime, nullable=True)  # Timer start
    actual_minutes = db.Column(db.Integer, nullable=True)  # Recorded on completion
    created_at = db.Column(db.DateTime, default=db.func.now())
    updated_at = db.Column(db.DateTime, default=db.func.now(), onupdate=db.func.now())

    user = db.relationship('User', backref='todos')
    requirements = db.relationship('Requirement', secondary=todo_requirements, backref='todos', lazy='joined')
    parent = db.relationship('Todo', remote_side=[id], backref='children')
    items = db.relationship('TodoItem', backref='todo', cascade='all, delete-orphan',
                            order_by='TodoItem.sort_order')
    pomodoros = db.relationship('PomodoroSession', backref='todo', cascade='all, delete-orphan',
                                order_by='PomodoroSession.created_at')

    STATUS_LABELS = {'todo': '待办', 'done': '完成'}

    @property
    def status_label(self):
        return self.STATUS_LABELS.get(self.status, self.status)

    @property
    def items_progress(self):
        """Return (done_count, total_count)."""
        if not self.items:
            return 0, 0
        done = sum(1 for i in self.items if i.is_done)
        return done, len(self.items)

    @property
    def all_items_done(self):
        """True if has items and all are checked."""
        if not self.items:
            return False
        return all(i.is_done for i in self.items)

    @property
    def workdays_overdue(self):
        if self.status == 'done' or not self.created_date:
            return 0
        today = date.today()
        if self.created_date >= today:
            return 0
        # Previous workday's todo is not overdue before 10am next workday
        # e.g. Friday todo → not overdue before Monday 10am
        if datetime.now().hour < 10:
            prev_workday = today - timedelta(days=1)
            while prev_workday.weekday() >= 5:  # skip weekend
                prev_workday -= timedelta(days=1)
            if self.created_date >= prev_workday:
                return 0
        total_days = (today - self.created_date).days
        full_weeks, remaining = divmod(total_days, 7)
        count = full_weeks * 5
        start_weekday = self.created_date.weekday()
        for i in range(1, remaining + 1):
            if (start_weekday + i) % 7 < 5:
                count += 1
        return count

    @property
    def overdue_color(self):
        from flask import current_app
        days = self.workdays_overdue
        if days >= current_app.config.get('OVERDUE_DANGER_DAYS', 3):
            return 'danger'
        if days >= current_app.config.get('OVERDUE_WARN_DAYS', 1):
            return 'warning'
        return ''

    @property
    def is_overdue_by_due_date(self):
        """True if due_date is set and past."""
        return self.due_date and self.due_date < date.today() and self.status != 'done'

    @property
    def timer_running(self):
        return self.started_at is not None and self.status != 'done'

    @property
    def elapsed_minutes(self):
        if not self.started_at:
            return 0
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        return int((now - self.started_at).total_seconds() / 60)

    def __repr__(self):
        return f'<Todo {self.title}>'


class PomodoroSession(db.Model):
    """Individual pomodoro timer session record."""
    __tablename__ = 'pomodoro_sessions'

    id = db.Column(db.Integer, primary_key=True)
    todo_id = db.Column(db.Integer, db.ForeignKey('todos.id'), nullable=False)
    started_at = db.Column(db.DateTime, nullable=True)  # When timer was started
    minutes = db.Column(db.Integer, nullable=False, default=0)
    completed = db.Column(db.Boolean, default=False)  # True if full pomodoro
    created_at = db.Column(db.DateTime, default=db.func.now())

    def __repr__(self):
        return f'<Pomodoro {self.minutes}min {"✓" if self.completed else "✗"}>'




class TodoItem(db.Model):
    __tablename__ = 'todo_items'

    id = db.Column(db.Integer, primary_key=True)
    todo_id = db.Column(db.Integer, db.ForeignKey('todos.id'), nullable=False)
    title = db.Column(db.String(300), nullable=False)
    is_done = db.Column(db.Boolean, default=False)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=db.func.now())

    def __repr__(self):
        return f'<TodoItem {self.title}>'
