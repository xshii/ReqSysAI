from datetime import date, timedelta
from io import BytesIO

from flask import render_template, request, send_file
from flask_login import login_required, current_user
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from app.dashboard import dashboard_bp
from app.extensions import db
from app.models.user import User
from app.models.requirement import Requirement
from app.models.todo import Todo


@dashboard_bp.route('/requirements')
@login_required
def requirement_progress():
    cur_status = request.args.get('status', '')
    cur_project = request.args.get('project_id', type=int)

    query = Requirement.query.options(
        joinedload(Requirement.project),
        joinedload(Requirement.assignee),
    )
    if cur_status:
        query = query.filter_by(status=cur_status)
    if cur_project:
        query = query.filter_by(project_id=cur_project)

    requirements = query.order_by(Requirement.updated_at.desc()).all()

    # Count active todos per requirement (many-to-many)
    from app.models.todo import todo_requirements
    req_ids = [r.id for r in requirements]
    todo_counts = {}
    if req_ids:
        rows = db.session.query(
            todo_requirements.c.requirement_id,
            func.count(Todo.id),
            func.sum(db.case((Todo.status == 'done', 1), else_=0)),
        ).join(Todo, Todo.id == todo_requirements.c.todo_id)\
         .filter(todo_requirements.c.requirement_id.in_(req_ids))\
         .group_by(todo_requirements.c.requirement_id).all()
        for req_id, total, done in rows:
            todo_counts[req_id] = (total, int(done or 0))

    from app.models.project import Project
    projects = Project.query.filter_by(status='active').all()

    return render_template('dashboard/requirements.html',
        requirements=requirements, todo_counts=todo_counts,
        projects=projects, statuses=Requirement.STATUS_LABELS,
        cur_status=cur_status, cur_project=cur_project,
    )



# ---- Phase 7: Stats / AI Weekly Report / Excel Export ----

def _week_range(offset=0):
    """Return (monday, sunday) for current week + offset."""
    today = date.today()
    monday = today - timedelta(days=today.weekday()) + timedelta(weeks=offset)
    sunday = monday + timedelta(days=6)
    return monday, sunday


def _gather_stats(monday, sunday, group=None):
    """Gather todo & requirement stats for the given week."""
    from app.models.project import Project
    from collections import defaultdict

    user_query = User.query.filter_by(is_active=True)
    if group:
        user_query = user_query.filter_by(group=group)
    users = user_query.order_by(User.group, User.name).all()
    user_ids = [u.id for u in users]

    # Per-user todo stats
    created_rows = db.session.query(
        Todo.user_id, func.count(Todo.id)
    ).filter(
        Todo.user_id.in_(user_ids),
        Todo.created_date >= monday, Todo.created_date <= sunday,
    ).group_by(Todo.user_id).all()
    created_map = dict(created_rows)

    done_rows = db.session.query(
        Todo.user_id, func.count(Todo.id)
    ).filter(
        Todo.user_id.in_(user_ids),
        Todo.done_date >= monday, Todo.done_date <= sunday,
    ).group_by(Todo.user_id).all()
    done_map = dict(done_rows)

    user_stats = []
    for u in users:
        created = created_map.get(u.id, 0)
        done = done_map.get(u.id, 0)
        user_stats.append({
            'user': u,
            'created': created,
            'done': done,
            'rate': round(done / created * 100) if created else 0,
        })

    # Requirement stats
    req_total = Requirement.query.count()
    req_done = Requirement.query.filter(Requirement.status.in_(['done', 'closed'])).count()

    # ---- Per-user per-project investment (person-days) ----
    # Logic: for each user per day, count distinct projects from their todos.
    # Each project gets 1/n of a person-day.
    week_todos = Todo.query.filter(
        Todo.user_id.in_(user_ids),
        Todo.created_date >= monday, Todo.created_date <= sunday,
    ).options(joinedload(Todo.requirements)).all()

    # user_id -> date -> set of project_ids
    user_date_projects = defaultdict(lambda: defaultdict(set))
    for t in week_todos:
        for r in t.requirements:
            if r.project_id:
                user_date_projects[t.user_id][t.created_date].add(r.project_id)

    # Aggregate: (user_id, project_id) -> person-days
    user_project_days = defaultdict(float)
    for uid, date_projects in user_date_projects.items():
        for dt, pids in date_projects.items():
            share = 1.0 / len(pids) if pids else 0
            for pid in pids:
                user_project_days[(uid, pid)] += share

    # Build project investment table
    project_ids = set(pid for (_, pid) in user_project_days)
    projects = {p.id: p for p in Project.query.filter(Project.id.in_(project_ids)).all()} if project_ids else {}
    user_map = {u.id: u for u in users}

    # Structure: list of {project, users: [{user, days}], total_days}
    project_investment = []
    for pid in sorted(project_ids):
        p = projects.get(pid)
        if not p:
            continue
        user_days = []
        total = 0.0
        for u in users:
            d = user_project_days.get((u.id, pid), 0)
            if d > 0:
                user_days.append({'user': u, 'days': round(d, 1)})
                total += d
        project_investment.append({
            'project': p,
            'user_days': user_days,
            'total_days': round(total, 1),
            'people_count': len(user_days),
        })

    return {
        'user_stats': user_stats,
        'req_total': req_total,
        'req_done': req_done,
        'req_rate': round(req_done / req_total * 100) if req_total else 0,
        'project_investment': project_investment,
    }


@dashboard_bp.route('/stats')
@login_required
def stats():
    offset = request.args.get('week', 0, type=int)
    cur_group = request.args.get('group', '')
    monday, sunday = _week_range(offset)

    groups = db.session.query(User.group).filter(User.group.isnot(None), User.group != '')\
        .distinct().order_by(User.group).all()
    groups = [g[0] for g in groups]

    data = _gather_stats(monday, sunday, group=cur_group or None)

    return render_template('dashboard/stats.html',
        data=data, monday=monday, sunday=sunday,
        offset=offset, groups=groups, cur_group=cur_group,
    )


@dashboard_bp.route('/stats/export')
@login_required
def stats_export():
    """Export weekly stats as Excel."""
    import openpyxl
    from openpyxl.styles import Font, Alignment

    offset = request.args.get('week', 0, type=int)
    cur_group = request.args.get('group', '')
    monday, sunday = _week_range(offset)
    data = _gather_stats(monday, sunday, group=cur_group or None)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '周报统计'

    # Header
    ws.append([f'周报统计 {monday} ~ {sunday}'])
    ws.merge_cells('A1:D1')
    ws['A1'].font = Font(bold=True, size=14)
    ws.append([])

    # Requirement summary
    ws.append(['需求完成率', f'{data["req_done"]}/{data["req_total"]}', f'{data["req_rate"]}%'])
    ws.append([])

    # Per-user table
    ws.append(['姓名', '工号', '新建任务', '完成任务', '完成率'])
    for cell in ws[ws.max_row]:
        cell.font = Font(bold=True)
    for s in data['user_stats']:
        u = s['user']
        ws.append([u.name, u.employee_id or '', s['created'], s['done'], f'{s["rate"]}%'])

    # Project investment sheets
    for pi in data.get('project_investment', []):
        ws2 = wb.create_sheet(title=pi['project'].name[:30])
        ws2.append([f'项目: {pi["project"].name}'])
        ws2['A1'].font = Font(bold=True, size=12)
        ws2.append([f'合计: {pi["people_count"]}人 · {pi["total_days"]}人天'])
        ws2.append([])
        ws2.append(['姓名', '工号', '投入(人天)', '占比'])
        for cell in ws2[ws2.max_row]:
            cell.font = Font(bold=True)
        for ud in pi['user_days']:
            pct = round(ud['days'] / pi['total_days'] * 100) if pi['total_days'] else 0
            ws2.append([ud['user'].name, ud['user'].employee_id or '', ud['days'], f'{pct}%'])
        for col in ws2.columns:
            max_len = max((len(str(c.value or '')) for c in col), default=10)
            ws2.column_dimensions[col[0].column_letter].width = max(max_len + 2, 10)

    # Auto column width for main sheet
    for col in ws.columns:
        max_len = max((len(str(c.value or '')) for c in col), default=10)
        ws.column_dimensions[col[0].column_letter].width = max(max_len + 2, 10)

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    filename = f'weekly_stats_{monday}_{sunday}.xlsx'
    return send_file(buf, download_name=filename,
                     as_attachment=True, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@dashboard_bp.route('/weekly-report', methods=['GET', 'POST'])
@login_required
def weekly_report():
    offset = request.args.get('week', 0, type=int)
    monday, sunday = _week_range(offset)

    if request.method == 'POST':
        from app.services.ai import call_ollama
        from app.models.todo import todo_requirements

        # 1. Completed todos this week
        todos_done = Todo.query.filter(
            Todo.done_date >= monday, Todo.done_date <= sunday,
        ).options(joinedload(Todo.user), joinedload(Todo.requirements)).all()

        # 2. Still active todos
        todos_active = Todo.query.filter(
            Todo.created_date <= sunday, Todo.status == 'todo',
        ).options(joinedload(Todo.user), joinedload(Todo.requirements)).all()

        # 3. Requirement changes
        req_changes = Requirement.query.filter(
            Requirement.updated_at >= str(monday),
            Requirement.updated_at <= str(sunday + timedelta(days=1)),
        ).all()

        # 4. Per-requirement investment: count distinct people and todo-days
        req_investment = {}  # req_number -> {people: set, days: int}
        for t in todos_done:
            for r in t.requirements:
                inv = req_investment.setdefault(r.number, {'title': r.title, 'people': set(), 'days': 0})
                inv['people'].add(t.user.name)
                inv['days'] += 1
        for t in todos_active:
            for r in t.requirements:
                inv = req_investment.setdefault(r.number, {'title': r.title, 'people': set(), 'days': 0})
                inv['people'].add(t.user.name)
                # Count active days within this week
                start = max(t.created_date, monday)
                end = min(date.today(), sunday)
                inv['days'] += max((end - start).days, 1)

        # Build context
        lines = [f'本周（{monday} ~ {sunday}）研发团队工作数据：\n']

        if todos_done:
            lines.append('已完成的任务：')
            for t in todos_done:
                reqs_str = ', '.join(r.number for r in t.requirements)
                lines.append(f'- {t.user.name}: {t.title}（{reqs_str}）')

        if todos_active:
            lines.append('\n进行中的任务：')
            for t in todos_active:
                reqs_str = ', '.join(r.number for r in t.requirements)
                lines.append(f'- {t.user.name}: {t.title}（{reqs_str}）')

        if req_investment:
            lines.append('\n需求投入汇总（人×天）：')
            for num, inv in sorted(req_investment.items()):
                people_list = ', '.join(sorted(inv['people']))
                lines.append(f'- [{num}] {inv["title"]}: {len(inv["people"])}人 × {inv["days"]}天（{people_list}）')

        if req_changes:
            lines.append('\n需求状态变更：')
            for r in req_changes:
                lines.append(f'- [{r.number}] {r.title}（{r.status_label}）')

        prompt = (
            '根据以下研发团队本周工作数据，生成一份简洁的中文周报。\n'
            '要求包含：\n'
            '1. 本周完成的工作\n'
            '2. 进行中的工作\n'
            '3. 各需求投入汇总（多少人投入多少天）\n'
            '4. 下周计划\n'
            '5. 风险/阻碍\n'
            '用 Markdown 格式，不要编造数据，投入数据必须如实反映。\n\n'
            + '\n'.join(lines)
        )

        _, raw = call_ollama(prompt)
        report = raw if raw else '周报生成失败，请重试'

        return render_template('dashboard/weekly_report.html',
            report=report, monday=monday, sunday=sunday, offset=offset,
        )

    return render_template('dashboard/weekly_report.html',
        report=None, monday=monday, sunday=sunday, offset=offset,
    )
