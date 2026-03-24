from datetime import date, datetime, timedelta
from io import BytesIO

from flask import render_template, request, send_file, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload

from app.dashboard import dashboard_bp
from app.extensions import db
from app.constants import TODO_STATUS_TODO, TODO_STATUS_DONE, REQ_INACTIVE_STATUSES
from app.models.user import User, Role, Group
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.requirement import Requirement
from app.models.todo import Todo, todo_requirements
from app.models.risk import Risk
from app.models.report import WeeklyReport, PersonalWeekly
from app.services.ai import call_ollama
from app.services.prompts import get_prompt
from app.services.statistics import (
    week_range, gather_week_stats, gather_project_data,
    get_reviewer, get_todo_progress, TodoProgress,
    get_delivery_metrics, get_estimate_deviation,
)


def _build_sub_projects(cur_project, monday):
    """Build sub-project progress list for parent project weekly report."""
    if not cur_project or not cur_project.children:
        return []
    sub_projects = []
    for child in cur_project.children:
        child_saved = WeeklyReport.query.filter_by(
            project_id=child.id, week_start=monday).first()
        from app.models.project_member import ProjectMember as PM_
        fo = PM_.query.filter_by(project_id=child.id, project_role='FO').first()
        summary = child_saved.summary if child_saved and child_saved.summary else None
        if summary is None:
            # AI generate one-line summary for child project
            child_reqs = Requirement.query.filter_by(project_id=child.id, parent_id=None).all()
            c_total = len(child_reqs)
            c_done = sum(1 for r in child_reqs if r.status in ('done', 'closed'))
            c_dev = sum(1 for r in child_reqs if r.status == 'in_dev')
            c_overdue = sum(1 for r in child_reqs if r.due_date and r.due_date < date.today()
                           and r.status not in ('done', 'closed'))
            # Completed todos this week
            child_req_ids = [r.id for r in child_reqs]
            week_done = 0
            if child_req_ids:
                from app.models.todo import todo_requirements as tr_
                week_done = Todo.query.filter(
                    Todo.done_date >= monday, Todo.done_date <= date.today()
                ).join(tr_, Todo.id == tr_.c.todo_id).filter(
                    tr_.c.requirement_id.in_(child_req_ids)).count()
            context = (f'{child.name}：需求 {c_done}/{c_total} 完成，{c_dev}个开发中，'
                       f'本周完成 {week_done} 个todo'
                       + (f'，{c_overdue}个延期' if c_overdue else ''))
            try:
                _, raw = call_ollama(f'用一句话（不超过30字）总结以下项目进展，直接输出文字：\n{context}')
                summary = (raw or '').strip()[:50] if raw else context
            except Exception:
                summary = context
        sub_projects.append({
            'project': child,
            'owner': fo.user if fo and fo.user else (child.owner if child.owner else None),
            'summary': summary,
        })
    return sub_projects


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

        # Project goal
        if cur_project and cur_project.description:
            lines.append(f'项目目标：{cur_project.description}\n')

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

        # Open risks from DB (needed for both prompt context and template)
        risk_q = Risk.query.filter_by(status='open').filter(Risk.deleted_at.is_(None))
        if cur_project_id:
            risk_q = risk_q.filter_by(project_id=cur_project_id)
        open_risks = risk_q.order_by(Risk.severity, Risk.due_date).all()

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

        # Sub-project context for AI
        if cur_project and cur_project.children:
            lines.append('\n专题（子项目）进展：')
            for child in cur_project.children:
                child_reqs = Requirement.query.filter_by(project_id=child.id, parent_id=None).all()
                c_total = len(child_reqs)
                c_done = sum(1 for r in child_reqs if r.status in ('done', 'closed'))
                from app.models.project_member import ProjectMember as PM_
                fo = PM_.query.filter_by(project_id=child.id, project_role='FO').first()
                fo_name = fo.display_name if fo else (child.owner.name if child.owner else '未分配')
                lines.append(f'- {child.name}（负责人：{fo_name}，需求 {c_done}/{c_total} 完成，进度 {child.progress}%）')

        # AI prompt: only generate analysis (summary, risks, plan)
        tpl = get_prompt('weekly_report')
        prompt = tpl.format(project_name=project_name) + '\n\n' + '\n'.join(lines)

        import json as json_lib
        result, _ = call_ollama(prompt)
        ai_analysis = {
            'summary': '数据不足，无法生成摘要',
            'highlights': [],
            'risks': [],
            'plan': [],
        }
        if isinstance(result, dict):
            ai_analysis['summary'] = result.get('summary', ai_analysis['summary'])
            ai_analysis['highlights'] = result.get('highlights', [])
            ai_analysis['risks'] = result.get('risks', [])
            ai_analysis['plan'] = result.get('plan', [])

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
        sub_projects = _build_sub_projects(cur_project, monday)

        report_data = {
            'project_name': project_name,
            'project_goal': cur_project.description if cur_project else '',
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
            'people_roles': {m.display_name: m.role_label for m in ProjectMember.query.filter_by(project_id=cur_project_id).all()},
            'ai': ai_analysis,
            'sub_projects': sub_projects,
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

        risk_q = Risk.query.filter_by(status='open').filter(Risk.deleted_at.is_(None))
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

        # Sub-projects
        sub_projects = []
        if cur_project and cur_project.children:
            for child in cur_project.children:
                child_saved = WeeklyReport.query.filter_by(
                    project_id=child.id, week_start=monday).first()
                from app.models.project_member import ProjectMember as PM_
                fo = PM_.query.filter_by(project_id=child.id, project_role='FO').first()
                sub_projects.append({
                    'project': child,
                    'owner': fo.user if fo and fo.user else (child.owner if child.owner else None),
                    'summary': child_saved.summary if child_saved and child_saved.summary else None,
                })

        report_data = {
            'project_name': project_name,
            'project_goal': cur_project.description if cur_project else '',
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
            'people_roles': {m.display_name: m.role_label for m in ProjectMember.query.filter_by(project_id=cur_project_id).all()},
            'ai': ai_analysis,
            'sub_projects': sub_projects,
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
    week_start_str = request.form.get('week_start', '')
    if not cur_project_id or not week_start_str:
        flash('参数缺失', 'danger')
        return redirect(request.referrer or url_for('dashboard.weekly_report'))
    week_start = date.fromisoformat(week_start_str)

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
    week_start_str = request.form.get('week_start', '')
    action = request.form.get('action', 'freeze')
    week_start = date.fromisoformat(week_start_str) if week_start_str else None

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


# ---- My Day (我的一天) ----

@dashboard_bp.route('/my-day')
@login_required
def my_day():
    """Personal daily schedule — 5-day Outlook-style timeline based on pomodoro sessions."""
    from app.models.todo import PomodoroSession

    today = date.today()
    # 5 days: today + 4 previous days (today first)
    days = [today - timedelta(days=i) for i in range(5)]

    # Load all pomodoro sessions for the 5-day range
    range_start = datetime(days[-1].year, days[-1].month, days[-1].day)
    range_end = datetime(today.year, today.month, today.day) + timedelta(days=1)
    all_sessions = PomodoroSession.query.join(Todo).filter(
        Todo.user_id == current_user.id,
        PomodoroSession.created_at >= range_start,
        PomodoroSession.created_at < range_end,
    ).options(joinedload(PomodoroSession.todo)).order_by(PomodoroSession.started_at.asc().nullslast()).all()

    # Group sessions by date
    day_data = {}
    for d in days:
        day_data[d] = {
            'sessions': [],
            'timeline': [],
            'total_min': 0,
            'count': 0,
            'done': [],
        }

    for s in all_sessions:
        s_date = (s.started_at or s.created_at).date() if (s.started_at or s.created_at) else None
        if s_date and s_date in day_data:
            dd = day_data[s_date]
            dd['sessions'].append(s)
            dd['total_min'] += s.minutes
            dd['count'] += 1
            start = s.started_at or s.created_at
            dd['timeline'].append({
                'start_hour': start.hour,
                'start_min': start.minute,
                'duration': s.minutes,
                'title': s.todo.title if s.todo else '',
                'completed': s.completed,
            })

    # Load done todos per day
    done_todos = Todo.query.filter(
        Todo.user_id == current_user.id,
        Todo.status == 'done',
        Todo.done_date.in_(days),
    ).all()
    for t in done_todos:
        if t.done_date in day_data:
            day_data[t.done_date]['done'].append(t)

    # Aggregate stats
    total_focus = sum(dd['total_min'] for dd in day_data.values())
    total_sessions = sum(dd['count'] for dd in day_data.values())
    total_done = sum(len(dd['done']) for dd in day_data.values())

    # Focus ranking across 5 days
    focus_by_todo = {}
    for s in all_sessions:
        focus_by_todo.setdefault(s.todo_id, {'title': s.todo.title if s.todo else '', 'minutes': 0, 'count': 0})
        focus_by_todo[s.todo_id]['minutes'] += s.minutes
        focus_by_todo[s.todo_id]['count'] += 1
    focus_ranking = sorted(focus_by_todo.values(), key=lambda x: -x['minutes'])[:10]

    weekday_names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

    # ---- Merged from profile_stats (个人效能) ----
    from app.models.incentive import Incentive
    from app.constants import TODO_STATUS_DONE
    uid = current_user.id
    six_months_ago = today - timedelta(days=180)

    monthly_todos = db.session.query(
        db.func.strftime('%Y-%m', Todo.done_date).label('month'),
        db.func.count(Todo.id),
    ).filter(
        Todo.user_id == uid, Todo.status == TODO_STATUS_DONE,
        Todo.done_date >= six_months_ago,
    ).group_by('month').order_by('month').all()

    monthly_focus = db.session.query(
        db.func.strftime('%Y-%m', Todo.done_date).label('month'),
        db.func.sum(Todo.actual_minutes),
    ).filter(
        Todo.user_id == uid, Todo.status == TODO_STATUS_DONE,
        Todo.done_date >= six_months_ago, Todo.actual_minutes > 0,
    ).group_by('month').order_by('month').all()

    req_count = Requirement.query.filter_by(assignee_id=uid).count()
    req_done = Requirement.query.filter_by(assignee_id=uid, status='done').count()
    incentive_count = db.session.query(db.func.count(Incentive.id)).filter(
        Incentive.status == 'approved', Incentive.nominees.any(id=uid),
    ).scalar() or 0

    year_ago = today - timedelta(days=365)
    heatmap_rows = db.session.query(
        Todo.done_date, db.func.count(Todo.id),
    ).filter(
        Todo.user_id == uid, Todo.status == TODO_STATUS_DONE,
        Todo.done_date >= year_ago,
    ).group_by(Todo.done_date).all()
    heatmap = {str(row[0]): row[1] for row in heatmap_rows}

    all_focus_hours = round((db.session.query(
        db.func.sum(Todo.actual_minutes),
    ).filter(Todo.user_id == uid, Todo.actual_minutes > 0).scalar() or 0) / 60, 1)

    return render_template('dashboard/my_day.html',
                           today=today, days=days, day_data=day_data,
                           total_focus=total_focus, total_sessions=total_sessions,
                           total_done=total_done, focus_ranking=focus_ranking,
                           weekday_names=weekday_names,
                           # 个人效能
                           monthly_todos=monthly_todos, monthly_focus=monthly_focus,
                           req_count=req_count, req_done=req_done,
                           incentive_count=incentive_count,
                           heatmap=heatmap, heatmap_start=year_ago,
                           all_focus_hours=all_focus_hours,
                           timedelta=timedelta)


# ---- Personal weekly report ----

@dashboard_bp.route('/my-weekly', methods=['GET', 'POST'])
@login_required
def my_weekly():
    offset = request.args.get('week', 0, type=int)
    monday, sunday = week_range(offset)

    # Completed todos: prefer done_date, fall back to created_date for those without done_date
    my_done = Todo.query.filter_by(user_id=current_user.id, status='done')\
        .filter(db.or_(
            db.and_(Todo.done_date >= monday, Todo.done_date <= sunday),
            db.and_(Todo.done_date.is_(None), Todo.created_date >= monday, Todo.created_date <= sunday),
        ))\
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

    # Load saved report (if exists)
    saved = PersonalWeekly.query.filter_by(
        user_id=current_user.id, week_start=monday).first()

    report = None
    ai_report = None

    if request.method == 'POST':
        import markdown as md_lib

        # If no data at all, skip AI and show hint
        if not my_done and not my_active and not my_reqs:
            ai_report = '<p>本周暂无工作数据（无已完成或进行中的任务），无法生成周报。</p>'
            ai_report = md_lib.markdown(ai_report)
            report = True
            # Still save
            if saved:
                saved.ai_html = ai_report
            else:
                saved = PersonalWeekly(user_id=current_user.id, week_start=monday,
                                       week_end=sunday, ai_html=ai_report)
                db.session.add(saved)
            db.session.commit()
        else:

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

            # Recurring todo stats this week
            from app.models.recurring_todo import RecurringTodo
            from app.models.recurring_completion import RecurringCompletion
            all_recurring = RecurringTodo.query.filter_by(user_id=current_user.id, is_active=True).all()
            if all_recurring:
                # Count how many times each recurring was due this week and how many were completed
                recurring_due_count = 0
                recurring_done_count = 0
                # Get all completions this week in one query
                week_completions = set()
                for c in RecurringCompletion.query.filter(
                    RecurringCompletion.user_id == current_user.id,
                    RecurringCompletion.recurring_id.in_([r.id for r in all_recurring]),
                    RecurringCompletion.completed_date >= monday,
                    RecurringCompletion.completed_date <= sunday,
                ).all():
                    week_completions.add((c.recurring_id, c.completed_date))

                for d in range((sunday - monday).days + 1):
                    check_date = monday + timedelta(days=d)
                    if check_date > date.today():
                        break
                    for r in all_recurring:
                        is_due = False
                        if r.cycle == 'weekly' and check_date.weekday() == 0:
                            is_due = True
                        elif r.cycle == 'monthly':
                            for p in r.monthly_periods:
                                if check_date.day == r._period_day(p, check_date.year, check_date.month):
                                    is_due = True
                                    break
                        elif r.cycle == 'weekdays' and r.weekdays and str(check_date.weekday()) in r.weekdays.split(','):
                            is_due = True
                        if is_due:
                            recurring_due_count += 1
                            if (r.id, check_date) in week_completions:
                                recurring_done_count += 1

                if recurring_due_count > 0:
                    rate = round(recurring_done_count / recurring_due_count * 100)
                    lines.append(f'\n周期任务执行情况：')
                    lines.append(f'- 本周到期 {recurring_due_count} 次，完成 {recurring_done_count} 次（完成率 {rate}%）')
                    lines.append(f'- 周期任务共 {len(all_recurring)} 个：' + '、'.join(r.title for r in all_recurring))

            prompt = get_prompt('personal_weekly') + '\n\n' + '\n'.join(lines)
            _, raw = call_ollama(prompt)
            ai_report = raw or '生成失败，请重试'
            ai_report = md_lib.markdown(ai_report, extensions=['tables'])
            report = True

            # Auto-save
            if saved:
                saved.ai_html = ai_report
            else:
                saved = PersonalWeekly(
                    user_id=current_user.id, week_start=monday,
                    week_end=sunday, ai_html=ai_report)
                db.session.add(saved)
            db.session.commit()

    elif saved and saved.ai_html:
        # Load previously saved report
        ai_report = saved.ai_html
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
    elif period == 'last_month':
        first_this_month = today.replace(day=1)
        end = first_this_month - timedelta(days=1)
        start = end.replace(day=1)
    elif period == 'month':
        start = today.replace(day=1)
        end = today
    elif period == 'last_week':
        start, end = week_range(-1)
    else:
        start, end = week_range(week_offset)
    label = f'{start.strftime("%Y-%m-%d")} ~ {end.strftime("%Y-%m-%d")}'

    users = User.query.filter_by(is_active=True).order_by(User.group, User.name).all()
    user_ids = [u.id for u in users]

    # All todos in the period (by created_date, which always exists)
    todos = Todo.query.filter(
        Todo.user_id.in_(user_ids),
        Todo.created_date >= start, Todo.created_date <= end,
    ).options(joinedload(Todo.requirements)).all()

    # Per day: count todos per project, then split the day proportionally
    # e.g. day has 5 todos for projA + 1 for projB → projA=5/6天, projB=1/6天
    user_date_proj_count = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for t in todos:
        work_date = t.done_date or t.created_date
        if not work_date:
            continue
        for r in t.requirements:
            if r.project_id:
                user_date_proj_count[t.user_id][work_date][r.project_id] += 1

    user_project_days = defaultdict(float)
    for uid, dates in user_date_proj_count.items():
        for dt, proj_counts in dates.items():
            day_total = sum(proj_counts.values())
            if day_total <= 0:
                continue
            for pid, cnt in proj_counts.items():
                user_project_days[(uid, pid)] += cnt / day_total

    project_ids = sorted(set(pid for (_, pid) in user_project_days))
    projects = {p.id: p for p in Project.query.filter(Project.id.in_(project_ids)).all()} if project_ids else {}

    # Per-user total days
    user_total = defaultdict(float)
    for (uid, pid), d in user_project_days.items():
        user_total[uid] += d

    # Load expected_ratio from ProjectMember
    member_map = {}
    if project_ids:
        members = ProjectMember.query.filter(
            ProjectMember.project_id.in_(project_ids),
            ProjectMember.user_id.isnot(None)).all()
        for m in members:
            member_map[(m.user_id, m.project_id)] = m

    # Mode 1 (by_person): flat rows — one row per (person, project)
    flat_rows = []
    for u in users:
        t = user_total.get(u.id, 0)
        if t <= 0:
            continue
        for pid in project_ids:
            d = user_project_days.get((u.id, pid), 0)
            if d <= 0:
                continue
            ratio = round(d / t * 100) if t else 0
            member = member_map.get((u.id, pid))
            flat_rows.append({
                'user': u,
                'project': projects.get(pid),
                'project_id': pid,
                'days': round(d, 1),
                'ratio': ratio,
                'expected_ratio': member.expected_ratio if member else None,
            })

    # Mode 2 (by_project): flat rows — one row per (project, person)
    proj_flat_rows = []
    for pid in project_ids:
        p = projects.get(pid)
        if not p:
            continue
        proj_total = sum(user_project_days.get((u.id, pid), 0) for u in users)
        if proj_total <= 0:
            continue
        for u in users:
            d = user_project_days.get((u.id, pid), 0)
            if d <= 0:
                continue
            ratio = round(d / proj_total * 100) if proj_total else 0
            proj_flat_rows.append({
                'project': p,
                'project_id': pid,
                'user': u,
                'days': round(d, 1),
                'proj_total': round(proj_total, 1),
                'ratio': ratio,
            })

    is_pm = current_user.is_admin or current_user.has_role('PM', 'PL', 'FO', 'LM', 'XM', 'HR')
    return render_template('dashboard/resource_map.html',
        flat_rows=flat_rows, proj_flat_rows=proj_flat_rows,
        projects=projects, project_ids=project_ids, users=users,
        period=period, mode=mode, label=label, offset=week_offset,
        is_pm=is_pm,
    )


@dashboard_bp.route('/resource-map/export')
@login_required
def resource_map_export():
    """Export resource map as CSV."""
    import csv
    import io
    period = request.args.get('period', 'week')
    mode = request.args.get('mode', 'by_person')
    week_offset = request.args.get('week', 0, type=int)

    # Reuse the same logic — call resource_map internally
    with current_app.test_request_context(f'/dashboard/resource-map?period={period}&week={week_offset}&mode={mode}'):
        from flask_login import login_user
        login_user(current_user)

    # Simpler: just query directly
    from collections import defaultdict
    today = date.today()
    if period == '3month':
        start = today - timedelta(days=90)
        end = today
    elif period == 'last_month':
        first_this_month = today.replace(day=1)
        end = first_this_month - timedelta(days=1)
        start = end.replace(day=1)
    elif period == 'month':
        start = today.replace(day=1)
        end = today
    elif period == 'last_week':
        start, end = week_range(-1)
    else:
        start, end = week_range(week_offset)

    users_q = User.query.filter_by(is_active=True).order_by(User.group, User.name).all()
    user_ids = [u.id for u in users_q]
    todos = Todo.query.filter(
        Todo.user_id.in_(user_ids),
        Todo.created_date >= start, Todo.created_date <= end,
    ).options(joinedload(Todo.requirements)).all()

    user_date_proj_count = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for t in todos:
        work_date = t.done_date or t.created_date
        if not work_date:
            continue
        for r in t.requirements:
            if r.project_id:
                user_date_proj_count[t.user_id][work_date][r.project_id] += 1

    user_project_days = defaultdict(float)
    for uid, dates_data in user_date_proj_count.items():
        for dt, proj_counts in dates_data.items():
            day_total = sum(proj_counts.values())
            if day_total <= 0:
                continue
            for pid, cnt in proj_counts.items():
                user_project_days[(uid, pid)] += cnt / day_total

    project_ids = sorted(set(pid for (_, pid) in user_project_days))
    projects = {p.id: p for p in Project.query.filter(Project.id.in_(project_ids)).all()} if project_ids else {}
    user_total = defaultdict(float)
    for (uid, pid), d in user_project_days.items():
        user_total[uid] += d

    buf = io.StringIO()
    writer = csv.writer(buf)
    if mode == 'by_person':
        writer.writerow(['姓名', '工号', '项目', '投入天数', '实际比例%', '预期比例%'])
        for u in users_q:
            t = user_total.get(u.id, 0)
            if t <= 0:
                continue
            for pid in project_ids:
                d = user_project_days.get((u.id, pid), 0)
                if d <= 0:
                    continue
                ratio = round(d / t * 100) if t else 0
                member = ProjectMember.query.filter_by(user_id=u.id, project_id=pid).first()
                exp = member.expected_ratio if member and member.expected_ratio else ''
                writer.writerow([u.name, u.employee_id, projects.get(pid, type('', (), {'name': '-'})).name,
                                 round(d, 1), ratio, exp])
    else:
        writer.writerow(['项目', '项目合计', '姓名', '工号', '投入天数', '占比%'])
        for pid in project_ids:
            p = projects.get(pid)
            if not p:
                continue
            proj_total = sum(user_project_days.get((u.id, pid), 0) for u in users_q)
            if proj_total <= 0:
                continue
            for u in users_q:
                d = user_project_days.get((u.id, pid), 0)
                if d <= 0:
                    continue
                ratio = round(d / proj_total * 100)
                writer.writerow([p.name, round(proj_total, 1), u.name, u.employee_id, round(d, 1), ratio])

    output = buf.getvalue().encode('utf-8-sig')
    return send_file(io.BytesIO(output), download_name=f'人力投入_{start}_{end}.csv',
                     as_attachment=True, mimetype='text/csv')


@dashboard_bp.route('/resource-map/expected-ratio', methods=['POST'])
@login_required
def save_expected_ratio():

    if not (current_user.is_admin or current_user.has_role('PM', 'PL', 'FO', 'LM', 'XM', 'HR')):
        return jsonify(ok=False, msg='无权限'), 403
    uid = request.form.get('user_id', type=int)
    pid = request.form.get('project_id', type=int)
    ratio = request.form.get('ratio', type=int)
    if not uid or not pid:
        return jsonify(ok=False), 400
    member = ProjectMember.query.filter_by(user_id=uid, project_id=pid).first()
    if not member:
        member = ProjectMember(user_id=uid, project_id=pid, project_role='DEV')
        db.session.add(member)
    member.expected_ratio = ratio if ratio and ratio > 0 else None
    db.session.commit()
    return jsonify(ok=True)


# ---- Emotion prediction ----

@dashboard_bp.route('/emotion')
@login_required
def emotion_predict():
    if not (current_user.is_admin or current_user.has_role('PL', 'LM', 'XM', 'HR')):
        from flask import abort
        abort(403)
    from app.models.emotion import EmotionRecord
    # Load saved records grouped by date
    risk_order = db.case(
        (EmotionRecord.risk_level == 'high', 0),
        (EmotionRecord.risk_level == 'medium', 1),
        else_=2
    )
    records = EmotionRecord.query.order_by(EmotionRecord.scan_date.desc(), risk_order).all()
    dates = sorted(set(r.scan_date for r in records), reverse=True)
    grouped = {}
    for d in dates:
        grouped[d] = [r for r in records if r.scan_date == d]
    return render_template('dashboard/emotion.html', grouped=grouped, dates=dates, today=date.today())


@dashboard_bp.route('/emotion/analyze', methods=['POST'])
@login_required
def emotion_analyze():
    """AI analyzes team emotion and attrition risk."""
    if not (current_user.is_admin or current_user.has_role('PL', 'LM', 'XM', 'HR')):
        return jsonify(ok=False, msg='无权限'), 403


    from collections import defaultdict

    users = User.query.filter_by(is_active=True).order_by(User.name).all()
    today = date.today()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)

    lines = [f'分析日期：{today}\n']
    lines.append('团队成员近期工作数据：\n')

    for u in users:
        # Last 7 days
        done_7d = Todo.query.filter(
            Todo.user_id == u.id, Todo.done_date >= week_ago, Todo.done_date <= today).count()
        # Last 30 days
        done_30d = Todo.query.filter(
            Todo.user_id == u.id, Todo.done_date >= month_ago, Todo.done_date <= today).count()
        # Active (unfinished)
        active = Todo.query.filter_by(user_id=u.id, status='todo').count()
        # Blocked
        blocked = Todo.query.filter(
            Todo.user_id == u.id, Todo.status == 'todo', Todo.need_help == True).count()
        # Help given (source='help', this user as helper)
        help_given = Todo.query.filter(
            Todo.user_id == u.id, Todo.source == 'help', Todo.created_date >= month_ago).count()
        # Focus time
        focus = db.session.query(db.func.sum(Todo.actual_minutes)).filter(
            Todo.user_id == u.id, Todo.created_date >= month_ago).scalar() or 0
        # Last active date
        last_done = db.session.query(db.func.max(Todo.done_date)).filter(
            Todo.user_id == u.id).scalar()
        last_str = str(last_done) if last_done else '无记录'
        # Daily avg (30d)
        daily_avg = round(done_30d / 30, 1) if done_30d else 0

        lines.append(
            f'- {u.name}（{u.group or ""}）：\n'
            f'  近7天完成 {done_7d} 个 | 近30天完成 {done_30d} 个（日均 {daily_avg}）\n'
            f'  进行中 {active} 个 | 阻塞 {blocked} 个 | 协助他人 {help_given} 次\n'
            f'  番茄钟 {focus} 分钟 | 最后完成日期 {last_str}')

    prompt = get_prompt('emotion_predict') + '\n\n' + '\n'.join(lines)
    result, raw = call_ollama(prompt)

    if isinstance(result, list):
        return jsonify(ok=True, members=result)
    return jsonify(ok=False, raw=raw or '分析失败')


@dashboard_bp.route('/emotion/save', methods=['POST'])
@login_required
def emotion_save():
    """Save AI emotion analysis results."""
    if not (current_user.is_admin or current_user.has_role('PL', 'LM', 'XM', 'HR')):
        return jsonify(ok=False), 403
    import json as json_lib
    from app.models.emotion import EmotionRecord
    data = request.get_json() or {}
    members = data.get('members', [])
    today = date.today()
    # Delete existing records for today (re-save)
    EmotionRecord.query.filter_by(scan_date=today).delete()
    for m in members:
        db.session.add(EmotionRecord(
            scan_date=today,
            member_name=m.get('name', ''),
            group=m.get('group', ''),
            status=m.get('status', '正常'),
            risk_level=m.get('risk_level', 'low'),
            signals=json_lib.dumps(m.get('signals', []), ensure_ascii=False),
            suggestion=m.get('suggestion', ''),
            created_by=current_user.id,
        ))
    db.session.commit()
    return jsonify(ok=True, count=len(members))


@dashboard_bp.route('/emotion/delete-record/<int:record_id>', methods=['POST'])
@login_required
def emotion_delete_record(record_id):
    """Delete a single emotion record."""
    from app.models.emotion import EmotionRecord
    r = db.session.get(EmotionRecord, record_id)
    if r:
        db.session.delete(r)
        db.session.commit()
    return jsonify(ok=True)


@dashboard_bp.route('/emotion/delete/<scan_date>', methods=['POST'])
@login_required
def emotion_delete(scan_date):
    """Delete all emotion records for a specific date."""
    if not (current_user.is_admin or current_user.has_role('PL', 'LM', 'XM', 'HR')):
        from flask import abort
        abort(403)
    from app.models.emotion import EmotionRecord
    deleted = EmotionRecord.query.filter_by(scan_date=scan_date).delete()
    db.session.commit()
    flash(f'已删除 {scan_date} 的记录', 'success')
    return redirect(url_for('dashboard.emotion_predict'))


@dashboard_bp.route('/emotion/comment/<int:record_id>', methods=['POST'])
@login_required
def emotion_comment(record_id):
    """Add comment to an emotion record. Supports #comment and @person for todo."""
    from app.models.emotion import EmotionRecord, EmotionComment
    from app.models.todo import Todo, TodoItem
    import re

    record = db.get_or_404(EmotionRecord, record_id)
    content = request.form.get('content', '').strip()[:500]
    if not content:
        return redirect(url_for('dashboard.emotion_predict'))

    # Save comment
    db.session.add(EmotionComment(record_id=record.id, user_id=current_user.id, content=content))

    # Check for @mention — create a follow-up todo
    at_match = re.search(r'@(\S+)', content)
    if at_match:
        target_name = at_match.group(1)
        target_user = User.query.filter(
            db.or_(User.name == target_name, User.pinyin.ilike(f'{target_name}%'))
        ).filter_by(is_active=True).first()
        if target_user:
            clean_content = re.sub(r'@\S+', '', content).strip()
            todo_title = f'[情绪跟进] {record.member_name}：{clean_content[:50]}'
            todo = Todo(user_id=target_user.id, title=todo_title,
                        due_date=date.today() + timedelta(days=7), category='team', source='help')
            todo.items.append(TodoItem(title=todo_title, sort_order=0))
            db.session.add(todo)

    db.session.commit()
    return redirect(url_for('dashboard.emotion_predict'))
