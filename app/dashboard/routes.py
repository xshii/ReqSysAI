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
    user_query = User.query.filter_by(is_active=True)
    if group:
        user_query = user_query.filter_by(group=group)
    users = user_query.order_by(User.group, User.name).all()
    user_ids = [u.id for u in users]

    # Per-user todo stats for the week (two aggregate queries instead of 2N)
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

    return {
        'user_stats': user_stats,
        'req_total': req_total,
        'req_done': req_done,
        'req_rate': round(req_done / req_total * 100) if req_total else 0,
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

    # Auto column width
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

        # Gather data for the week
        todos_done = Todo.query.filter(
            Todo.done_date >= monday, Todo.done_date <= sunday,
        ).options(joinedload(Todo.user)).all()

        todos_new = Todo.query.filter(
            Todo.created_date >= monday, Todo.created_date <= sunday,
            Todo.status == 'todo',
        ).options(joinedload(Todo.user)).all()

        req_changes = Requirement.query.filter(
            Requirement.updated_at >= str(monday),
            Requirement.updated_at <= str(sunday + timedelta(days=1)),
        ).all()

        # Build context
        lines = [f'本周（{monday} ~ {sunday}）研发团队工作数据：\n']

        if todos_done:
            lines.append('已完成的任务：')
            for t in todos_done:
                lines.append(f'- {t.user.name}: {t.title}')

        if todos_new:
            lines.append('\n未完成的任务：')
            for t in todos_new:
                lines.append(f'- {t.user.name}: {t.title}')

        if req_changes:
            lines.append('\n需求变更：')
            for r in req_changes:
                lines.append(f'- [{r.number}] {r.title}（{r.status_label}）')

        prompt = (
            '根据以下研发团队本周工作数据，生成一份简洁的中文周报。'
            '包含：本周完成、进行中、下周计划、风险/阻碍。'
            '用 Markdown 格式，不要编造数据。\n\n'
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
