from datetime import date, timedelta

from flask import render_template, request, redirect, url_for, jsonify
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload

from app.main import main_bp
from app.extensions import db
from app.constants import (
    TODO_STATUS_TODO, TODO_STATUS_DONE, REQ_INACTIVE_STATUSES,
    HEATMAP_DAYS, AI_TOKEN_RATIO, MAX_RECENT_REQS_FOR_QUICK_TODO,
    MAX_RANT_LENGTH,
)
from app.models.requirement import Requirement
from app.models.todo import Todo, TodoItem, TodoComment, todo_requirements
from app.models.risk import Risk
from app.models.incentive import Incentive
from app.models.ai_log import AIParseLog
from app.models.user import User
from app.models.rant import Rant


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
    ).options(joinedload(Todo.items), joinedload(Todo.requirements), joinedload(Todo.children))\
     .order_by(db.case((Todo.status == TODO_STATUS_TODO, 0), else_=1), Todo.sort_order).all()
    todo_total = len(my_todos)
    todo_done = sum(1 for t in my_todos if t.status == TODO_STATUS_DONE)

    # My assigned requirements (active)
    my_reqs = Requirement.query.filter_by(assignee_id=current_user.id)\
        .filter(Requirement.status.notin_(REQ_INACTIVE_STATUSES))\
        .options(joinedload(Requirement.project))\
        .order_by(Requirement.due_date.asc().nullslast(), Requirement.priority, Requirement.updated_at.desc()).limit(10).all()

    # Group todos by category for merged display
    req_todos = {}  # req_id → [todos]
    risk_todos = []
    team_todos = []
    personal_todos = []
    req_map = {r.id: r for r in my_reqs}  # Known requirements
    for t in my_todos:
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
    # Merge any extra requirements from todos into display list
    display_reqs = list(my_reqs) + [r for rid, r in req_map.items() if rid not in {x.id for x in my_reqs}]

    # My related risks
    my_risks = Risk.query.filter(
        Risk.status == 'open',
        db.or_(Risk.tracker_id == current_user.id, Risk.created_by == current_user.id),
    ).order_by(Risk.due_date).all()

    # Alerts: overdue requirements + overdue risks
    alerts = [
        f'需求 [{r.number}] {r.title} 已超期 ({r.due_date.strftime("%m-%d")})'
        for r in my_reqs if r.due_date and r.due_date < today
    ] + [
        f'风险「{r.title}」已超期 ({r.due_date.strftime("%m-%d") if r.due_date else ""})'
        for r in my_risks if r.is_overdue
    ]

    # Approved incentives: last 2 months excluding recent 7 days; fallback to 3 months if empty
    inc_end = today - timedelta(days=7)
    for months in (60, 90):
        inc_start = today - timedelta(days=months)
        approved_incentives = Incentive.query.filter(
            Incentive.status == 'approved',
            Incentive.reviewed_at >= str(inc_start),
            Incentive.reviewed_at <= str(inc_end),
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
    month_q = Rant.query.filter(Rant.created_at >= str(month_start))
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

    return render_template('main/index.html',
        my_todos=my_todos, todo_total=todo_total, todo_done=todo_done,
        my_reqs=my_reqs, my_risks=my_risks, today=today,
        req_todos=req_todos, risk_todos=risk_todos, team_todos=team_todos, personal_todos=personal_todos,
        display_reqs=display_reqs,
        approved_incentives=approved_incentives, rants=rants,
        ai_ranking=ai_ranking, alerts=alerts,
        heatmap=heatmap, heatmap_start=heatmap_start, timedelta=timedelta,
        milestones=milestones,
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
    else:
        title = request.form.get('title', '').strip()
        req_id = request.form.get('req_id', type=int)
        category = request.form.get('category', 'work')

    if not title:
        return jsonify(ok=False) if is_ajax else redirect(url_for('main.index'))

    if category not in ('work', 'team', 'personal', 'risk'):
        category = 'work'
    today = date.today()

    # Handle #summary → add comment to the most recent todo for this requirement
    if title.startswith('#') and req_id:
        comment_text = title[1:].strip()
        if comment_text:
            # Find latest active todo for this req
            latest_todo = Todo.query.filter(
                Todo.user_id == current_user.id,
            ).join(todo_requirements, Todo.id == todo_requirements.c.todo_id)\
             .filter(todo_requirements.c.requirement_id == req_id)\
             .order_by(Todo.created_at.desc()).first()
            if latest_todo:
                db.session.add(TodoComment(
                    todo_id=latest_todo.id, user_id=current_user.id, content=comment_text,
                ))
                db.session.commit()
                return jsonify(ok=True, title=comment_text, todo_id=latest_todo.id, action='comment') if is_ajax else redirect(url_for('main.index'))
            # No todo found, create as normal todo
            pass

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
            # Also create for self
            my_todo = Todo(user_id=current_user.id, title=title, due_date=today,
                           category=category, requirements=reqs)
            my_todo.items.append(TodoItem(title=title, sort_order=0))
            db.session.add(my_todo)
            db.session.commit()
            result = {'ok': True, 'title': title, 'todo_id': my_todo.id,
                      'helper': f'{at_target}({len(members)+1}人)', 'is_help': False}
            return jsonify(**result) if is_ajax else redirect(url_for('main.index'))

        # Single person help
        helper = User.query.filter(
            db.or_(User.name == at_target, User.pinyin.ilike(f'{at_target}%'))
        ).filter_by(is_active=True).first()
        if helper and helper.id != current_user.id:
            my_todo = Todo(user_id=current_user.id, title=title, due_date=today,
                           category=category, source='help', requirements=reqs)
            my_todo.items.append(TodoItem(title=title, sort_order=0))
            db.session.add(my_todo)
            db.session.flush()
            helper_todo = Todo(user_id=helper.id, title=title, due_date=today,
                               category=category, source='help', parent_id=my_todo.id, requirements=reqs)
            helper_todo.items.append(TodoItem(title=title, sort_order=0))
            db.session.add(helper_todo)
            db.session.commit()
            result = {'ok': True, 'title': title, 'todo_id': my_todo.id,
                      'helper': helper.name, 'is_help': True}
            return jsonify(**result) if is_ajax else redirect(url_for('main.index'))

    # Normal todo
    todo = Todo(
        user_id=current_user.id, title=title, due_date=today,
        category=category, requirements=reqs,
    )
    todo.items.append(TodoItem(title=title, sort_order=0))
    db.session.add(todo)
    db.session.commit()
    return jsonify(ok=True, title=title, todo_id=todo.id) if is_ajax else redirect(url_for('main.index'))


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
            todos.append({
                'title': item['title'],
                'req_number': req_num,
                'req_id': req_map.get(req_num, 0),
                'reason': item.get('reason', ''),
                'est_min': item.get('est_min', 0),
            })
    return jsonify(ok=True, todos=todos)


@main_bp.route('/api/move-todo', methods=['POST'])
@login_required
def move_todo():
    """Move a todo to a different requirement (or to team/risk)."""
    data = request.get_json() or {}
    todo_id = data.get('todo_id')
    target_req_id = data.get('req_id')  # int or 'team'/'risk'/'personal'
    todo = db.session.get(Todo, todo_id)
    if not todo or todo.user_id != current_user.id:
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


@main_bp.route('/api/users')
@login_required
def api_users():
    """Return active users for @autocomplete."""
    users = User.query.filter_by(is_active=True).order_by(User.name).all()
    return jsonify([{'id': u.id, 'name': u.name, 'pinyin': u.pinyin or '', 'employee_id': u.employee_id} for u in users])


@main_bp.route('/api/search')
@login_required
def api_search():
    """Global search API for Cmd+K modal."""
    from app.services.search import search
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify(ok=True, results=[])
    results = search(q)
    # Add URLs for each result
    url_map = {
        'requirement': lambda r: url_for('requirement.requirement_detail', req_id=int(r['id'])),
        'todo': lambda r: url_for('todo.team'),
        'project': lambda r: url_for('project.project_detail', project_id=int(r['id'])),
        'user': lambda r: url_for('admin.user_list'),
    }
    type_labels = {'requirement': '需求', 'todo': 'Todo', 'project': '项目', 'user': '用户'}
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
    if not todo or todo.user_id != current_user.id:
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
    from app.services.ai import call_ollama
    from app.services.prompts import get_prompt
    from app.models.risk import Risk
    import markdown as md_lib

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
    open_risks = Risk.query.filter_by(status='open').all()
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
