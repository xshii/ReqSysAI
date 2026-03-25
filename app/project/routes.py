from datetime import date, timedelta

from flask import flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.constants import MILESTONE_COLOR
from app.extensions import db
from app.models.project import Milestone, Project
from app.models.project_member import ProjectMember
from app.models.risk import Risk
from app.models.user import User
from app.project import project_bp
from app.project.forms import MilestoneForm, ProjectForm


def _resolve_owner_id(owner_name):
    """Match owner name to system user, return user_id or None."""
    if not owner_name:
        return None
    u = User.query.filter(db.or_(User.name == owner_name, User.name == owner_name.strip())).filter_by(is_active=True).first()
    return u.id if u else None


@project_bp.route('/')
@login_required
def project_list():
    status = request.args.get('status', 'active')
    query = Project.query
    if status != 'all':
        query = query.filter_by(status=status)
    projects = query.order_by(Project.created_at.desc()).all()
    return render_template('project/list.html', projects=projects, cur_status=status)


@project_bp.route('/new', methods=['GET', 'POST'])
@login_required
def project_create():
    from app.models.project import MilestoneTemplate

    form = ProjectForm()
    form.parent_id.choices = [(0, '-- 无（顶级项目）--')] + [
        (p.id, p.name) for p in Project.query.filter_by(status='active').order_by(Project.name).all()]
    templates = MilestoneTemplate.query.order_by(MilestoneTemplate.name).all()

    if form.validate_on_submit():
        project = Project(
            name=form.name.data,
            description=form.description.data,
            parent_id=form.parent_id.data or None,
            created_by=current_user.id,
        )
        db.session.add(project)
        db.session.flush()

        # Create milestones from form
        ms_names = request.form.getlist('ms_name')
        ms_dates = request.form.getlist('ms_date')
        for i, name in enumerate(ms_names):
            name = name.strip()
            if name:
                due_str = ms_dates[i] if i < len(ms_dates) and ms_dates[i] else ''
                due = date.fromisoformat(due_str) if due_str else None
                project.milestones.append(Milestone(name=name, due_date=due))

        db.session.commit()
        flash(f'项目「{project.name}」创建成功', 'success')
        return redirect(url_for('project.project_detail', project_id=project.id))
    return render_template('project/form.html', form=form, title='新建项目', templates=templates)


@project_bp.route('/milestone-templates', methods=['POST'])
@login_required
def milestone_template_action():
    """Create / edit / delete / copy milestone templates."""
    from app.constants import parse_offset
    from app.models.project import MilestoneTemplate, MilestoneTemplateItem

    action = request.form.get('action')

    if action == 'create':
        name = request.form.get('name', '').strip()
        if not name:
            flash('请输入模板名称', 'danger')
        elif MilestoneTemplate.query.filter_by(name=name).first():
            flash(f'模板 {name} 已存在', 'warning')
        else:
            tpl = MilestoneTemplate(name=name, description=request.form.get('description', '').strip() or None)
            item_names = request.form.getlist('item_name')
            item_offsets = request.form.getlist('item_offset')
            cumulative = 0
            for i, iname in enumerate(item_names):
                iname = iname.strip()
                if iname:
                    raw = item_offsets[i].strip() if i < len(item_offsets) and item_offsets[i] else '0'
                    cumulative += parse_offset(raw)
                    tpl.items.append(MilestoneTemplateItem(name=iname, offset_days=cumulative, sort_order=i))
            db.session.add(tpl)
            db.session.commit()
            flash(f'模板 {name} 已创建', 'success')

    elif action == 'edit':
        tpl_id = request.form.get('template_id', type=int)
        tpl = db.session.get(MilestoneTemplate, tpl_id) if tpl_id else None
        if tpl:
            tpl.name = request.form.get('name', '').strip() or tpl.name
            tpl.description = request.form.get('description', '').strip() or None
            MilestoneTemplateItem.query.filter_by(template_id=tpl.id).delete()
            item_names = request.form.getlist('item_name')
            item_offsets = request.form.getlist('item_offset')
            cumulative = 0
            for i, iname in enumerate(item_names):
                iname = iname.strip()
                if iname:
                    raw = item_offsets[i].strip() if i < len(item_offsets) and item_offsets[i] else '0'
                    cumulative += parse_offset(raw)
                    tpl.items.append(MilestoneTemplateItem(name=iname, offset_days=cumulative, sort_order=i))
            db.session.commit()
            flash(f'模板 {tpl.name} 已更新', 'success')

    elif action == 'copy':
        tpl_id = request.form.get('template_id', type=int)
        tpl = db.session.get(MilestoneTemplate, tpl_id) if tpl_id else None
        if tpl:
            new_name = f'{tpl.name}（副本）'
            idx = 2
            while MilestoneTemplate.query.filter_by(name=new_name).first():
                new_name = f'{tpl.name}（副本{idx}）'
                idx += 1
            copy = MilestoneTemplate(name=new_name, description=tpl.description)
            for item in tpl.items:
                copy.items.append(MilestoneTemplateItem(name=item.name, offset_days=item.offset_days, sort_order=item.sort_order))
            db.session.add(copy)
            db.session.commit()
            flash(f'已复制为 {new_name}', 'success')

    elif action == 'delete':
        tpl_id = request.form.get('template_id', type=int)
        tpl = db.session.get(MilestoneTemplate, tpl_id) if tpl_id else None
        if tpl:
            db.session.delete(tpl)
            db.session.commit()
            flash(f'模板 {tpl.name} 已删除', 'success')

    next_url = request.form.get('next') or request.args.get('next')
    return redirect(next_url) if next_url else redirect(request.referrer or url_for('project.project_list'))


@project_bp.route('/api/template/<int:tpl_id>')
@login_required
def api_template(tpl_id):
    from app.models.project import MilestoneTemplate
    tpl = db.session.get(MilestoneTemplate, tpl_id)
    if not tpl:
        return jsonify(ok=False), 404
    return jsonify(ok=True, items=[
        {'name': item.name, 'offset_days': item.offset_days}
        for item in tpl.items
    ])


@project_bp.route('/api/templates', methods=['GET', 'POST'])
@login_required
def api_templates():
    """List / create / delete milestone templates (accessible to all users)."""
    from app.constants import parse_offset
    from app.models.project import MilestoneTemplate, MilestoneTemplateItem

    if request.method == 'POST':
        data = request.get_json() or {}
        action = data.get('action')
        if action == 'create':
            name = (data.get('name') or '').strip()
            if not name:
                return jsonify(ok=False, msg='名称不能为空')
            if MilestoneTemplate.query.filter_by(name=name).first():
                return jsonify(ok=False, msg=f'模板 {name} 已存在')
            tpl = MilestoneTemplate(name=name, description=(data.get('description') or '').strip() or None)
            cumulative = 0
            for i, item in enumerate(data.get('items', [])):
                iname = (item.get('name') or '').strip()
                if iname:
                    cumulative += parse_offset(item.get('offset', 0))
                    tpl.items.append(MilestoneTemplateItem(name=iname, offset_days=cumulative, sort_order=i))
            db.session.add(tpl)
            db.session.commit()
            return jsonify(ok=True, id=tpl.id)
        elif action == 'copy':
            tpl_id = data.get('id')
            tpl = db.session.get(MilestoneTemplate, tpl_id) if tpl_id else None
            if not tpl:
                return jsonify(ok=False, msg='模板不存在')
            new_name = f'{tpl.name}（副本）'
            idx = 2
            while MilestoneTemplate.query.filter_by(name=new_name).first():
                new_name = f'{tpl.name}（副本{idx}）'
                idx += 1
            copy = MilestoneTemplate(name=new_name, description=tpl.description)
            for item in tpl.items:
                copy.items.append(MilestoneTemplateItem(name=item.name, offset_days=item.offset_days, sort_order=item.sort_order))
            db.session.add(copy)
            db.session.commit()
            return jsonify(ok=True, id=copy.id, name=new_name)
        elif action == 'delete':
            tpl_id = data.get('id')
            tpl = db.session.get(MilestoneTemplate, tpl_id) if tpl_id else None
            if tpl:
                db.session.delete(tpl)
                db.session.commit()
            return jsonify(ok=True)

    # GET: return all templates
    templates = MilestoneTemplate.query.order_by(MilestoneTemplate.name).all()
    result = []
    for t in templates:
        items = []
        prev = 0
        for item in t.items:
            delta = item.offset_days - prev
            items.append({'name': item.name, 'offset': delta, 'cumulative': item.offset_days})
            prev = item.offset_days
        result.append({'id': t.id, 'name': t.name, 'description': t.description, 'items': items})
    return jsonify(ok=True, templates=result)


@project_bp.route('/<int:project_id>')
@login_required
def project_detail(project_id):
    from datetime import date as d_date

    from sqlalchemy.orm import joinedload

    from app.models.requirement import Requirement
    from app.models.todo import Todo, todo_requirements

    project = db.get_or_404(Project, project_id)
    today = d_date.today()

    # Requirements stats
    reqs = Requirement.query.filter_by(project_id=project_id, parent_id=None).order_by(Requirement.number).all()
    req_total = len(reqs)
    req_done = sum(1 for r in reqs if r.status in ('done', 'closed'))
    req_overdue = [r for r in reqs if r.due_date and r.due_date < today and r.status not in ('done', 'closed', 'cancelled')]

    # Open risks
    open_risks = Risk.query.filter_by(project_id=project_id, status='open').order_by(Risk.severity).all()

    # Key members
    key_members = ProjectMember.query.filter_by(project_id=project_id, is_key=True).all()

    # Recent completed todos (last 7 days)
    week_ago = today - timedelta(days=7)
    req_ids = [r.id for r in reqs]
    recent_done = []
    if req_ids:
        recent_done = Todo.query.filter(
            Todo.done_date >= week_ago
        ).join(todo_requirements, Todo.id == todo_requirements.c.todo_id).filter(
            todo_requirements.c.requirement_id.in_(req_ids)
        ).options(joinedload(Todo.user)).order_by(Todo.done_date.desc()).limit(10).all()

    # Generate milestone timeline image
    timeline_img = None
    if project.milestones:
        try:
            from app.services.timeline import generate_timeline_image
            ms_data = [{'name': m.name, 'due_date': m.due_date, 'status': m.status} for m in project.milestones]
            timeline_img = generate_timeline_image(ms_data)
        except Exception:
            pass

    return render_template('project/detail.html', project=project, today=today,
                           reqs=reqs, req_total=req_total, req_done=req_done,
                           req_overdue=req_overdue, open_risks=open_risks,
                           key_members=key_members, recent_done=recent_done,
                           milestone_color=MILESTONE_COLOR, timeline_img=timeline_img)


@project_bp.route('/<int:project_id>/follow', methods=['POST'])
@login_required
def toggle_follow(project_id):
    """Toggle follow/unfollow a project."""
    project = db.get_or_404(Project, project_id)
    if project in current_user.followed_projects.all():
        current_user.followed_projects.remove(project)
        followed = False
    else:
        current_user.followed_projects.append(project)
        followed = True
    db.session.commit()
    if request.is_json:
        return jsonify(ok=True, followed=followed)
    return redirect(url_for('project.project_detail', project_id=project_id))


@project_bp.route('/<int:project_id>/edit', methods=['GET', 'POST'])
@login_required
def project_edit(project_id):
    project = db.get_or_404(Project, project_id)
    form = ProjectForm(obj=project)
    form.parent_id.choices = [(0, '-- 无（顶级项目）--')] + [
        (p.id, p.name) for p in Project.query.filter(
            Project.status == 'active', Project.id != project_id).order_by(Project.name).all()]
    if not form.is_submitted():
        form.parent_id.data = project.parent_id or 0
    if form.validate_on_submit():
        project.name = form.name.data
        project.description = form.description.data
        project.parent_id = form.parent_id.data or None
        # Save milestones
        ms_names = request.form.getlist('ms_name')
        ms_dates = request.form.getlist('ms_date')
        Milestone.query.filter_by(project_id=project.id).delete()
        for i, name in enumerate(ms_names):
            name = name.strip()
            if name:
                due_str = ms_dates[i].strip() if i < len(ms_dates) and ms_dates[i] else ''
                due = date.fromisoformat(due_str) if due_str else None
                db.session.add(Milestone(
                    project_id=project.id, name=name,
                    due_date=due, status='active',
                ))
        db.session.commit()
        flash('项目更新成功', 'success')
        return redirect(url_for('project.project_detail', project_id=project.id))
    from app.models.project import MilestoneTemplate
    from app.models.project_member import ProjectMember
    templates = MilestoneTemplate.query.order_by(MilestoneTemplate.name).all()
    members = ProjectMember.query.filter_by(project_id=project.id).all()
    member_ids = {m.user_id for m in members}
    available = [u for u in User.query.filter_by(is_active=True).order_by(User.name).all()
                 if u.id not in member_ids]
    return render_template('project/form.html', form=form, project=project,
                           templates=templates, members=members, available=available,
                           roles=ProjectMember.DEFAULT_ROLES,
                           title=f'编辑项目 - {project.name}')


@project_bp.route('/<int:project_id>/status', methods=['POST'])
@login_required
def project_status(project_id):
    project = db.get_or_404(Project, project_id)
    new_status = request.form.get('status')
    if new_status in Project.STATUS_LABELS:
        project.status = new_status
        db.session.commit()
        flash(f'项目已标记为「{project.status_label}」', 'success')
    return redirect(url_for('project.project_detail', project_id=project.id))


# --- Milestones ---

@project_bp.route('/<int:project_id>/milestones/new', methods=['GET', 'POST'])
@login_required
def milestone_create(project_id):
    project = db.get_or_404(Project, project_id)
    form = MilestoneForm()
    if form.validate_on_submit():
        ms = Milestone(project_id=project.id, name=form.name.data, due_date=form.due_date.data)
        db.session.add(ms)
        db.session.commit()
        flash(f'里程碑「{ms.name}」创建成功', 'success')
        return redirect(url_for('project.project_detail', project_id=project.id))
    return render_template('project/milestone_form.html', form=form, project=project, title='新建里程碑')


@project_bp.route('/milestones/<int:ms_id>/edit', methods=['GET', 'POST'])
@login_required
def milestone_edit(ms_id):
    ms = db.get_or_404(Milestone, ms_id)
    form = MilestoneForm(obj=ms)
    if form.validate_on_submit():
        ms.name = form.name.data
        ms.due_date = form.due_date.data
        db.session.commit()
        flash('里程碑更新成功', 'success')
        return redirect(url_for('project.project_detail', project_id=ms.project_id))
    return render_template('project/milestone_form.html', form=form, project=ms.project, title=f'编辑里程碑 - {ms.name}')


@project_bp.route('/milestones/<int:ms_id>/toggle', methods=['POST'])
@login_required
def milestone_toggle(ms_id):
    ms = db.get_or_404(Milestone, ms_id)
    ms.status = 'completed' if ms.status == 'active' else 'active'
    db.session.commit()
    flash(f'里程碑「{ms.name}」已标记为{"已完成" if ms.status == "completed" else "进行中"}', 'success')
    return redirect(url_for('project.project_detail', project_id=ms.project_id))


@project_bp.route('/milestones/<int:ms_id>/delete', methods=['POST'])
@login_required
def milestone_delete(ms_id):
    ms = db.get_or_404(Milestone, ms_id)
    project_id = ms.project_id
    if ms.requirements:
        flash('该里程碑下有关联需求，无法删除', 'danger')
    else:
        db.session.delete(ms)
        db.session.commit()
        flash('里程碑已删除', 'success')
    return redirect(url_for('project.project_detail', project_id=project_id))
