from datetime import date, timedelta

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models.standup import StandupRecord
from app.models.todo import Todo
from app.standup import standup_bp


@standup_bp.route('/')
@login_required
def index():
    today = date.today()
    record = StandupRecord.query.filter_by(user_id=current_user.id, date=today).first()
    if record:
        return render_template('standup/done.html', record=record)

    yesterday = today - timedelta(days=1)
    yesterday_todos = Todo.query.filter_by(user_id=current_user.id, done_date=yesterday).all()
    today_todos = Todo.query.filter_by(user_id=current_user.id)\
        .filter(Todo.status == 'todo').all()

    return render_template('standup/form.html', today=today,
                           yesterday_todos=yesterday_todos, today_todos=today_todos)


@standup_bp.route('/submit', methods=['POST'])
@login_required
def submit():
    today = date.today()
    if StandupRecord.query.filter_by(user_id=current_user.id, date=today).first():
        flash('今日站会已提交', 'info')
        return redirect(url_for('standup.index'))

    yesterday_done = request.form.get('yesterday_done', '').strip()
    today_plan = request.form.get('today_plan', '').strip()
    blocker = request.form.get('blocker', '').strip()

    if not yesterday_done or not today_plan:
        flash('昨日完成和今日计划不能为空', 'danger')
        return redirect(url_for('standup.index'))

    record = StandupRecord(
        user_id=current_user.id, date=today,
        yesterday_done=yesterday_done,
        today_plan=today_plan,
        blocker=blocker if blocker and blocker != '无' else None,
        has_blocker=bool(blocker and blocker != '无'),
    )
    db.session.add(record)
    db.session.commit()
    flash('站会记录已提交', 'success')
    return redirect(url_for('standup.index'))


@standup_bp.route('/history')
@login_required
def history():
    records = StandupRecord.query.filter_by(user_id=current_user.id)\
        .order_by(StandupRecord.date.desc()).limit(30).all()
    return render_template('standup/history.html', records=records)
