from datetime import datetime, date

from app.extensions import db


class RecurringTodo(db.Model):
    """Recurring todo template — weekly/monthly/specific weekdays."""
    __tablename__ = 'recurring_todos'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(300), nullable=False)
    cycle = db.Column(db.String(20), nullable=False)  # weekly / monthly / weekdays
    weekdays = db.Column(db.String(20), nullable=True)  # e.g. "1,3,5" for Mon,Wed,Fri (weekdays mode)
    monthly_day = db.Column(db.Integer, nullable=True)  # legacy single day
    monthly_days = db.Column(db.String(20), nullable=True)  # e.g. "start,mid,end" for 月初,月中,月末
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='recurring_todos')

    CYCLE_LABELS = {'weekly': '每周', 'monthly': '每月', 'weekdays': '指定星期'}
    WEEKDAY_NAMES = ['一', '二', '三', '四', '五', '六', '日']
    MONTHLY_PERIOD_LABELS = {'start': '月初', 'mid': '月中', 'end': '月末'}

    @staticmethod
    def _period_day(period, year=None, month=None):
        """Convert period name to day of month."""
        import calendar
        today = date.today()
        y = year or today.year
        m = month or today.month
        if period == 'start':
            return 1
        elif period == 'mid':
            return 15
        elif period == 'end':
            _, last = calendar.monthrange(y, m)
            return last
        return 1

    @property
    def monthly_periods(self):
        """Get list of monthly periods."""
        if self.monthly_days:
            return [p.strip() for p in self.monthly_days.split(',') if p.strip()]
        if self.monthly_day:
            # Legacy: convert single day to period
            if self.monthly_day <= 5:
                return ['start']
            elif self.monthly_day <= 20:
                return ['mid']
            return ['end']
        return ['start']

    @property
    def cycle_label(self):
        return self.CYCLE_LABELS.get(self.cycle, self.cycle)

    @property
    def schedule_desc(self):
        if self.cycle == 'weekly':
            return '每周'
        elif self.cycle == 'monthly':
            labels = [self.MONTHLY_PERIOD_LABELS.get(p, p) for p in self.monthly_periods]
            return '每月' + '、'.join(labels)
        elif self.cycle == 'weekdays' and self.weekdays:
            days = [self.WEEKDAY_NAMES[int(d)] for d in self.weekdays.split(',') if d.isdigit() and int(d) < 7]
            return '每周' + '、'.join(days)
        return self.cycle

    def is_due_today(self):
        """Check if this recurring todo should trigger today."""
        today = date.today()
        if self.cycle == 'weekly':
            return today.weekday() == 0  # Monday
        elif self.cycle == 'monthly':
            for p in self.monthly_periods:
                if today.day == self._period_day(p):
                    return True
            return False
        elif self.cycle == 'weekdays' and self.weekdays:
            return str(today.weekday()) in self.weekdays.split(',')
        return False

    def days_since_last(self):
        """Days since the deadline of the most recent occurrence.
        weekly: deadline is Saturday (can do Mon-Sat), overdue on Sunday.
        monthly: deadline is the day itself.
        weekdays: deadline is the day itself.
        Returns 0 if still within valid period, >0 if overdue."""
        today = date.today()
        if self.is_due_today():
            return 0
        if self.cycle == 'weekly':
            # Weekly tasks can be done Mon-Sat, overdue on Sunday only
            if today.weekday() < 6:  # Mon-Sat: still within this week
                return 0
            return 1  # Sunday: 1 day overdue
        elif self.cycle == 'monthly':
            # Find most recent past period day this month
            past_diffs = []
            has_future = False
            for p in self.monthly_periods:
                target = self._period_day(p)
                if today.day > target:
                    past_diffs.append(today.day - target)
                else:
                    has_future = True
            if past_diffs:
                return min(past_diffs)  # days since the most recent past period
            # All periods are still upcoming this month — not overdue
            return 0
        elif self.cycle == 'weekdays' and self.weekdays:
            target_days = sorted(int(d) for d in self.weekdays.split(',') if d.isdigit())
            if not target_days:
                return None
            for d in reversed(target_days):
                diff = today.weekday() - d
                if diff > 0:
                    return diff
            return today.weekday() + (7 - target_days[-1])
        return None

    def days_until_next(self):
        """Days until next occurrence."""
        from datetime import timedelta
        today = date.today()
        if self.cycle == 'weekly':
            days_ahead = 0 - today.weekday()  # Monday=0
            if days_ahead <= 0:
                days_ahead += 7
            return days_ahead
        elif self.cycle == 'monthly':
            import calendar
            # Find nearest future period day
            for p in sorted(self.monthly_periods, key=lambda x: self._period_day(x)):
                target = self._period_day(p)
                if today.day < target:
                    return target - today.day
            # All past this month — next month's first period
            _, last = calendar.monthrange(today.year, today.month)
            first_target = min(self._period_day(p, today.year, today.month + 1 if today.month < 12 else 1) for p in self.monthly_periods)
            return last - today.day + first_target
        elif self.cycle == 'weekdays' and self.weekdays:
            target_days = sorted(int(d) for d in self.weekdays.split(',') if d.isdigit())
            if not target_days:
                return 999
            for d in target_days:
                diff = d - today.weekday()
                if diff > 0:
                    return diff
            return 7 - today.weekday() + target_days[0]
        return 999
