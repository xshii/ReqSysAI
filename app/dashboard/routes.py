from datetime import date, datetime, timedelta
from io import BytesIO

from flask import render_template, request, send_file, flash, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload

from app.dashboard import dashboard_bp
from app.extensions import db
from app.constants import TODO_STATUS_TODO, TODO_STATUS_DONE, REQ_INACTIVE_STATUSES
from app.models.user import User, Role, Group
from app.models.project import Project
from app.models.requirement import Requirement
from app.models.todo import Todo, todo_requirements
from app.models.risk import Risk
from app.models.report import WeeklyReport
from app.services.ai import call_ollama
from app.services.prompts import get_prompt
from app.services.statistics import (
    week_range, gather_week_stats, gather_project_data,
    get_reviewer, get_todo_progress, TodoProgress,
    get_delivery_metrics, get_estimate_deviation,
)


@dashboard_bp.route('/requirements')
@login_required
def requirement_progress():

    cur_status = request.args.get('status', '')
    cur_project = request.args.get('project_id', type=int)

    query = Requirement.query.options(
        joinedload(Requirement.project), joinedload(Requirement.assignee),
    )
    if cur_status:
        query = query.filter_by(status=cur_status)
    if cur_project:
        query = query.filter_by(project_id=cur_project)
    requirements = query.order_by(Requirement.updated_at.desc()).all()

    todo_counts = get_todo_progress([r.id for r in requirements])

    return render_template('dashboard/requirements.html',
        requirements=requirements, todo_counts=todo_counts,
        projects=Project.query.filter_by(status='active').all(),
        statuses=Requirement.STATUS_LABELS,
        cur_status=cur_status, cur_project=cur_project,
    )



# ---- Stats / Weekly Report / Excel Export ----

@dashboard_bp.route('/stats')
@login_required
def stats():

    offset = request.args.get('week', 0, type=int)
    cur_group = request.args.get('group', '')
    cur_project_id = request.args.get('project_id', type=int)
    monday, sunday = week_range(offset)

    groups = [g.name for g in Group.query.order_by(Group.name).all()]
    cur_project = db.session.get(Project, cur_project_id) if cur_project_id else None
    data = gather_week_stats(monday, sunday, group=cur_group or None, project_id=cur_project_id)

    return render_template('dashboard/stats.html',
        data=data, monday=monday, sunday=sunday,
        offset=offset, groups=groups, cur_group=cur_group,
        cur_project=cur_project, cur_project_id=cur_project_id or 0,
    )


@dashboard_bp.route('/metrics')
@login_required
def metrics():
    """Delivery cycle time and estimate-vs-actual deviation analytics."""
    import statistics as _stats

    cur_project_id = request.args.get('project_id', type=int)
    cur_project = db.session.get(Project, cur_project_id) if cur_project_id else None
    projects = Project.query.filter_by(status='active').order_by(Project.name).all()

    delivery = get_delivery_metrics(project_id=cur_project_id)
    deviation = get_estimate_deviation(project_id=cur_project_id)

    # Delivery summary
    lead_times = [d['lead_time'] for d in delivery if d['lead_time'] is not None]
    cycle_times = [d['cycle_time'] for d in delivery if d['cycle_time'] is not None]
    avg_lead = round(sum(lead_times) / len(lead_times), 1) if lead_times else 0
    avg_cycle = round(sum(cycle_times) / len(cycle_times), 1) if cycle_times else 0

    # Deviation summary
    dev_pcts = [d['deviation_pct'] for d in deviation]
    avg_deviation = round(sum(dev_pcts) / len(dev_pcts), 1) if dev_pcts else 0
    median_deviation = round(_stats.median(dev_pcts), 1) if dev_pcts else 0

    return render_template('dashboard/metrics.html',
        delivery=delivery, deviation=deviation,
        avg_lead=avg_lead, avg_cycle=avg_cycle,
        avg_deviation=avg_deviation, median_deviation=median_deviation,
        projects=projects, cur_project=cur_project,
        cur_project_id=cur_project_id or 0,
    )


@dashboard_bp.route('/stats/export')
@login_required
def stats_export():
    """Export weekly stats as Excel."""
    import openpyxl
    from openpyxl.styles import Font, Alignment

    offset = request.args.get('week', 0, type=int)
    cur_group = request.args.get('group', '')
    cur_project_id = request.args.get('project_id', type=int)
    monday, sunday = week_range(offset)
    data = gather_week_stats(monday, sunday, group=cur_group or None, project_id=cur_project_id)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '周报统计'

    # Header
    ws.append([f'周报统计 {monday} ~ {sunday}'])
    ws.merge_cells('A1:D1')
    ws['A1'].font = Font(bold=True, size=14)
    ws.append([])

    # Requirement summary
    ws.append(['需求完成率', f'{data.req_done}/{data.req_total}', f'{data.req_rate}%'])
    ws.append([])

    # Per-user table
    ws.append(['姓名', '工号', '新建任务', '完成任务', '完成率'])
    for cell in ws[ws.max_row]:
        cell.font = Font(bold=True)
    for s in data.user_stats:
        ws.append([s.user.name, s.user.employee_id or '', s.created, s.done, f'{s.rate}%'])

    # Project investment sheets
    for pi in data.project_investment:
        ws2 = wb.create_sheet(title=pi.project.name[:30])
        ws2.append([f'项目: {pi.project.name}'])
        ws2['A1'].font = Font(bold=True, size=12)
        ws2.append([f'合计: {pi.people_count}人 · {pi.total_days}人天'])
        ws2.append([])
        ws2.append(['姓名', '工号', '投入(人天)', '占比'])
        for cell in ws2[ws2.max_row]:
            cell.font = Font(bold=True)
        for ud in pi.user_days:
            pct = round(ud.days / pi.total_days * 100) if pi.total_days else 0
            ws2.append([ud.user.name, ud.user.employee_id or '', ud.days, f'{pct}%'])
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
    cur_project_id = request.args.get('project_id', type=int)
    monday, sunday = week_range(offset)
    cur_project = db.session.get(Project, cur_project_id) if cur_project_id else None

    if request.method == 'POST':
        WR_check = WeeklyReport
        frozen = WR_check.query.filter_by(project_id=cur_project_id, week_start=monday, is_frozen=True).first()
        if frozen:
            flash('周报已冻结，无法重新生成', 'warning')
            return redirect(url_for('dashboard.weekly_report', week=offset, project_id=cur_project_id))

        # 1. Completed todos this week
        done_q = Todo.query.filter(
            Todo.done_date >= monday, Todo.done_date <= sunday,
        ).options(joinedload(Todo.user), joinedload(Todo.requirements))
        if cur_project_id:
            done_q = done_q.join(todo_requirements, Todo.id == todo_requirements.c.todo_id)\
                           .join(Requirement, Requirement.id == todo_requirements.c.requirement_id)\
                           .filter(Requirement.project_id == cur_project_id)
        todos_done = done_q.all()

        # 2. Still active todos
        active_q = Todo.query.filter(
            Todo.created_date <= sunday, Todo.status == 'todo',
        ).options(joinedload(Todo.user), joinedload(Todo.requirements))
        if cur_project_id:
            active_q = active_q.join(todo_requirements, Todo.id == todo_requirements.c.todo_id)\
                               .join(Requirement, Requirement.id == todo_requirements.c.requirement_id)\
                               .filter(Requirement.project_id == cur_project_id)
        todos_active = active_q.all()

        # 3. Requirement changes
        req_q = Requirement.query.filter(
            Requirement.updated_at >= str(monday),
            Requirement.updated_at <= str(sunday + timedelta(days=1)),
        )
        if cur_project_id:
            req_q = req_q.filter_by(project_id=cur_project_id)
        req_changes = req_q.all()

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

        # 5. All requirements overview (for project scope)
        req_overview_q = Requirement.query.filter(Requirement.parent_id.is_(None))
        if cur_project_id:
            req_overview_q = req_overview_q.filter_by(project_id=cur_project_id)
        all_reqs = req_overview_q.order_by(Requirement.number).all()

        # 6. Per-person stats this week
        from collections import Counter
        person_done = Counter()
        person_active = Counter()
        for t in todos_done:
            person_done[t.user.name] += 1
        for t in todos_active:
            person_active[t.user.name] += 1

        # 7. Milestones
        milestones = []
        if cur_project:
            milestones = cur_project.milestones

        # Build context
        project_name = cur_project.name if cur_project else '研发团队'
        lines = [f'本周（{monday} ~ {sunday}）{project_name}工作数据：\n']

        # Milestones
        if milestones:
            lines.append('里程碑：')
            for ms in milestones:
                due_str = f'，截止 {ms.due_date.strftime("%m-%d")}' if ms.due_date else ''
                status = '已完成' if ms.status == 'completed' else '进行中'
                lines.append(f'- {ms.name}（{status}{due_str}）')

        # Requirement overview
        if all_reqs:
            lines.append('需求总览：')
            for r in all_reqs:
                due_str = f'，预期 {r.due_date.strftime("%m-%d")}' if r.due_date else ''
                days_str = f'，预估 {r.estimate_days}人天' if r.estimate_days else ''
                if r.due_date and r.due_date < date.today() and r.status not in REQ_INACTIVE_STATUSES:
                    overdue = f'⚠️已延期{(date.today() - r.due_date).days}天'
                else:
                    overdue = ''
                children_str = ''
                if r.children:
                    done_children = sum(1 for c in r.children if c.status in REQ_INACTIVE_STATUSES)
                    children_str = f'，子需求 {done_children}/{len(r.children)} 完成'
                assignee = r.assignee_display
                lines.append(f'- [{r.number}] {r.title}（{r.status_label}，{assignee}{days_str}{due_str}{children_str}）{overdue}')

        if todos_done:
            lines.append('\n本周已完成的任务：')
            for t in todos_done:
                reqs_str = ', '.join(r.number for r in t.requirements)
                lines.append(f'- {t.user.name}: {t.title}（{reqs_str}）')

        if todos_active:
            lines.append('\n进行中的任务：')
            for t in todos_active:
                reqs_str = ', '.join(r.number for r in t.requirements)
                lines.append(f'- {t.user.name}: {t.title}（{reqs_str}）')

        if open_risks:
            lines.append('\n风险&问题（未解决）：')
            for r in open_risks:
                r_days = (r.due_date - date.today()).days if r.due_date else 999
                r_status = f'已延期{-r_days}天' if r_days < 0 else f'剩{r_days}天'
                lines.append(f'- {r.title}（{r.severity_label}，{r_status}，跟踪人：{r.tracker.name if r.tracker else "无"}）')

        if req_changes:
            lines.append('\n本周需求状态变更：')
            for r in req_changes:
                lines.append(f'- [{r.number}] {r.title}（{r.status_label}）')

        if req_investment:
            lines.append('\n需求投入汇总（人×天）：')
            for num, inv in sorted(req_investment.items()):
                people_list = ', '.join(sorted(inv['people']))
                lines.append(f'- [{num}] {inv["title"]}: {len(inv["people"])}人 × {inv["days"]}天（{people_list}）')

        # Person stats
        all_persons = sorted(set(list(person_done.keys()) + list(person_active.keys())))
        if all_persons:
            lines.append('\n人员投入：')
            for name in all_persons:
                lines.append(f'- {name}: 完成 {person_done.get(name, 0)} 个任务，进行中 {person_active.get(name, 0)} 个')

        if req_changes:
            lines.append('\n需求状态变更：')
            for r in req_changes:
                lines.append(f'- [{r.number}] {r.title}（{r.status_label}）')

        # AI prompt: only generate analysis (summary, risks, plan)
        tpl = get_prompt('weekly_report')
        prompt = tpl.format(project_name=project_name) + '\n\n' + '\n'.join(lines)

        import json as json_lib
        result, _ = call_ollama(prompt)
        ai_analysis = {
            'summary': '数据不足，无法生成摘要',
            'risks': [],
            'plan': [],
        }
        if isinstance(result, dict):
            ai_analysis['summary'] = result.get('summary', ai_analysis['summary'])
            ai_analysis['risks'] = result.get('risks', [])
            ai_analysis['plan'] = result.get('plan', [])

        # Open risks from DB
        risk_q = Risk.query.filter_by(status='open')
        if cur_project_id:
            risk_q = risk_q.filter_by(project_id=cur_project_id)
        open_risks = risk_q.order_by(Risk.severity, Risk.due_date).all()

        # Reviewer: PL of current user's group; if user is PL, then XM
        reviewer = ''
        if current_user.has_role('PL'):
            xm_users = User.query.filter(User.is_active == True, User.group == current_user.group)\
                .join(User.roles).filter(Role.name.in_(['XM', 'PM'])).first()
            reviewer = xm_users.name if xm_users else '待定'
        else:
            pl_user = User.query.filter(User.is_active == True, User.group == current_user.group)\
                .join(User.roles).filter(Role.name == 'PL').first()
            reviewer = pl_user.name if pl_user else '待定'

        # People map: person × requirement matrix
        from collections import defaultdict as dd2
        people_map = {}
        people_map_reqs = sorted(req_investment.keys())
        for rnum, inv in req_investment.items():
            for pname in inv['people']:
                if pname not in people_map:
                    people_map[pname] = {'_total': 0}
                people_map[pname][rnum] = inv['days'] // max(len(inv['people']), 1)
                people_map[pname]['_total'] += people_map[pname][rnum]

        # Package all data for template and Excel
        report_data = {
            'project_name': project_name,
            'today': date.today(),
            'monday': monday,
            'sunday': sunday,
            'reviewer': reviewer,
            'milestones': milestones,
            'all_reqs': all_reqs,
            'req_investment': req_investment,
            'person_done': dict(person_done),
            'person_active': dict(person_active),
            'all_persons': all_persons,
            'todos_done': todos_done,
            'todos_active': todos_active,
            'open_risks': open_risks,
            'people_map': people_map,
            'people_map_reqs': people_map_reqs,
            'ai': ai_analysis,
        }

        # Save to DB
        import json as json_lib
        saved = WeeklyReport.query.filter_by(project_id=cur_project_id, week_start=monday).first()
        if saved:
            saved.summary = ai_analysis['summary']
            saved.risks_json = json_lib.dumps(ai_analysis['risks'], ensure_ascii=False)
            saved.plan_json = json_lib.dumps(ai_analysis['plan'], ensure_ascii=False)
            saved.updated_at = datetime.utcnow()
        else:
            saved = WeeklyReport(
                project_id=cur_project_id,
                week_start=monday, week_end=sunday,
                summary=ai_analysis['summary'],
                risks_json=json_lib.dumps(ai_analysis['risks'], ensure_ascii=False),
                plan_json=json_lib.dumps(ai_analysis['plan'], ensure_ascii=False),
                created_by=current_user.id,
            )
            db.session.add(saved)
        db.session.commit()

        return render_template('dashboard/weekly_report.html',
            report_data=report_data, saved_report=saved,
            monday=monday, sunday=sunday, offset=offset,
            cur_project=cur_project, cur_project_id=cur_project_id or 0,
        )

    # GET: check if saved report exists, and load full DB data
    import json as json_lib
    saved = WeeklyReport.query.filter_by(project_id=cur_project_id, week_start=monday).first() if cur_project_id else None

    if saved:
        # Load saved AI analysis + fresh DB data
        from collections import Counter

        project_name = cur_project.name if cur_project else '研发团队'

        # Milestones
        milestones = cur_project.milestones if cur_project else []

        # Requirements
        req_overview_q = Requirement.query.filter(Requirement.parent_id.is_(None))
        if cur_project_id:
            req_overview_q = req_overview_q.filter_by(project_id=cur_project_id)
        all_reqs = req_overview_q.order_by(Requirement.number).all()

        # Todos
        done_q = Todo.query.filter(Todo.done_date >= monday, Todo.done_date <= sunday)\
            .options(joinedload(Todo.user), joinedload(Todo.requirements))
        active_q = Todo.query.filter(Todo.created_date <= sunday, Todo.status == 'todo')\
            .options(joinedload(Todo.user), joinedload(Todo.requirements))
        if cur_project_id:
            done_q = done_q.join(todo_requirements, Todo.id == todo_requirements.c.todo_id)\
                           .join(Requirement, Requirement.id == todo_requirements.c.requirement_id)\
                           .filter(Requirement.project_id == cur_project_id)
            active_q = active_q.join(todo_requirements, Todo.id == todo_requirements.c.todo_id)\
                               .join(Requirement, Requirement.id == todo_requirements.c.requirement_id)\
                               .filter(Requirement.project_id == cur_project_id)
        todos_done = done_q.all()
        todos_active = active_q.all()

        person_done = Counter(t.user.name for t in todos_done)
        person_active = Counter(t.user.name for t in todos_active)
        all_persons = sorted(set(list(person_done.keys()) + list(person_active.keys())))

        req_investment = {}
        for t in todos_done + todos_active:
            for r in t.requirements:
                inv = req_investment.setdefault(r.number, {'title': r.title, 'people': set(), 'days': 0})
                inv['people'].add(t.user.name)
                inv['days'] += 1

        risk_q = Risk.query.filter_by(status='open')
        if cur_project_id:
            risk_q = risk_q.filter_by(project_id=cur_project_id)
        open_risks = risk_q.order_by(Risk.severity, Risk.due_date).all()

        # Reviewer
        reviewer = ''
        if current_user.has_role('PL'):
            xm = User.query.filter(User.is_active == True, User.group == current_user.group)\
                .join(User.roles).filter(Role.name.in_(['XM', 'PM'])).first()
            reviewer = xm.name if xm else '待定'
        else:
            pl = User.query.filter(User.is_active == True, User.group == current_user.group)\
                .join(User.roles).filter(Role.name == 'PL').first()
            reviewer = pl.name if pl else '待定'

        # People map
        people_map = {}
        people_map_reqs = sorted(req_investment.keys())
        for rnum, inv in req_investment.items():
            for pname in inv['people']:
                if pname not in people_map:
                    people_map[pname] = {'_total': 0}
                people_map[pname][rnum] = inv['days'] // max(len(inv['people']), 1)
                people_map[pname]['_total'] += people_map[pname][rnum]

        # Merge saved AI analysis
        ai_analysis = {
            'summary': saved.summary or '',
            'risks': json_lib.loads(saved.risks_json) if saved.risks_json else [],
            'plan': json_lib.loads(saved.plan_json) if saved.plan_json else [],
        }

        report_data = {
            'project_name': project_name,
            'today': date.today(),
            'monday': monday,
            'sunday': sunday,
            'reviewer': reviewer,
            'milestones': milestones,
            'all_reqs': all_reqs,
            'req_investment': req_investment,
            'person_done': dict(person_done),
            'person_active': dict(person_active),
            'all_persons': all_persons,
            'todos_done': todos_done,
            'todos_active': todos_active,
            'open_risks': open_risks,
            'people_map': people_map,
            'people_map_reqs': people_map_reqs,
            'ai': ai_analysis,
        }

        return render_template('dashboard/weekly_report.html',
            report_data=report_data, saved_report=saved,
            monday=monday, sunday=sunday, offset=offset,
            cur_project=cur_project, cur_project_id=cur_project_id or 0,
        )

    return render_template('dashboard/weekly_report.html',
        report_data=None, saved_report=None,
        monday=monday, sunday=sunday, offset=offset,
        cur_project=cur_project, cur_project_id=cur_project_id or 0,
    )


@dashboard_bp.route('/weekly-report/save', methods=['POST'])
@login_required
def weekly_report_save():
    """Save manually edited report content."""
    import json as json_lib

    cur_project_id = request.form.get('project_id', type=int)
    week_start = request.form.get('week_start')
    if not cur_project_id or not week_start:
        flash('参数缺失', 'danger')
        return redirect(request.referrer or url_for('dashboard.weekly_report'))

    saved = WeeklyReport.query.filter_by(project_id=cur_project_id, week_start=week_start).first()
    if not saved:
        flash('请先生成周报', 'warning')
        return redirect(request.referrer or url_for('dashboard.weekly_report'))

    if saved.is_frozen:
        flash('周报已冻结，无法编辑', 'warning')
        offset = request.form.get('offset', 0, type=int)
        return redirect(url_for('dashboard.weekly_report', week=offset, project_id=cur_project_id))

    saved.summary = request.form.get('summary', '').strip()
    risks = [r.strip() for r in request.form.get('risks', '').strip().splitlines() if r.strip()]
    plan = [p.strip() for p in request.form.get('plan', '').strip().splitlines() if p.strip()]
    saved.risks_json = json_lib.dumps(risks, ensure_ascii=False)
    saved.plan_json = json_lib.dumps(plan, ensure_ascii=False)
    saved.updated_at = datetime.utcnow()
    db.session.commit()
    flash('周报已保存', 'success')

    offset = request.form.get('offset', 0, type=int)
    return redirect(url_for('dashboard.weekly_report', week=offset, project_id=cur_project_id))


@dashboard_bp.route('/weekly-report/freeze', methods=['POST'])
@login_required
def weekly_report_freeze():
    """Freeze/unfreeze weekly report. Only project PM (owner) can freeze."""

    cur_project_id = request.form.get('project_id', type=int)
    week_start = request.form.get('week_start')
    action = request.form.get('action', 'freeze')

    saved = WeeklyReport.query.filter_by(project_id=cur_project_id, week_start=week_start).first()
    if not saved:
        flash('周报不存在', 'danger')
        return redirect(request.referrer or url_for('dashboard.weekly_report'))

    project = db.session.get(Project, cur_project_id)
    is_pm = project and project.owner_id == current_user.id
    if not is_pm and not current_user.is_admin:
        flash('只有项目 PM 或管理员可以冻结/解冻周报', 'danger')
        return redirect(request.referrer or url_for('dashboard.weekly_report'))

    if action == 'freeze':
        saved.is_frozen = True
        saved.frozen_by = current_user.id
        saved.frozen_at = datetime.utcnow()
        flash('周报已冻结', 'success')
    else:
        saved.is_frozen = False
        saved.frozen_by = None
        saved.frozen_at = None
        flash('周报已解冻', 'success')

    db.session.commit()
    offset = request.form.get('offset', 0, type=int)
    return redirect(url_for('dashboard.weekly_report', week=offset, project_id=cur_project_id))


@dashboard_bp.route('/weekly-report/export', methods=['POST'])
@login_required
def weekly_report_export():
    """Export weekly report as formatted Excel."""
    import openpyxl
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

    offset = request.args.get('week', 0, type=int)
    cur_project_id = request.args.get('project_id', type=int)
    monday, sunday = week_range(offset)
    cur_project = db.session.get(Project, cur_project_id) if cur_project_id else None
    project_name = cur_project.name if cur_project else '研发团队'

    # AI analysis from form hidden fields
    ai_summary = request.form.get('ai_summary', '')
    ai_risks = [r for r in request.form.get('ai_risks', '').split('||') if r]
    ai_plan = [p for p in request.form.get('ai_plan', '').split('||') if p]

    # Gather data
    req_q = Requirement.query.filter(Requirement.parent_id.is_(None))
    if cur_project_id:
        req_q = req_q.filter_by(project_id=cur_project_id)
    all_reqs = req_q.order_by(Requirement.number).all()

    milestones = cur_project.milestones if cur_project else []

    # Todo stats
    from collections import Counter
    done_q = Todo.query.filter(Todo.done_date >= monday, Todo.done_date <= sunday)
    active_q = Todo.query.filter(Todo.created_date <= sunday, Todo.status == 'todo')
    if cur_project_id:
        done_q = done_q.join(todo_requirements, Todo.id == todo_requirements.c.todo_id)\
                       .join(Requirement, Requirement.id == todo_requirements.c.requirement_id)\
                       .filter(Requirement.project_id == cur_project_id)
        active_q = active_q.join(todo_requirements, Todo.id == todo_requirements.c.todo_id)\
                           .join(Requirement, Requirement.id == todo_requirements.c.requirement_id)\
                           .filter(Requirement.project_id == cur_project_id)
    todos_done = done_q.options(joinedload(Todo.user), joinedload(Todo.requirements)).all()
    todos_active = active_q.options(joinedload(Todo.user), joinedload(Todo.requirements)).all()

    person_done = Counter(t.user.name for t in todos_done)
    person_active = Counter(t.user.name for t in todos_active)
    all_persons = sorted(set(list(person_done.keys()) + list(person_active.keys())))

    req_investment = {}
    for t in todos_done + todos_active:
        for r in t.requirements:
            inv = req_investment.setdefault(r.number, {'title': r.title, 'people': set(), 'days': 0})
            inv['people'].add(t.user.name)
            inv['days'] += 1

    # ---- Build Excel ----
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '项目周报'

    # Styles
    header_font = Font(bold=True, size=14, color='FFFFFF')
    header_fill = PatternFill(start_color='4A6CF7', end_color='4A6CF7', fill_type='solid')
    section_font = Font(bold=True, size=11, color='2D3748')
    section_fill = PatternFill(start_color='EDF2F7', end_color='EDF2F7', fill_type='solid')
    th_font = Font(bold=True, size=9)
    th_fill = PatternFill(start_color='F7FAFC', end_color='F7FAFC', fill_type='solid')
    td_font = Font(size=9)
    thin_border = Border(
        left=Side(style='thin', color='CBD5E0'),
        right=Side(style='thin', color='CBD5E0'),
        top=Side(style='thin', color='CBD5E0'),
        bottom=Side(style='thin', color='CBD5E0'),
    )
    risk_font = Font(size=9, color='E53E3E')

    row = 1

    # Title
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=7)
    cell = ws.cell(row=row, column=1, value=f'{project_name} 项目周报')
    cell.font = header_font
    cell.fill = header_fill
    cell.alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[row].height = 30
    row += 1

    # Date range
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=7)
    cell = ws.cell(row=row, column=1, value=f'{monday.strftime("%Y-%m-%d")} ~ {sunday.strftime("%Y-%m-%d")}')
    cell.font = Font(size=10, color='718096')
    cell.alignment = Alignment(horizontal='center')
    row += 2

    def write_section(title):
        nonlocal row
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=7)
        cell = ws.cell(row=row, column=1, value=title)
        cell.font = section_font
        cell.fill = section_fill
        row += 1

    def write_table_header(headers):
        nonlocal row
        for i, h in enumerate(headers, 1):
            cell = ws.cell(row=row, column=i, value=h)
            cell.font = th_font
            cell.fill = th_fill
            cell.border = thin_border
        row += 1

    def write_table_row(values):
        nonlocal row
        for i, v in enumerate(values, 1):
            cell = ws.cell(row=row, column=i, value=v)
            cell.font = td_font
            cell.border = thin_border
        row += 1

    # Summary
    write_section('整体进展')
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=7)
    ws.cell(row=row, column=1, value=ai_summary).font = Font(size=10)
    row += 2

    # Milestones
    if milestones:
        write_section('里程碑')
        write_table_header(['里程碑', '状态', '截止日期'])
        for ms in milestones:
            write_table_row([
                ms.name,
                '已完成' if ms.status == 'completed' else '进行中',
                ms.due_date.strftime('%Y-%m-%d') if ms.due_date else '-',
            ])
        row += 1

    # Requirements
    if all_reqs:
        write_section('需求进展')
        write_table_header(['编号', '标题', '状态', '负责人', '预估(人天)', '预期完成', '本周投入'])
        for r in all_reqs:
            inv = req_investment.get(r.number)
            invest_str = f'{len(inv["people"])}人·{inv["days"]}天' if inv else '-'
            children_str = ''
            if r.children:
                dc = sum(1 for c in r.children if c.status in REQ_INACTIVE_STATUSES)
                children_str = f' ({dc}/{len(r.children)})'
            overdue = ' [超期]' if (r.due_date and r.due_date < date.today() and r.status not in REQ_INACTIVE_STATUSES) else ''
            write_table_row([
                r.number,
                r.title + children_str,
                r.status_label + overdue,
                r.assignee_display,
                r.estimate_days or '-',
                r.due_date.strftime('%m-%d') if r.due_date else '-',
                invest_str,
            ])
        row += 1

    # Person stats
    if all_persons:
        write_section('人员投入')
        write_table_header(['姓名', '完成任务', '进行中'])
        for name in all_persons:
            write_table_row([name, person_done.get(name, 0), person_active.get(name, 0)])
        row += 1

    # Risks
    write_section('风险与问题')
    if ai_risks:
        for r in ai_risks:
            cell = ws.cell(row=row, column=1, value=f'  · {r}')
            cell.font = risk_font
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=7)
            row += 1
    else:
        ws.cell(row=row, column=1, value='  暂无').font = Font(size=9, color='A0AEC0')
        row += 1
    row += 1

    # Plan
    write_section('下周计划')
    if ai_plan:
        for p in ai_plan:
            ws.cell(row=row, column=1, value=f'  · {p}').font = td_font
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=7)
            row += 1
    else:
        ws.cell(row=row, column=1, value='  暂无').font = Font(size=9, color='A0AEC0')

    # Column widths
    col_widths = [10, 30, 10, 10, 12, 10, 12]
    for i, w in enumerate(col_widths, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    filename = f'{project_name}_周报_{monday}_{sunday}.xlsx'
    return send_file(buf, download_name=filename,
                     as_attachment=True, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


# ---- Personal weekly report ----

@dashboard_bp.route('/my-weekly', methods=['GET', 'POST'])
@login_required
def my_weekly():
    offset = request.args.get('week', 0, type=int)
    monday, sunday = week_range(offset)

    my_done = Todo.query.filter_by(user_id=current_user.id)\
        .filter(Todo.done_date >= monday, Todo.done_date <= sunday)\
        .options(joinedload(Todo.requirements), joinedload(Todo.items)).all()
    my_active = Todo.query.filter_by(user_id=current_user.id)\
        .filter(Todo.status == 'todo', Todo.created_date <= sunday)\
        .options(joinedload(Todo.requirements), joinedload(Todo.items)).all()

    my_reqs = set()
    for t in my_done + my_active:
        for r in t.requirements:
            my_reqs.add(r)
    my_reqs = sorted(my_reqs, key=lambda r: r.number)

    req_days = {}
    for t in my_done:
        for r in t.requirements:
            req_days[r.number] = req_days.get(r.number, 0) + 1

    # Categorize active todos (needed for both GET and POST)
    overdue_todos = [t for t in my_active if t.created_date and t.created_date < monday]
    blocked_todos = [t for t in my_active if t.need_help]

    report = None
    ai_report = None
    if request.method == 'POST':
        import markdown as md_lib

        lines = [f'本周（{monday} ~ {sunday}）{current_user.name} 的工作数据：\n']
        normal_active = [t for t in my_active if t not in overdue_todos and t not in blocked_todos]

        if my_done:
            lines.append('本周已完成：')
            for t in my_done:
                reqs = ', '.join(r.number for r in t.requirements)
                time_str = f'，用时{t.actual_minutes}分钟' if t.actual_minutes else ''
                lines.append(f'- ✓ {t.title}（{reqs}{time_str}）')

        if normal_active:
            lines.append('\n进行中：')
            for t in normal_active:
                reqs = ', '.join(r.number for r in t.requirements)
                lines.append(f'- ○ {t.title}（{reqs}）')

        if overdue_todos:
            lines.append('\n延期未完成（上周遗留）：')
            for t in overdue_todos:
                reqs = ', '.join(r.number for r in t.requirements)
                days = (date.today() - t.created_date).days
                lines.append(f'- ⚠️ {t.title}（{reqs}，已延期{days}天）')

        if blocked_todos:
            lines.append('\n阻塞中：')
            for t in blocked_todos:
                reqs = ', '.join(r.number for r in t.requirements)
                reason = f'，原因：{t.blocked_reason}' if t.blocked_reason else ''
                lines.append(f'- 🔴 {t.title}（{reqs}{reason}）')

        if my_reqs:
            lines.append('\n参与的需求及状态：')
            for r in my_reqs:
                due_info = ''
                if r.due_date:
                    days_left = (r.due_date - date.today()).days
                    due_info = f'，已延期{-days_left}天' if days_left < 0 else f'，剩{days_left}天'
                lines.append(f'- [{r.number}] {r.title}（{r.status_label}{due_info}）')

        prompt = get_prompt('personal_weekly') + '\n\n' + '\n'.join(lines)
        _, raw = call_ollama(prompt)
        ai_report = raw or '生成失败，请重试'
        ai_report = md_lib.markdown(ai_report, extensions=['tables'])
        report = True

    # Calculate totals
    total_focus = sum(t.actual_minutes or 0 for t in my_done)
    reviewer_name = get_reviewer(current_user)

    return render_template('dashboard/my_weekly.html',
        my_done=my_done, my_active=my_active, my_reqs=my_reqs,
        req_days=req_days, report=report, ai_report=ai_report,
        overdue_todos=overdue_todos, blocked_todos=blocked_todos,
        total_focus_min=total_focus, reviewer=reviewer_name,
        today=date.today(),
        monday=monday, sunday=sunday, offset=offset,
    )


# ---- Resource allocation map ----

@dashboard_bp.route('/resource-map')
@login_required
def resource_map():
    from collections import defaultdict

    period = request.args.get('period', 'week')
    mode = request.args.get('mode', 'by_person')  # by_person or by_project
    week_offset = request.args.get('week', 0, type=int)

    today = date.today()
    if period == '3month':
        start = today - timedelta(days=90)
        end = today
    elif period == 'month':
        start = today.replace(day=1)
        end = today
    else:
        start, end = week_range(week_offset)
    label = f'{start.strftime("%Y-%m-%d")} ~ {end.strftime("%Y-%m-%d")}'

    users = User.query.filter_by(is_active=True).order_by(User.group, User.name).all()
    user_ids = [u.id for u in users]

    todos = Todo.query.filter(
        Todo.user_id.in_(user_ids),
        Todo.created_date >= start, Todo.created_date <= end,
    ).options(joinedload(Todo.requirements)).all()

    user_date_projects = defaultdict(lambda: defaultdict(set))
    for t in todos:
        for r in t.requirements:
            if r.project_id:
                user_date_projects[t.user_id][t.created_date].add(r.project_id)

    user_project_days = defaultdict(float)
    for uid, date_projects in user_date_projects.items():
        for dt, pids in date_projects.items():
            share = 1.0 / len(pids) if pids else 0
            for pid in pids:
                user_project_days[(uid, pid)] += share

    project_ids = sorted(set(pid for (_, pid) in user_project_days))
    projects = {p.id: p for p in Project.query.filter(Project.id.in_(project_ids)).all()} if project_ids else {}

    # Mode 1 (by_person): rows = users, columns = projects
    person_rows = []
    for u in users:
        proj_days = {}
        total = 0.0
        for pid in project_ids:
            d = user_project_days.get((u.id, pid), 0)
            if d > 0:
                proj_days[pid] = round(d, 1)
                total += d
        if total > 0:
            person_rows.append({'user': u, 'proj_days': proj_days, 'total': round(total, 1)})

    # Mode 2 (by_project): rows = projects, columns = users
    active_user_ids = [r['user'].id for r in person_rows]
    active_users = [r['user'] for r in person_rows]
    project_rows = []
    for pid in project_ids:
        p = projects.get(pid)
        if not p:
            continue
        user_days = {}
        total = 0.0
        for u in active_users:
            d = user_project_days.get((u.id, pid), 0)
            if d > 0:
                user_days[u.id] = round(d, 1)
                total += d
        if total > 0:
            project_rows.append({'project': p, 'user_days': user_days, 'total': round(total, 1)})

    return render_template('dashboard/resource_map.html',
        person_rows=person_rows, project_rows=project_rows,
        active_users=active_users,
        projects=projects, project_ids=project_ids,
        period=period, mode=mode, label=label, offset=week_offset,
    )
