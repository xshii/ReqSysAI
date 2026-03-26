from datetime import date, datetime, timedelta

from flask import jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload

from app.constants import (
    AI_TOKEN_RATIO,
    HEATMAP_DAYS,
    MAX_RANT_LENGTH,
    REQ_INACTIVE_STATUSES,
    TODO_STATUS_DONE,
    TODO_STATUS_TODO,
)
from app.extensions import db
from app.main import main_bp
from app.models.ai_log import AIParseLog
from app.models.email_setting import EmailSetting
from app.models.incentive import Incentive
from app.models.project import Project
from app.models.rant import Rant
from app.models.requirement import Requirement
from app.models.risk import Risk
from app.models.todo import Todo, TodoItem, todo_requirements
from app.models.user import User


def _prev_workday(today):
    """Return previous workday (Friday if today is Monday)."""
    if today.weekday() == 0:
        return today - timedelta(days=3)
    return today - timedelta(days=1)


def _yesterday_reqs(user_id, yesterday):
    """Get active requirements linked to yesterday's todos."""
    todos = Todo.query.filter_by(user_id=user_id).filter(
        db.or_(
            db.and_(Todo.status == TODO_STATUS_DONE, Todo.done_date == yesterday),
            db.and_(Todo.status == TODO_STATUS_TODO, Todo.created_date <= yesterday),
        )
    ).options(joinedload(Todo.requirements)).all()
    reqs, seen = [], set()
    for t in todos:
        for r in t.requirements:
            if r.id not in seen and r.status not in REQ_INACTIVE_STATUSES:
                reqs.append(r)
                seen.add(r.id)
    return reqs


@main_bp.route('/')
@login_required
def index():
    today = date.today()

    # My today's todos
    my_todos = Todo.query.filter_by(user_id=current_user.id).filter(
        db.or_(
            Todo.status == TODO_STATUS_TODO,
            db.and_(Todo.status == TODO_STATUS_DONE, Todo.done_date == today),
        )
    ).options(joinedload(Todo.items), joinedload(Todo.requirements), joinedload(Todo.children), joinedload(Todo.pomodoros), joinedload(Todo.parent))\
     .order_by(db.case((Todo.status == TODO_STATUS_TODO, 0), else_=1), Todo.sort_order).all()
    todo_total = len(my_todos)
    todo_done = sum(1 for t in my_todos if t.status == TODO_STATUS_DONE)

    # 隐藏项目仅管理层+eye打开时可见（隐私模式，见 routes.py _mgr_view_open 注释）
    from app.project.routes import _mgr_view_open
    _hidden_pids = [] if _mgr_view_open() else [p.id for p in Project.query.filter_by(is_hidden=True).all()]
    _req_q = Requirement.query.filter_by(assignee_id=current_user.id)\
        .filter(Requirement.status.notin_(REQ_INACTIVE_STATUSES))
    if _hidden_pids:
        _req_q = _req_q.filter(Requirement.project_id.notin_(_hidden_pids))
    my_reqs = _req_q\
        .options(joinedload(Requirement.project), joinedload(Requirement.comments))\
        .order_by(Requirement.due_date.asc().nullslast(), Requirement.priority, Requirement.updated_at.desc()).limit(10).all()

    # Group todos by category for merged display
    req_todos = {}  # req_id → [todos]
    risk_todos = []
    team_todos = []
    personal_todos = []
    req_map = {r.id: r for r in my_reqs}  # Known requirements
    # Help requests: others' @me child todos I haven't accepted yet
    help_requests = [t for t in my_todos if t.parent_id and t.source == 'help' and t.status != 'done']
    help_todo_ids = {t.id for t in help_requests}
    for t in my_todos:
        if t.id in help_todo_ids:
            continue  # Skip unaccepted help requests — shown separately with accept/reject buttons
        if t.category == 'risk':
            risk_todos.append(t)
        elif t.category == 'personal':
            personal_todos.append(t)
        elif t.category == 'team' or not t.requirements:
            team_todos.append(t)
        else:
            linked = [r for r in t.requirements if r.status not in REQ_INACTIVE_STATUSES]
            if linked:
                for r in linked:
                    req_todos.setdefault(r.id, []).append(t)
                    if r.id not in req_map:
                        req_map[r.id] = r  # Add requirement not in my_reqs
            else:
                team_todos.append(t)
    # Merge any extra requirements from todos into display list (exclude hidden projects)
    _hidden_set = set(_hidden_pids)
    display_reqs = list(my_reqs) + [r for rid, r in req_map.items() if rid not in {x.id for x in my_reqs} and r.project_id not in _hidden_set]

    # Risk titles already in today's todos (for +Todo button state)
    risk_todo_titles = {t.title for t in my_todos if t.category == 'risk'}

    # My related risks — overdue/due-today first, then severity, then due_date
    my_risks = Risk.query.filter(
        Risk.status == 'open',
        Risk.deleted_at.is_(None),
        db.or_(Risk.tracker_id == current_user.id, Risk.owner_id == current_user.id),
        Risk.project_id.notin_(_hidden_pids) if _hidden_pids else True,
    ).order_by(
        db.case((Risk.due_date < today, 0), (Risk.due_date == today, 1), else_=2),
        db.case({'high': 0, 'medium': 1, 'low': 2}, value=Risk.severity),
        Risk.due_date,
    ).all()

    # Alerts: overdue/due-today requirements + overdue/due-today risks
    alerts = [
        {'text': f'需求 [{r.number}] {r.title} 已超期 ({r.due_date.strftime("%m-%d")})', 'level': 'danger'}
        for r in my_reqs if r.due_date and r.due_date < today
    ] + [
        {'text': f'风险「{r.title}」已超期 ({r.due_date.strftime("%m-%d") if r.due_date else ""})', 'level': 'danger'}
        for r in my_risks if r.is_overdue
    ] + [
        {'text': f'需求 [{r.number}] {r.title} 今日到期', 'level': 'warning'}
        for r in my_reqs if r.due_date and r.due_date == today and r.status not in ('done', 'closed')
    ] + [
        {'text': f'风险「{r.title}」今日到期', 'level': 'warning'}
        for r in my_risks if r.is_due_today
    ]

    # Approved incentives: last 2 months excluding recent 7 days; fallback to 3 months if empty
    inc_end = today - timedelta(days=7)
    for months in (60, 90):
        inc_start = today - timedelta(days=months)
        approved_incentives = Incentive.query.filter(
            Incentive.status == 'approved',
            Incentive.is_public == True,
            Incentive.reviewed_at >= inc_start,
            Incentive.reviewed_at <= inc_end,
        ).order_by(Incentive.reviewed_at.desc()).all()
        if approved_incentives:
            break

    # AI usage ranking: top5
    ai_stats = db.session.query(
        AIParseLog.created_by,
        db.func.count(AIParseLog.id).label('call_count'),
        db.func.sum(db.func.length(AIParseLog.raw_input)).label('input_chars'),
        db.func.sum(db.func.length(AIParseLog.ai_output)).label('output_chars'),
    ).group_by(AIParseLog.created_by)\
     .order_by(db.func.count(AIParseLog.id).desc()).limit(5).all()

    ai_ranking = []
    for row in ai_stats:
        user = db.session.get(User, row.created_by)
        chars = (row.input_chars or 0) + (row.output_chars or 0)
        ai_ranking.append({
            'name': user.name if user else '未知',
            'calls': row.call_count,
            'tokens': int(chars * AI_TOKEN_RATIO),
        })

    # Contribution heatmap
    heatmap_start = today - timedelta(days=HEATMAP_DAYS)
    heatmap_rows = db.session.query(
        Todo.done_date, db.func.count(Todo.id),
    ).filter(
        Todo.user_id == current_user.id,
        Todo.status == TODO_STATUS_DONE,
        Todo.done_date >= heatmap_start,
    ).group_by(Todo.done_date).all()
    heatmap = {str(row[0]): row[1] for row in heatmap_rows}

    # Graffiti board: top3 all-time + current month
    month_start = today.replace(day=1)
    top_rants = Rant.query.filter(Rant.likes > 0).order_by(Rant.likes.desc()).limit(3).all()
    top_ids = {r.id for r in top_rants}
    month_q = Rant.query.filter(Rant.created_at >= month_start)
    if top_ids:
        month_q = month_q.filter(~Rant.id.in_(top_ids))
    rants = top_rants + month_q.order_by(Rant.created_at.desc()).limit(20).all()

    # Milestones from followed projects (upcoming/active)
    from app.models.project import Milestone
    followed_pids = [p.id for p in current_user.followed_projects.all()]
    milestones = []
    if followed_pids:
        milestones = Milestone.query.filter(
            Milestone.project_id.in_(followed_pids),
            Milestone.status == 'active',
        ).order_by(Milestone.due_date.asc().nullslast()).all()

    # Meetings with unclosed risks — only show risks related to current user
    from app.models.meeting import Meeting
    my_unclosed_risks = Risk.query.filter(
        Risk.status == 'open', Risk.deleted_at.is_(None), Risk.meeting_id.isnot(None),
        db.or_(Risk.tracker_id == current_user.id, Risk.owner_id == current_user.id),
    ).all()
    unclosed_meeting_ids = list(set(r.meeting_id for r in my_unclosed_risks))
    unclosed_meetings = Meeting.query.filter(Meeting.id.in_(unclosed_meeting_ids)).order_by(Meeting.date.desc()).all() if unclosed_meeting_ids else []
    unclosed_meeting_risks = {}
    for r in my_unclosed_risks:
        unclosed_meeting_risks[r.meeting_id] = unclosed_meeting_risks.get(r.meeting_id, 0) + 1

    # Recurring todos + completion status (independent of daily todos)
    from app.models.recurring_completion import RecurringCompletion
    from app.models.recurring_todo import RecurringTodo
    all_recurring = RecurringTodo.query.filter_by(user_id=current_user.id, is_active=True).all()
    recurring_due = [r for r in all_recurring if r.is_due_today()]
    # Check completions: today + this week (for weekday tasks not due today)
    recurring_status = {}
    if all_recurring:
        week_start_day = today - timedelta(days=today.weekday())
        completions = RecurringCompletion.query.filter(
            RecurringCompletion.user_id == current_user.id,
            RecurringCompletion.recurring_id.in_([r.id for r in all_recurring]),
            RecurringCompletion.completed_date >= week_start_day,
            RecurringCompletion.completed_date <= today,
        ).all()
        for c in completions:
            recurring_status[c.recurring_id] = 'done'

    # Weekly focus time (Pomodoro)
    week_start = today - timedelta(days=today.weekday())
    week_focus = db.session.query(db.func.coalesce(db.func.sum(Todo.actual_minutes), 0)).filter(
        Todo.user_id == current_user.id,
        Todo.done_date >= week_start,
        Todo.actual_minutes > 0,
    ).scalar() or 0

    # Persistent notifications (unread)
    from app.models.notification import Notification
    notifications = Notification.query.filter_by(user_id=current_user.id, is_read=False)\
        .order_by(Notification.created_at.desc()).limit(10).all()

    return render_template('main/index.html',
        my_todos=my_todos, todo_total=todo_total, todo_done=todo_done,
        notifications=notifications,
        my_reqs=my_reqs, my_risks=my_risks, today=today,
        req_todos=req_todos, risk_todos=risk_todos, team_todos=team_todos, personal_todos=personal_todos,
        display_reqs=display_reqs,
        approved_incentives=approved_incentives, rants=rants,
        ai_ranking=ai_ranking, alerts=alerts, help_requests=help_requests, risk_todo_titles=risk_todo_titles,
        heatmap=heatmap, heatmap_start=heatmap_start, timedelta=timedelta,
        milestones=milestones, all_recurring=all_recurring, recurring_due=recurring_due,
        recurring_status=recurring_status, week_focus=week_focus,
        unclosed_meetings=unclosed_meetings, unclosed_meeting_risks=unclosed_meeting_risks,
    )


@main_bp.route('/quick-todo', methods=['POST'])
@login_required
def quick_todo():
    """Create todo from homepage. Supports both form and JSON."""
    is_ajax = request.is_json
    if is_ajax:
        data = request.get_json() or {}
        title = (data.get('title') or '').strip()
        req_id = data.get('req_id')
        category = data.get('category', 'work')
        target_uid = data.get('user_id') if isinstance(data.get('user_id'), int) else None
    else:
        title = request.form.get('title', '').strip()
        req_id = request.form.get('req_id', type=int)
        category = request.form.get('category', 'work')
        target_uid = request.form.get('user_id', type=int)

    next_url = request.form.get('next') or request.args.get('next')
    # Target user: default to current_user, allow specifying another user (for team page)
    todo_user_id = target_uid or current_user.id

    if not title:
        return jsonify(ok=False) if is_ajax else redirect(next_url or url_for('main.index'))

    if category not in ('work', 'team', 'personal', 'risk'):
        category = 'work'
    today = date.today()

    # Handle #comment → add as requirement-level comment (not tied to specific todo)
    if title.startswith('#') and req_id:
        comment_text = title[1:].strip()
        if comment_text:
            from app.models.requirement import Activity
            from app.models.requirement import Comment as ReqComment
            db.session.add(ReqComment(
                requirement_id=req_id, user_id=current_user.id, content=comment_text,
            ))
            db.session.add(Activity(
                requirement_id=req_id, user_id=current_user.id,
                action='commented', detail=comment_text,
            ))
            db.session.commit()
            return jsonify(ok=True, title=comment_text, req_id=req_id,
                           user=current_user.name, action='comment') if is_ajax else redirect(url_for('main.index'))

    # Handle @name or @group → create todos for target(s)
    at_target = None
    if title.startswith('@'):
        import re
        m = re.match(r'@(\S+)\s*(.*)', title)
        if m:
            at_target = m.group(1)
            title = m.group(2).strip() or f'来自 {current_user.name}'

    reqs = []
    if req_id:
        req = db.session.get(Requirement, req_id)
        if req:
            reqs = [req]

    if at_target:
        from app.models.user import Group
        # Check if @target is a group name
        group = Group.query.filter_by(name=at_target).first()
        if group:
            # Group broadcast: create todo for all active members in group
            members = User.query.filter_by(group=at_target, is_active=True)\
                .filter(User.id != current_user.id).all()
            for member in members:
                t = Todo(user_id=member.id, title=title, due_date=today,
                         category=category, requirements=reqs)
                t.items.append(TodoItem(title=title, sort_order=0))
                db.session.add(t)
            # Also create for the target user
            my_todo = Todo(user_id=todo_user_id, title=title, due_date=today,
                           category=category, requirements=reqs)
            my_todo.items.append(TodoItem(title=title, sort_order=0))
            db.session.add(my_todo)
            db.session.commit()
            result = {'ok': True, 'title': title, 'todo_id': my_todo.id,
                      'helper': f'{at_target}({len(members)+1}人)', 'is_help': False}
            return jsonify(**result) if is_ajax else redirect(next_url or url_for('main.index'))

        # Single person help
        helper = User.query.filter(
            db.or_(User.name == at_target, User.pinyin.ilike(f'{at_target}%'))
        ).filter_by(is_active=True).first()
        if helper and helper.id != todo_user_id:
            my_todo = Todo(user_id=todo_user_id, title=title, due_date=today,
                           category=category, source='help', requirements=reqs)
            my_todo.items.append(TodoItem(title=title, sort_order=0))
            db.session.add(my_todo)
            db.session.flush()
            helper_todo = Todo(user_id=helper.id, title=title, due_date=today + timedelta(days=7),
                               category=category, source='help', parent_id=my_todo.id, requirements=reqs)
            helper_todo.items.append(TodoItem(title=title, sort_order=0))
            db.session.add(helper_todo)
            db.session.commit()
            result = {'ok': True, 'title': title, 'todo_id': my_todo.id,
                      'helper': helper.name, 'is_help': True}
            return jsonify(**result) if is_ajax else redirect(next_url or url_for('main.index'))

    # Normal todo (auto_done: create as already completed, for activity tracking)
    auto_done = data.get('auto_done', False) if is_ajax else False
    todo = Todo(
        user_id=todo_user_id, title=title, due_date=today,
        category=category, requirements=reqs,
    )
    if auto_done:
        todo.status = TODO_STATUS_DONE
        todo.done_date = today
    todo.items.append(TodoItem(title=title, sort_order=0, is_done=auto_done))
    db.session.add(todo)
    db.session.commit()
    return jsonify(ok=True, title=title, todo_id=todo.id) if is_ajax else redirect(next_url or url_for('main.index'))


@main_bp.route('/api/site-setting', methods=['POST'])
@login_required
def api_site_setting():
    """Save a site-wide setting (key-value)."""
    from app.models.site_setting import SiteSetting
    data = request.get_json() or {}
    key = data.get('key', '').strip()
    value = data.get('value', '')
    if not key:
        return jsonify(ok=False)
    SiteSetting.set(key, value)
    return jsonify(ok=True)


@main_bp.route('/api/activity', methods=['POST'])
@login_required
def save_activity():
    """Save a quick activity timer record (meeting/review/break/other)."""
    from app.models.activity_timer import ActivityTimer
    data = request.get_json() or {}
    activity = data.get('activity', '').strip()
    label = data.get('label', '').strip()
    minutes = data.get('minutes', 0)
    if not activity or minutes < 1:
        return jsonify(ok=False)
    # Prefer explicit date+time strings (no timezone issues)
    date_str = data.get('date')
    time_str = data.get('time')
    if date_str and time_str:
        started_at = datetime.strptime(f'{date_str} {time_str}', '%Y-%m-%d %H:%M')
    else:
        started_at_ms = data.get('start')
        if not started_at_ms:
            return jsonify(ok=False)
        started_at = datetime.fromtimestamp(started_at_ms / 1000)
    rec = ActivityTimer(
        user_id=current_user.id, activity=activity, label=label,
        started_at=started_at, minutes=minutes, date=started_at.date(),
    )
    db.session.add(rec)
    db.session.commit()
    return jsonify(ok=True, id=rec.id)


@main_bp.route('/api/batch-adopt', methods=['POST'])
@login_required
def batch_adopt():
    """Adopt multiple AI-recommended todos at once."""
    data = request.get_json() or {}
    todos_data = data.get('todos', [])
    today = date.today()
    results = []
    for item in todos_data:
        title = (item.get('title') or '').strip()
        if not title:
            continue
        req_id = item.get('req_id')
        reqs = []
        if req_id:
            req = db.session.get(Requirement, req_id)
            if req:
                reqs = [req]
        reason = (item.get('reason') or '').strip()
        full_title = f'{title}（{reason}）' if reason else title
        todo = Todo(user_id=current_user.id, title=full_title, due_date=today,
                    category='work', source='ai', requirements=reqs)
        todo.items.append(TodoItem(title=full_title, sort_order=0))
        db.session.add(todo)
        db.session.flush()
        results.append({'todo_id': todo.id, 'title': full_title, 'req_id': req_id or 0})
    db.session.commit()
    return jsonify(ok=True, count=len(results), items=results)


@main_bp.route('/api/ai-recommend-todos', methods=['POST'])
@login_required
def ai_recommend_todos():
    """AI recommends today's todos based on requirements, deadlines, and recent work."""
    from app.services.ai import call_ollama
    from app.services.prompts import get_prompt

    today = date.today()

    # Gather context: active requirements with progress
    my_reqs_list = Requirement.query.filter_by(assignee_id=current_user.id)\
        .filter(Requirement.status.notin_(REQ_INACTIVE_STATUSES))\
        .order_by(Requirement.priority, Requirement.due_date).all()
    if not my_reqs_list:
        return jsonify(ok=False, msg='暂无进行中的需求')

    # Build req_number → req_id map for adopt
    req_map = {r.number: r.id for r in my_reqs_list}

    # Recent todos (last 5 days) for continuity
    recent = Todo.query.filter_by(user_id=current_user.id)\
        .filter(Todo.created_date >= today - timedelta(days=5))\
        .options(joinedload(Todo.requirements)).all()

    # Today's existing todos to avoid duplicates
    today_titles = {t.title.lower() for t in recent if t.created_date == today and t.status == TODO_STATUS_TODO}

    lines = ['当前日期：' + today.strftime('%Y-%m-%d')]
    lines.append('\n我的需求：')
    for r in my_reqs_list:
        days_left = (r.due_date - today).days if r.due_date else 999
        if days_left < 0:
            urgency = f'🔴已延期{-days_left}天！'
            due = f'截止{r.due_date.strftime("%m-%d")}(已延期{-days_left}天)'
        elif days_left <= 3:
            urgency = f'⚠️仅剩{days_left}天！'
            due = f'截止{r.due_date.strftime("%m-%d")}(仅剩{days_left}天)'
        elif days_left <= 7:
            urgency = f'⏰剩{days_left}天'
            due = f'截止{r.due_date.strftime("%m-%d")}(剩{days_left}天)'
        else:
            urgency = ''
            due = f'截止{r.due_date.strftime("%m-%d")}(剩{days_left}天)' if r.due_date else '无截止日'
        # Analyze investment status
        invested = sum(1 for t in recent if any(req.id == r.id for req in t.requirements))
        if invested == 0:
            invest_warn = '⚠️近5天无投入，需要关注'
        elif invested <= 2:
            invest_warn = f'近5天投入较少({invested}个todo)'
        else:
            invest_warn = f'近5天持续投入中({invested}个todo)'
        children = f'，子需求{len(r.children)}个' if r.children else ''
        lines.append(f'  {urgency}{r.number} {r.title}（{r.status_label}，{due}，预估{r.estimate_days or "?"}人天，{invest_warn}{children}）')

    if recent:
        lines.append('\n近5天工作记录：')
        for t in recent:
            status = '✓' if t.status == TODO_STATUS_DONE else '○'
            req_tag = t.requirements[0].number if t.requirements else '无需求'
            lines.append(f'  {status} [{req_tag}] {t.title} ({t.created_date.strftime("%m-%d")})')

    # My open risks
    from app.models.risk import Risk
    my_risks_ai = Risk.query.filter(
        Risk.status == 'open',
        db.or_(Risk.tracker_id == current_user.id, Risk.created_by == current_user.id),
    ).order_by(Risk.due_date).all()
    if my_risks_ai:
        lines.append('\n我的风险&问题：')
        for r in my_risks_ai:
            r_days = (r.due_date - today).days if r.due_date else 999
            r_status = f'已延期{-r_days}天' if r_days < 0 else f'剩{r_days}天'
            lines.append(f'  🔥 {r.title}（{r.severity_label}，{r_status}）')

    if today_titles:
        lines.append('\n今天已有的任务（不要重复）：')
        for title in today_titles:
            lines.append(f'  - {title}')

    # Recurring todos due today — tell AI about them, return IDs for frontend highlighting
    from app.models.recurring_completion import RecurringCompletion
    from app.models.recurring_todo import RecurringTodo
    due_recurring = [r for r in RecurringTodo.query.filter_by(
        user_id=current_user.id, is_active=True).all() if r.is_due_today()]
    # Filter out already completed today
    recurring_highlight_ids = []
    if due_recurring:
        done_ids = set(c.recurring_id for c in RecurringCompletion.query.filter(
            RecurringCompletion.user_id == current_user.id,
            RecurringCompletion.recurring_id.in_([r.id for r in due_recurring]),
            RecurringCompletion.completed_date == today).all())
        not_done = [r for r in due_recurring if r.id not in done_ids]
        if not_done:
            lines.append('\n今日到期的周期任务（仅供参考，不要作为推荐项输出）：')
            for r in not_done:
                lines.append(f'  - {r.title}')
                recurring_highlight_ids.append(r.id)

    prompt = get_prompt('todo_recommend') + '\n\n' + '\n'.join(lines)
    result, _ = call_ollama(prompt)
    if not result:
        return jsonify(ok=False, msg='AI 推荐失败，请重试')
    if isinstance(result, dict):
        result = [result]
    if not isinstance(result, list):
        return jsonify(ok=False, msg='AI 返回格式异常')

    todos = []
    for item in result:
        if isinstance(item, dict) and item.get('title'):
            req_num = item.get('req_number', '')
            t = {
                'title': item['title'],
                'req_number': req_num,
                'req_id': req_map.get(req_num, 0),
                'reason': item.get('reason', ''),
                'est_min': item.get('est_min', 0),
            }
            todos.append(t)
    return jsonify(ok=True, todos=todos, recurring_highlight_ids=recurring_highlight_ids)


@main_bp.route('/api/move-todo', methods=['POST'])
@login_required
def move_todo():
    """Move a todo to a different requirement (or to team/risk)."""
    data = request.get_json() or {}
    todo_id = data.get('todo_id')
    target_req_id = data.get('req_id')  # int or 'team'/'risk'/'personal'
    todo = db.session.get(Todo, todo_id)
    if not todo:
        return jsonify(ok=False)

    # Clear old requirements
    todo.requirements = []
    if isinstance(target_req_id, int) and target_req_id > 0:
        req = db.session.get(Requirement, target_req_id)
        if req:
            todo.requirements = [req]
            todo.category = 'work'
    elif target_req_id == 'team':
        todo.category = 'team'
    elif target_req_id == 'risk':
        todo.category = 'risk'
    elif target_req_id == 'personal':
        todo.category = 'personal'
    db.session.commit()
    return jsonify(ok=True)


@main_bp.route('/api/reassign-todo', methods=['POST'])
@login_required
def reassign_todo():
    """Reassign a todo to another user (team collaboration)."""
    data = request.get_json() or {}
    todo_id = data.get('todo_id')
    target_user_id = data.get('target_user_id')
    if not todo_id or not target_user_id:
        return jsonify(ok=False, msg='参数缺失')
    todo = db.session.get(Todo, todo_id)
    target_user = db.session.get(User, target_user_id)
    if not todo or not target_user:
        return jsonify(ok=False, msg='数据不存在')
    if todo.user_id == int(target_user_id):
        return jsonify(ok=True, msg='无需转交')  # Same user, no-op
    old_user = db.session.get(User, todo.user_id)
    old_name = old_user.name if old_user else '未知'
    # Reassign todo and its child help-request todos
    todo.user_id = int(target_user_id)
    for child in todo.children:
        child.user_id = int(target_user_id)
    db.session.commit()
    return jsonify(ok=True, old_user=old_name, new_user=target_user.name, title=todo.title)


@main_bp.route('/api/users')
@login_required
def api_users():
    """Return active users for @autocomplete."""
    users = User.query.filter_by(is_active=True).order_by(User.name).all()
    return jsonify([{'id': u.id, 'name': u.name, 'pinyin': u.pinyin or '',
                      'employee_id': u.employee_id, 'manager': u.manager or ''} for u in users])


@main_bp.route('/api/personnel/options')
@login_required
def api_personnel_options():
    """Return roles, groups, domains for add-personnel modal."""
    import re
    from flask import current_app
    from app.models.user import Group, Role

    hidden = current_app.config.get('HIDDEN_ROLES', [])
    roles = Role.query.filter(Role.name.notin_(hidden)).order_by(Role.name).all()
    groups = Group.query.filter_by(is_hidden=False).order_by(Group.name).all()
    DEFAULT_DOMAINS = ['芯片验证', '业务开发', '技术开发', '编译器', '算法', '芯片', '产品', '功能仿真', '性能仿真', '产品测试']
    db_domains = set(u.domain for u in User.query.filter(User.domain.isnot(None), User.domain != '').all())
    all_domains = sorted(db_domains | set(DEFAULT_DOMAINS))

    role_cfg = {r['name']: r.get('desc', '') for r in current_app.config.get('ROLES', [])}
    return jsonify(
        roles=[{'id': r.id, 'name': r.name, 'desc': role_cfg.get(r.name, r.description or '')} for r in roles],
        groups=[g.name for g in groups],
        domains=all_domains,
    )


@main_bp.route('/api/pinyin-initial')
@login_required
def api_pinyin_initial():
    """Return the lowercase pinyin initial of a Chinese name."""
    from app.utils.pinyin import to_pinyin
    name = request.args.get('name', '').strip()
    if not name:
        return jsonify(initial='')
    py = to_pinyin(name)
    # to_pinyin returns e.g. "zs zhangsan", take first char
    initial = py[0].lower() if py else ''
    return jsonify(initial=initial if initial.isalpha() else '')


@main_bp.route('/api/personnel/add', methods=['POST'])
@login_required
def api_add_personnel():
    """Add a new personnel record (external user)."""
    import re
    from flask import current_app
    from app.models.user import Role
    from app.utils.pinyin import to_pinyin
    from app.services.audit import log_audit

    EID_FULL_RE = r'^[a-z](00\d{6}|\d00\d{7})$'
    EID_NUM_RE = r'^(00\d{6}|\d00\d{7})$'
    data = request.get_json() or {}
    eid = (data.get('employee_id') or '').strip()
    name = (data.get('name') or '').strip()
    role_id = data.get('role_id')
    domain = (data.get('domain') or '').strip()
    group = (data.get('group') or '').strip() or None
    manager = (data.get('manager') or '').strip() or None

    if not name or len(name) < 2:
        return jsonify(ok=False, msg='姓名至少2个字符')
    if not eid:
        return jsonify(ok=False, msg='请输入工号')
    if re.match(EID_NUM_RE, eid):
        # No prefix, auto-generate from name pinyin
        py = to_pinyin(name)
        prefix = py[0].lower() if py and py[0].isalpha() else ''
        if not prefix:
            return jsonify(ok=False, msg='无法从姓名生成工号首字母')
        eid = prefix + eid
    elif not re.match(EID_FULL_RE, eid):
        return jsonify(ok=False, msg='工号格式错误，如 a00123456、00123456 或 3001234567')
    if not role_id:
        return jsonify(ok=False, msg='请选择角色')
    if not domain:
        return jsonify(ok=False, msg='请填写业务领域')
    if manager:
        mgr_parts = manager.rsplit(' ', 1)
        if len(mgr_parts) == 2 and re.match(r'^[a-z]?(00\d{6}|\d00\d{7})$', mgr_parts[1]):
            pass  # "姓名 工号" or "姓名 纯数字工号"
        else:
            mgr_user = User.query.filter_by(name=manager.strip(), is_active=True).first()
            if not mgr_user and len(mgr_parts) == 2:
                mgr_user = User.query.filter_by(name=mgr_parts[0].strip(), is_active=True).first()
            if mgr_user:
                manager = f'{mgr_user.name} {mgr_user.employee_id}'
            else:
                return jsonify(ok=False, msg='主管未找到，请输入 姓名 工号')

    # Check hidden roles
    hidden = current_app.config.get('HIDDEN_ROLES', [])
    role = db.session.get(Role, role_id)
    if not role or role.name in hidden:
        return jsonify(ok=False, msg='无效的角色')

    # Check duplicate employee_id
    if User.query.filter_by(employee_id=eid).first():
        return jsonify(ok=False, msg=f'工号 {eid} 已存在')

    user = User(
        employee_id=eid,
        name=name,
        ip_address=f'pending-{eid}',
        pinyin=to_pinyin(name),
        group=group,
        domain=domain,
        manager=manager,
        is_active=True,
    )
    user.roles.append(role)
    db.session.add(user)
    db.session.flush()  # get user.id for audit log

    log_audit('create', 'user', user.id, name,
              f'录入人员 {name} ({eid})，角色 {role.name}，业务领域 {domain}')
    db.session.commit()
    return jsonify(ok=True, id=user.id, name=name)


@main_bp.route('/api/notifications')
@login_required
def api_notifications():
    """Return unread notifications for current user."""
    from app.models.notification import Notification
    items = Notification.query.filter_by(user_id=current_user.id, is_read=False)\
        .order_by(Notification.created_at.desc()).limit(20).all()
    return jsonify([{
        'id': n.id, 'type': n.type, 'type_label': n.type_label,
        'icon': n.type_icon, 'title': n.title, 'link': n.link,
        'time': n.created_at.strftime('%m-%d %H:%M'),
    } for n in items])


@main_bp.route('/api/notifications/read', methods=['POST'])
@login_required
def api_notifications_read():
    """Mark notifications as read."""
    from app.models.notification import Notification
    data = request.get_json() or {}
    nid = data.get('id')
    if nid == 'all':
        Notification.query.filter_by(user_id=current_user.id, is_read=False).update({'is_read': True})
    elif nid:
        n = db.session.get(Notification, int(nid))
        if n and n.user_id == current_user.id:
            n.is_read = True
    db.session.commit()
    return jsonify(ok=True)


@main_bp.route('/api/email-settings/<entity_type>/<int:entity_id>')
@login_required
def api_email_settings_get(entity_type, entity_id):
    """Get saved email settings for an entity."""
    from app.models.email_setting import EmailSetting
    s = EmailSetting.query.filter_by(entity_type=entity_type, entity_id=entity_id).first()
    if s:
        return jsonify(ok=True, subject=s.subject or '', to=s.to_list or '', cc=s.cc_list or '')
    return jsonify(ok=True, subject='', to='', cc='')


@main_bp.route('/api/email-settings/<entity_type>/<int:entity_id>', methods=['POST'])
@login_required
def api_email_settings_save(entity_type, entity_id):
    """Save email settings for an entity."""
    from app.models.email_setting import EmailSetting
    data = request.get_json() or {}
    s = EmailSetting.query.filter_by(entity_type=entity_type, entity_id=entity_id).first()
    if not s:
        s = EmailSetting(entity_type=entity_type, entity_id=entity_id)
        db.session.add(s)
    s.subject = (data.get('subject') or '').strip() or None
    s.to_list = (data.get('to') or '').strip() or None
    s.cc_list = (data.get('cc') or '').strip() or None
    s.updated_by = current_user.id
    db.session.commit()
    return jsonify(ok=True)


@main_bp.route('/api/search')
@login_required
def api_search():
    """Global search API for Cmd+K modal."""
    from app.services.search import search
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify(ok=True, results=[])
    results = search(q, current_user_id=current_user.id, is_manager=current_user.is_team_manager)
    # Add URLs for each result
    url_map = {
        'requirement': lambda r: url_for('requirement.requirement_detail', req_id=int(r['id'])),
        'todo': lambda r: url_for('todo.team'),
        'project': lambda r: url_for('project.project_detail', project_id=int(r['id'])),
        'user': lambda r: url_for('admin.user_list'),
        'meeting': lambda r: url_for('project.meeting_detail', project_id=r.get('project_id', 1), meeting_id=int(r['id'])),
        'risk': lambda r: url_for('project.risk_list', project_id=r.get('project_id', 1)),
        'aar': lambda r: url_for('project.aar_list', project_id=r.get('project_id', 1)),
    }
    type_labels = {'requirement': '需求', 'todo': 'Todo', 'project': '项目',
                   'user': '用户', 'meeting': '会议', 'risk': '风险', 'aar': 'AAR复盘'}
    for r in results:
        fn = url_map.get(r['type'])
        r['url'] = fn(r) if fn else '#'
        r['type_label'] = type_labels.get(r['type'], r['type'])
    return jsonify(ok=True, results=results)


@main_bp.route('/todo/<int:todo_id>/toggle', methods=['POST'])
@login_required
def toggle_todo(todo_id):
    """Toggle todo done/undone from homepage."""
    todo = db.session.get(Todo, todo_id)
    if not todo:
        return jsonify(ok=False) if request.is_json else redirect(url_for('main.index'))
    if todo.status == TODO_STATUS_DONE:
        todo.status = TODO_STATUS_TODO
        todo.done_date = None
        for item in todo.items:
            item.is_done = False
    else:
        todo.status = TODO_STATUS_DONE
        todo.done_date = date.today()
        for item in todo.items:
            item.is_done = True
    # Cascade status to linked help todos (parent↔child)
    linked = []
    if todo.parent_id:
        linked.append(db.session.get(Todo, todo.parent_id))
    linked.extend(Todo.query.filter_by(parent_id=todo.id).all())
    for t in linked:
        if t and t.status != todo.status:
            t.status = todo.status
            t.done_date = todo.done_date
            for item in t.items:
                item.is_done = (todo.status == TODO_STATUS_DONE)
    db.session.commit()
    if request.is_json:
        return jsonify(ok=True, done=todo.status == TODO_STATUS_DONE)
    return redirect(url_for('main.index'))


# ---- AI: Daily Standup Summary ----

@main_bp.route('/api/daily-standup', methods=['POST'])
@login_required
def daily_standup():
    """Generate daily standup summary for current user's team."""
    import markdown as md_lib

    from app.models.risk import Risk
    from app.services.ai import call_ollama
    from app.services.prompts import get_prompt

    today = date.today()
    yesterday = today - timedelta(days=1)
    if today.weekday() == 0:  # Monday → look back to Friday
        yesterday = today - timedelta(days=3)

    users = User.query.filter_by(is_active=True).order_by(User.name).all()
    lines = [f'日期：{today}（昨天：{yesterday}）\n']

    for u in users:
        done_yesterday = Todo.query.filter(
            Todo.user_id == u.id, Todo.done_date == yesterday
        ).options(joinedload(Todo.requirements)).all()
        active_today = Todo.query.filter(
            Todo.user_id == u.id, Todo.status == 'todo'
        ).options(joinedload(Todo.requirements)).limit(10).all()
        blocked = [t for t in active_today if t.need_help]

        lines.append(f'\n{u.name}（{u.group or ""}）：')
        if done_yesterday:
            lines.append('  昨日完成：')
            for t in done_yesterday:
                reqs = ', '.join(r.number for r in t.requirements)
                lines.append(f'  - {t.title}（{reqs}）')
        else:
            lines.append('  昨日完成：无')

        if active_today:
            lines.append('  今日进行中：')
            for t in active_today[:5]:
                reqs = ', '.join(r.number for r in t.requirements)
                lines.append(f'  - {t.title}（{reqs}）')
        if blocked:
            lines.append('  阻塞：')
            for t in blocked:
                reason = f'，原因：{t.blocked_reason}' if t.blocked_reason else ''
                lines.append(f'  - {t.title}{reason}')

    # Overdue requirements
    from app.models.requirement import Requirement
    overdue_reqs = Requirement.query.filter(
        Requirement.status.notin_(('done', 'closed', 'cancelled')),
        Requirement.due_date < today
    ).all()
    if overdue_reqs:
        lines.append('\n全组延期需求：')
        for r in overdue_reqs:
            days = (today - r.due_date).days
            lines.append(f'- [{r.number}] {r.title}（延期{days}天，{r.assignee_display}）')

    # Open risks
    open_risks = Risk.query.filter_by(status='open').filter(Risk.deleted_at.is_(None)).all()
    if open_risks:
        lines.append('\n未解决风险：')
        for r in open_risks:
            lines.append(f'- {r.title}（{r.severity_label}）')

    prompt = get_prompt('daily_standup') + '\n\n' + '\n'.join(lines)
    _, raw = call_ollama(prompt)
    if raw:
        html = md_lib.markdown(raw, extensions=['tables'])
        return jsonify(ok=True, html=html)
    return jsonify(ok=False, error='生成失败')


# ---- Daily Progress Report ----

@main_bp.route('/api/daily-progress', methods=['POST'])
@login_required
def daily_progress():
    """Generate formatted daily progress for current user."""
    from app.models.requirement import Requirement
    from app.models.risk import Risk

    today = date.today()

    # Only business todos (risk + requirement linked), not team/personal
    all_biz = Todo.query.filter(
        Todo.user_id == current_user.id,
        Todo.category.in_(['work', 'risk']),
    ).options(joinedload(Todo.requirements)).all()

    done_today = [t for t in all_biz if t.done_date == today]
    active = [t for t in all_biz if t.status == 'todo']
    blocked = [t for t in active if t.need_help]

    # Requirement progress (completion %)
    my_reqs = Requirement.query.filter(
        Requirement.assignee_id == current_user.id,
        Requirement.status.notin_(('done', 'closed', 'cancelled')),
    ).options(joinedload(Requirement.project)).all()

    # Build person context
    from app.models.project_member import ProjectMember
    my_roles = '、'.join(r.name for r in current_user.roles) or '成员'
    lines = [f'汇报人：{current_user.name}（{my_roles}，{current_user.group or ""}）']

    # Collect project members from related projects
    project_ids = set(r.project_id for r in my_reqs if r.project_id)
    if project_ids:
        members = ProjectMember.query.filter(
            ProjectMember.project_id.in_(project_ids)
        ).all()
        if members:
            lines.append('项目成员：')
            seen = set()
            for m in members:
                if m.user_id and m.user_id not in seen:
                    seen.add(m.user_id)
                    u = db.session.get(User, m.user_id)
                    if u:
                        u_roles = '、'.join(r.name for r in u.roles) or '成员'
                        lines.append(f'  - {u.name}（{u_roles}，项目角色：{m.project_role}）')
                elif m.external_name and m.external_name not in seen:
                    seen.add(m.external_name)
                    lines.append(f'  - {m.external_name}（外部，项目角色：{m.project_role}）')

    lines.append(f'\n【{today.strftime("%Y-%m-%d")}】进展：')

    if done_today:
        for i, t in enumerate(done_today, 1):
            reqs = '、'.join(r.number for r in t.requirements)
            suffix = f'（{reqs}）' if reqs else ''
            lines.append(f'{i}. {t.title}{suffix}')
    else:
        lines.append('（暂无完成项）')

    if active:
        lines.append('')
        lines.append('进行中：')
        for i, t in enumerate(active, 1):
            reqs = '、'.join(r.number for r in t.requirements)
            suffix = f'（{reqs}）' if reqs else ''
            overdue = f'，延{t.workdays_overdue}天' if t.workdays_overdue else ''
            lines.append(f'{i}. {t.title}{suffix}{overdue}')

    # Requirement completion %
    if my_reqs:
        lines.append('')
        lines.append('需求进度：')
        for r in my_reqs:
            total = Todo.query.filter(
                Todo.user_id == current_user.id
            ).join(todo_requirements, Todo.id == todo_requirements.c.todo_id)\
             .filter(todo_requirements.c.requirement_id == r.id).count()
            done = Todo.query.filter(
                Todo.user_id == current_user.id, Todo.status == 'done'
            ).join(todo_requirements, Todo.id == todo_requirements.c.todo_id)\
             .filter(todo_requirements.c.requirement_id == r.id).count()
            pct = round(done / total * 100) if total else 0
            due_info = f'，截止{r.due_date.strftime("%m-%d")}' if r.due_date else ''
            overdue_info = f'，已超期{(today - r.due_date).days}天' if r.due_date and r.due_date < today else ''
            lines.append(f'- [{r.number}] {r.title}：完成{pct}%（{done}/{total}）{due_info}{overdue_info}')

    # Blocked todos + open risks → "当前问题"
    open_risks = Risk.query.filter(
        Risk.status == 'open',
        db.or_(Risk.tracker_id == current_user.id, Risk.created_by == current_user.id),
    ).all()
    if blocked or open_risks:
        lines.append('')
        lines.append('当前问题：')
        idx = 1
        for t in blocked:
            days = t.workdays_overdue or 0
            owner = current_user.name
            owner_role = my_roles
            if t.requirements:
                req = t.requirements[0]
                if req.assignee_id and req.assignee_id != current_user.id:
                    assignee_user = db.session.get(User, req.assignee_id)
                    if assignee_user:
                        owner = assignee_user.name
                        owner_role = '、'.join(r.name for r in assignee_user.roles) or '成员'
                    else:
                        owner = req.assignee_display
                        owner_role = ''
            reason = t.blocked_reason or '待解决'
            role_tag = f'（{owner_role}）' if owner_role else ''
            lines.append(f'{idx}. {t.title}——责任人：{owner}{role_tag}，阻塞{days}天 / {reason}')
            idx += 1
        for r in open_risks:
            tracker = db.session.get(User, r.tracker_id)
            tracker_name = tracker.name if tracker else '未指定'
            tracker_role = ('、'.join(rl.name for rl in tracker.roles) if tracker else '')
            role_tag = f'（{tracker_role}）' if tracker_role else ''
            days = (today - r.due_date).days if r.due_date and r.due_date < today else 0
            due_info = f'超期{days}天' if days > 0 else (f'截止{r.due_date.strftime("%m-%d")}' if r.due_date else '')
            lines.append(f'{idx}. [风险] {r.title}（{r.severity_label}）——跟踪人：{tracker_name}{role_tag}，{due_info}')
            idx += 1

    raw_data = '\n'.join(lines)

    # No data at all — return as-is, don't call AI
    if not done_today and not active and not my_reqs:
        return jsonify(ok=True, text=raw_data)

    # Let AI format it nicely
    from app.services.ai import call_ollama
    prompt = (
        '你是一个研发日报助手。将以下原始数据整理成格式化的每日进展报告。\n'
        f'当前用户：{current_user.name}\n\n'
        '输出格式（纯文本，不要 JSON、不要 markdown）：\n'
        f'【{today.strftime("%Y-%m-%d")}】进展：\n'
        '1. 完成的事项（过去式描述成果）\n\n'
        '进行中：\n'
        '1. 正在做的事项（描述当前进度）\n\n'
        '当前问题：\n'
        f'1. 具体问题描述——责任人：{current_user.name}，阻塞N天/预期解决时间x.x\n\n'
        '红线规则（违反则输出无效）：\n'
        '1. 严禁编造原始数据中不存在的任务、人名、数字\n'
        '2. 责任人/跟踪人必须使用原始数据中出现的人名，不能编造\n'
        '3. 问题描述必须写具体内容（如"SSO token刷新接口未修复"），不要写"问题描述"四个字\n'
        '4. 没有数据的部分直接省略，不要输出空段落\n'
        '5. 可以合并相似任务、润色措辞，但不能添加不存在的内容\n\n'
        '原始数据：\n' + raw_data
    )
    _, ai_text = call_ollama(prompt)
    if ai_text:
        return jsonify(ok=True, text=ai_text)
    return jsonify(ok=True, text=raw_data)


# ---- Recurring Todos ----

@main_bp.route('/recurring-todos')
@login_required
def recurring_list():
    from app.models.recurring_todo import RecurringTodo
    items = RecurringTodo.query.filter_by(user_id=current_user.id, is_active=True)\
        .order_by(RecurringTodo.cycle, RecurringTodo.title).all()
    return render_template('main/recurring.html', items=items, today=date.today())


@main_bp.route('/recurring-todos/add', methods=['POST'])
@login_required
def recurring_add():
    from app.models.recurring_todo import RecurringTodo
    title = request.form.get('title', '').strip()
    cycle = request.form.get('cycle', 'weekly')
    weekday_list = request.form.getlist('weekdays')
    period_list = request.form.getlist('monthly_periods')
    if title:
        if cycle == 'weekdays' and weekday_list:
            # Each weekday gets its own record
            for wd in weekday_list:
                db.session.add(RecurringTodo(
                    user_id=current_user.id, title=title, cycle='weekdays',
                    weekdays=wd))
        elif cycle == 'monthly' and period_list:
            # Each period gets its own record
            for p in period_list:
                db.session.add(RecurringTodo(
                    user_id=current_user.id, title=title, cycle='monthly',
                    monthly_days=p))
        else:
            db.session.add(RecurringTodo(
                user_id=current_user.id, title=title, cycle=cycle))
        db.session.commit()
    return redirect(url_for('main.recurring_list'))


@main_bp.route('/recurring-todos/<int:rid>/delete', methods=['POST'])
@login_required
def recurring_delete(rid):
    from app.models.recurring_todo import RecurringTodo
    r = db.get_or_404(RecurringTodo, rid)
    if r.user_id == current_user.id:
        from app.models.recurring_completion import RecurringCompletion
        RecurringCompletion.query.filter_by(recurring_id=r.id).delete()
        db.session.delete(r)
        db.session.commit()
    if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify(ok=True)
    return redirect(url_for('main.recurring_list'))


@main_bp.route('/recurring-todos/ai-recommend', methods=['POST'])
@login_required
def recurring_ai_recommend():
    """AI recommends which due recurring todos to import into today's todo."""
    from app.models.recurring_todo import RecurringTodo
    from app.services.ai import call_ollama
    from app.services.prompts import get_prompt

    # Get today's due recurring todos
    all_recurring = RecurringTodo.query.filter_by(user_id=current_user.id, is_active=True).all()
    due_today = [r for r in all_recurring if r.is_due_today()]

    if not due_today:
        return jsonify(ok=True, items=[], msg='今天没有到期的周期任务')

    # Current workload
    active_count = Todo.query.filter_by(user_id=current_user.id, status='todo').count()

    lines = [
        f'用户：{current_user.name}，角色：{current_user.role_names or "开发"}',
        f'当前进行中 {active_count} 个任务',
        '',
        '今日到期的周期任务：',
    ]
    for r in due_today:
        lines.append(f'- {r.title}（{r.schedule_desc}）')

    prompt = get_prompt('recurring_recommend') + '\n\n' + '\n'.join(lines)
    result, raw = call_ollama(prompt)

    if isinstance(result, list):
        return jsonify(ok=True, items=result)
    return jsonify(ok=False, raw=raw or '生成失败')


@main_bp.route('/recurring-todos/<int:rid>/toggle', methods=['POST'])
@login_required
def recurring_toggle(rid):
    """Toggle completion of a recurring todo for today (independent of daily todos)."""
    from app.models.recurring_completion import RecurringCompletion
    from app.models.recurring_todo import RecurringTodo
    r = db.get_or_404(RecurringTodo, rid)
    if r.user_id != current_user.id:
        return jsonify(ok=False), 403
    today = date.today()
    existing = RecurringCompletion.query.filter_by(
        recurring_id=rid, user_id=current_user.id, completed_date=today).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()
        return jsonify(ok=True, done=False)
    comp = RecurringCompletion(recurring_id=rid, user_id=current_user.id, completed_date=today)
    db.session.add(comp)
    db.session.commit()
    return jsonify(ok=True, done=True)


@main_bp.route('/rant', methods=['POST'])
@login_required
def post_rant():
    is_ajax = request.is_json
    if is_ajax:
        data = request.get_json() or {}
        content = (data.get('content') or '').strip()[:MAX_RANT_LENGTH]
        alias = (data.get('alias') or '').strip()[:30] or None
    else:
        content = request.form.get('content', '').strip()[:MAX_RANT_LENGTH]
        alias = request.form.get('alias', '').strip()[:30] or None
    if content:
        r = Rant(content=content, alias=alias)
        db.session.add(r)
        db.session.commit()
        if is_ajax:
            return jsonify(ok=True, id=r.id, alias=alias, content=content,
                           date=r.created_at.strftime('%m-%d'))
    if is_ajax:
        return jsonify(ok=False)
    return redirect(url_for('main.index'))


@main_bp.route('/rant/<int:rant_id>/like', methods=['POST'])
@login_required
def like_rant(rant_id):
    rant = db.session.get(Rant, rant_id)
    if rant:
        rant.likes = (rant.likes or 0) + 1
        db.session.commit()
        if request.is_json:
            return jsonify(ok=True, likes=rant.likes)
    elif request.is_json:
        return jsonify(ok=False)
    return redirect(url_for('main.index'))


@main_bp.route('/rant/<int:rant_id>/delete', methods=['POST'])
@login_required
def delete_rant(rant_id):
    if not current_user.is_admin:
        return jsonify(ok=False) if request.is_json else redirect(url_for('main.index'))
    rant = db.session.get(Rant, rant_id)
    if rant:
        db.session.delete(rant)
        db.session.commit()
        if request.is_json:
            return jsonify(ok=True)
    return redirect(url_for('main.index'))


@main_bp.route('/api/email-settings', methods=['GET'])
@login_required
def get_email_settings():
    """Get saved email settings for an entity."""
    entity_type = request.args.get('type', '')
    entity_id = request.args.get('id', 0, type=int)
    if not entity_type or not entity_id:
        return jsonify(subject='', to='', cc='')
    setting = EmailSetting.query.filter_by(entity_type=entity_type, entity_id=entity_id).first()
    if not setting:
        return jsonify(subject='', to='', cc='')
    return jsonify(subject=setting.subject or '', to=setting.to_list or '', cc=setting.cc_list or '')


@main_bp.route('/api/email-settings', methods=['POST'])
@login_required
def save_email_settings_api():
    """Save email settings for an entity (upsert)."""
    data = request.get_json() or {}
    entity_type = data.get('type', '')
    entity_id = data.get('id', 0)
    if not entity_type or not entity_id:
        return jsonify(ok=False, msg='Missing type or id')
    setting = EmailSetting.query.filter_by(entity_type=entity_type, entity_id=entity_id).first()
    if not setting:
        setting = EmailSetting(entity_type=entity_type, entity_id=entity_id)
        db.session.add(setting)
    setting.subject = data.get('subject', '')
    setting.to_list = data.get('to', '')
    setting.cc_list = data.get('cc', '')
    setting.updated_by = current_user.id
    db.session.commit()
    return jsonify(ok=True)
