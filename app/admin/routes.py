import csv
import io
import logging
import os

import requests
import yaml
from flask import render_template, redirect, url_for, flash, request, current_app, Response, jsonify

logger = logging.getLogger(__name__)

from app.admin import admin_bp
from app.admin.forms import UserCreateForm, UserEditForm
from app.decorators import admin_required
from app.extensions import db
from app.models.user import User, Role, Group
from app.models.project import MilestoneTemplate, MilestoneTemplateItem
from app.services.ai import check_ollama_status
from app.services.prompts import get_all_prompts, save_all_prompts, LABELS as PROMPT_LABELS, DEFAULTS as PROMPT_DEFAULTS
from app.models.ip_request import IPChangeRequest
from app.utils.pinyin import to_pinyin

from datetime import datetime


@admin_bp.route('/users')
@admin_required
def user_list():
    filter_group = request.args.get('group', '')
    q = User.query
    if filter_group == '_none':
        q = q.filter(db.or_(User.group.is_(None), User.group == ''))
    elif filter_group:
        q = q.filter_by(group=filter_group)
    users = q.order_by(User.group, User.name).all()

    all_groups = [g.name for g in Group.query.order_by(Group.name).all()]
    group_counts = {}
    for g in all_groups:
        group_counts[g] = User.query.filter_by(group=g, is_active=True).count()

    hidden = set(current_app.config.get('HIDDEN_ROLES', []) + ['Admin'])
    visible_roles = [r for r in Role.query.order_by(Role.id).all() if r.name not in hidden]

    ip_requests = IPChangeRequest.query.filter_by(status='pending')\
        .order_by(IPChangeRequest.created_at.desc()).all()

    return render_template('admin/users.html', users=users, visible_roles=visible_roles,
                           all_groups=all_groups, group_counts=group_counts,
                           filter_group=filter_group, ip_requests=ip_requests)


@admin_bp.route('/users/new', methods=['GET', 'POST'])
@admin_required
def user_create():
    form = UserCreateForm()
    form.role_ids.choices = [(r.id, r.name) for r in Role.query.order_by(Role.id).all()]

    if form.validate_on_submit():
        if User.query.filter_by(ip_address=form.ip_address.data).first():
            flash('该 IP 已被绑定', 'danger')
            return render_template('admin/user_form.html', form=form, title='创建用户')

        selected_roles = Role.query.filter(Role.id.in_(form.role_ids.data)).all()
        user = User(
            employee_id=form.employee_id.data,
            name=form.name.data,
            pinyin=to_pinyin(form.name.data),
            ip_address=form.ip_address.data,
            group=form.group.data or None,
            roles=selected_roles,
        )
        db.session.add(user)
        db.session.commit()
        flash(f'用户 {user.name} 创建成功', 'success')
        return redirect(url_for('admin.user_list'))

    return render_template('admin/user_form.html', form=form, title='创建用户')


@admin_bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@admin_required
def user_edit(user_id):
    user = db.get_or_404(User, user_id)
    form = UserEditForm(obj=user)
    form.role_ids.choices = [(r.id, r.name) for r in Role.query.order_by(Role.id).all()]
    if not form.is_submitted():
        form.role_ids.data = [r.id for r in user.roles]

    if form.validate_on_submit():
        existing = User.query.filter(
            User.ip_address == form.ip_address.data, User.id != user.id
        ).first()
        if existing:
            flash(f'该 IP 已被 {existing.name} 绑定', 'danger')
            return render_template('admin/user_form.html', form=form, title=f'编辑用户 - {user.name}', user=user)

        user.employee_id = form.employee_id.data
        user.name = form.name.data
        user.pinyin = to_pinyin(form.name.data)
        user.ip_address = form.ip_address.data
        user.group = form.group.data or None
        user.roles = Role.query.filter(Role.id.in_(form.role_ids.data)).all()
        user.is_active = form.is_active.data
        db.session.commit()
        flash(f'用户 {user.name} 更新成功', 'success')
        return redirect(url_for('admin.user_list'))

    return render_template('admin/user_form.html', form=form, title=f'编辑用户 - {user.name}', user=user)


@admin_bp.route('/ip-request/<int:req_id>/approve', methods=['POST'])
@admin_required
def ip_request_approve(req_id):
    r = db.get_or_404(IPChangeRequest, req_id)
    r.status = 'approved'
    r.reviewed_by = current_user.id
    r.reviewed_at = datetime.utcnow()
    # Update user IP
    user = db.session.get(User, r.user_id)
    if user:
        user.ip_address = r.new_ip
    db.session.commit()
    flash(f'已同意 {user.name} 的 IP 更换申请', 'success')
    return redirect(url_for('admin.user_list'))


@admin_bp.route('/ip-request/<int:req_id>/reject', methods=['POST'])
@admin_required
def ip_request_reject(req_id):
    r = db.get_or_404(IPChangeRequest, req_id)
    r.status = 'rejected'
    r.reviewed_by = current_user.id
    r.reviewed_at = datetime.utcnow()
    db.session.commit()
    flash('已拒绝 IP 更换申请', 'info')
    return redirect(url_for('admin.user_list'))


@admin_bp.route('/users/<int:user_id>/toggle', methods=['POST'])
@admin_required
def user_toggle(user_id):
    user = db.get_or_404(User, user_id)
    user.is_active = not user.is_active
    db.session.commit()
    status = '启用' if user.is_active else '禁用'
    flash(f'用户 {user.name} 已{status}', 'success')
    return redirect(url_for('admin.user_list'))


def _decode_csv(file):
    """Read uploaded file and decode to text. Returns text or None."""
    raw = file.read()
    for enc in ('utf-8-sig', 'gbk', 'utf-8'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return None


def _do_csv_import(text, require_group=False):
    """Shared CSV import logic. ID优先匹配，其次工号。

    CSV columns: ID(可选), 姓名(*), 工号(*), 小组, 角色
    """
    reader = csv.DictReader(io.StringIO(text))
    fields = set(reader.fieldnames or [])
    required = {'姓名', '工号'}
    if require_group:
        required.add('小组')
    if not required.issubset(fields):
        flash(f'CSV 表头缺少必填列：{", ".join(required)}', 'danger')
        return

    has_id = 'ID' in fields
    hidden = set(current_app.config.get('HIDDEN_ROLES', []) + ['Admin'])
    created, updated, skipped = 0, 0, 0
    new_groups = set()
    errors = []

    for i, row in enumerate(reader, start=2):
        uid = (row.get('ID') or '').strip() if has_id else ''
        name = (row.get('姓名') or '').strip()
        eid = (row.get('工号') or '').strip().lower()
        group = (row.get('小组') or '').strip() or None
        role_str = (row.get('角色') or '').strip()

        if not name or not eid:
            skipped += 1
            errors.append(f'第{i}行：姓名或工号为空，已跳过')
            continue
        if require_group and not group:
            skipped += 1
            errors.append(f'第{i}行：小组为空，已跳过')
            continue

        # Auto-create group
        if group and group not in new_groups and not Group.query.filter_by(name=group).first():
            db.session.add(Group(name=group))
            new_groups.add(group)

        # Parse roles
        role_names = [r.strip() for r in role_str.replace(',', ';').split(';') if r.strip()]
        role_names = [r for r in role_names if r not in hidden]
        roles = Role.query.filter(Role.name.in_(role_names)).all() if role_names else []
        if role_names and len(roles) != len(role_names):
            found = {r.name for r in roles}
            errors.append(f'第{i}行({eid})：未知角色 {", ".join(set(role_names) - found)}，已忽略')

        # Match: ID first, then employee_id
        user = None
        if uid and uid.isdigit():
            user = db.session.get(User, int(uid))
        if not user:
            user = User.query.filter_by(employee_id=eid).first()

        if user:
            user.employee_id = eid
            user.name = name
            user.pinyin = to_pinyin(name)
            user.group = group
            kept = [r for r in user.roles if r.name in hidden]
            user.roles = kept + (roles if roles else [r for r in user.roles if r.name not in hidden])
            updated += 1
        else:
            user = User(
                employee_id=eid, name=name, pinyin=to_pinyin(name),
                ip_address=f'pending-{eid}', group=group, roles=roles,
            )
            db.session.add(user)
            created += 1

    db.session.commit()
    msg = f'导入完成：新建 {created} 人，更新 {updated} 人'
    if new_groups:
        msg += f'，自动创建团队 {len(new_groups)} 个'
    if skipped:
        msg += f'，跳过 {skipped} 行'
    flash(msg, 'success')
    if errors:
        flash('；'.join(errors[:10]), 'warning')


@admin_bp.route('/users/import-csv', methods=['POST'])
@admin_required
def user_import_csv():
    """Import users from uploaded CSV."""
    file = request.files.get('csv_file')
    if not file or not file.filename:
        flash('请选择 CSV 文件', 'danger')
        return redirect(url_for('admin.user_list'))
    if not file.filename.lower().endswith('.csv'):
        flash('仅支持 .csv 文件', 'danger')
        return redirect(url_for('admin.user_list'))
    try:
        text = _decode_csv(file)
        if not text:
            flash('文件编码无法识别，请使用 UTF-8 或 GBK 编码', 'danger')
            return redirect(url_for('admin.user_list'))
        _do_csv_import(text)
    except Exception as e:
        db.session.rollback()
        flash(f'导入失败：{e}', 'danger')
    return redirect(url_for('admin.user_list'))


@admin_bp.route('/users/<int:user_id>/group', methods=['POST'])
@admin_required
def user_update_group(user_id):
    """Inline group change from user table."""
    user = db.get_or_404(User, user_id)
    user.group = request.form.get('group', '').strip() or None
    db.session.commit()
    return redirect(request.referrer or url_for('admin.user_list'))


@admin_bp.route('/groups/action', methods=['POST'])
@admin_required
def group_action():
    action = request.form.get('action')
    if action == 'create':
        name = request.form.get('group_name', '').strip()
        if not name:
            flash('请输入团队名称', 'danger')
        elif Group.query.filter_by(name=name).first():
            flash(f'团队 {name} 已存在', 'warning')
        else:
            db.session.add(Group(name=name))
            db.session.commit()
            flash(f'团队 {name} 已创建', 'success')
    elif action == 'rename':
        old_name = request.form.get('old_name', '').strip()
        new_name = request.form.get('new_name', '').strip()
        if old_name and new_name:
            g = Group.query.filter_by(name=old_name).first()
            if g:
                g.name = new_name
            User.query.filter_by(group=old_name).update({'group': new_name})
            db.session.commit()
            flash(f'团队 {old_name} 已重命名为 {new_name}', 'success')
    elif action == 'delete':
        name = request.form.get('group_name', '').strip()
        if name:
            g = Group.query.filter_by(name=name).first()
            if g:
                db.session.delete(g)
            User.query.filter_by(group=name).update({'group': None})
            db.session.commit()
            flash(f'团队 {name} 已解散', 'success')
    return redirect(url_for('admin.user_list'))


@admin_bp.route('/groups/export-csv')
@admin_required
def group_export_csv():
    """Export all active members as CSV."""
    hidden = set(current_app.config.get('HIDDEN_ROLES', []) + ['Admin'])
    users = User.query.filter_by(is_active=True)\
        .order_by(User.group, User.name).all()

    buf = io.StringIO()
    buf.write('\ufeff')  # BOM for Excel
    writer = csv.writer(buf)
    writer.writerow(['ID', '姓名', '工号', '小组', '角色'])
    for u in users:
        role_names = ';'.join(r.name for r in u.roles if r.name not in hidden)
        writer.writerow([u.id, u.name, u.employee_id, u.group or '', role_names])

    return Response(
        buf.getvalue(),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': 'attachment; filename=teams.csv'},
    )


# ---- Milestone templates ----

@admin_bp.route('/milestone-templates', methods=['GET', 'POST'])
@admin_required
def milestone_template_list():

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'create':
            name = request.form.get('name', '').strip()
            if not name:
                flash('请输入模板名称', 'danger')
            elif MilestoneTemplate.query.filter_by(name=name).first():
                flash(f'模板 {name} 已存在', 'warning')
            else:
                tpl = MilestoneTemplate(
                    name=name,
                    description=request.form.get('description', '').strip() or None,
                )
                # Parse milestone items
                item_names = request.form.getlist('item_name')
                item_offsets = request.form.getlist('item_offset')
                for i, iname in enumerate(item_names):
                    iname = iname.strip()
                    if iname:
                        offset = int(item_offsets[i]) if i < len(item_offsets) and item_offsets[i] else 0
                        tpl.items.append(MilestoneTemplateItem(name=iname, offset_days=offset, sort_order=i))
                db.session.add(tpl)
                db.session.commit()
                flash(f'模板 {name} 已创建', 'success')
        elif action == 'delete':
            tpl_id = request.form.get('template_id', type=int)
            tpl = db.session.get(MilestoneTemplate, tpl_id) if tpl_id else None
            if tpl:
                db.session.delete(tpl)
                db.session.commit()
                flash(f'模板 {tpl.name} 已删除', 'success')
        return redirect(url_for('admin.milestone_template_list'))

    templates = MilestoneTemplate.query.order_by(MilestoneTemplate.name).all()
    return render_template('admin/milestone_templates.html', templates=templates)


# ---- AI Model management ----

def _ollama_request(method, path, **kwargs):
    """Send request to Ollama API. Returns (response_json, error_msg)."""
    ok, err = check_ollama_status()
    if not ok:
        return None, err
    base_url = current_app.config['OLLAMA_BASE_URL']
    try:
        resp = getattr(requests, method)(
            f'{base_url}{path}', timeout=30,
            proxies={'http': '', 'https': ''}, **kwargs,
        )
        resp.raise_for_status()
        return resp.json(), None
    except requests.RequestException as e:
        return None, str(e)


@admin_bp.route('/ai-models')
@admin_required
def ai_model_list():
    data, err = _ollama_request('get', '/api/tags')
    models = []
    if data:
        for m in data.get('models', []):
            size_gb = (m.get('size', 0) / 1e9)
            models.append({
                'name': m['name'],
                'size': f'{size_gb:.1f} GB' if size_gb >= 1 else f'{m.get("size", 0) / 1e6:.0f} MB',
                'modified': m.get('modified_at', '')[:19].replace('T', ' '),
                'family': m.get('details', {}).get('family', ''),
                'params': m.get('details', {}).get('parameter_size', ''),
            })
    current_model = current_app.config['OLLAMA_MODEL']

    # Read default system prompt from Modelfile
    modelfile_path = os.path.join(current_app.root_path, '..', 'scripts', 'Modelfile.reqsys')
    default_prompt = ''
    if os.path.exists(modelfile_path):
        with open(modelfile_path, encoding='utf-8') as f:
            content = f.read()
            # Extract SYSTEM block
            if 'SYSTEM' in content:
                start = content.index('SYSTEM')
                # Find the content between triple quotes
                if '"""' in content[start:]:
                    s = content.index('"""', start) + 3
                    e = content.index('"""', s)
                    default_prompt = content[s:e].strip()

    prompts = get_all_prompts()

    ai_provider = current_app.config.get('AI_PROVIDER', 'ollama')
    return render_template('admin/ai_models.html',
                           models=models, err=err, current_model=current_model,
                           default_prompt=default_prompt,
                           prompts=prompts, prompt_labels=PROMPT_LABELS,
                           prompt_defaults=PROMPT_DEFAULTS,
                           ai_provider=ai_provider,
                           openai_base_url=current_app.config.get('OPENAI_BASE_URL', ''),
                           openai_api_key=current_app.config.get('OPENAI_API_KEY', ''),
                           openai_model=current_app.config.get('OPENAI_MODEL', 'gpt-4o-mini'))


@admin_bp.route('/ai-models/create', methods=['POST'])
@admin_required
def ai_model_create():
    base_model = request.form.get('base_model', '').strip()
    new_name = request.form.get('new_name', '').strip()
    system_prompt = request.form.get('system_prompt', '').strip()

    if not base_model or not new_name:
        flash('请填写基础模型和新模型名称', 'danger')
        return redirect(url_for('admin.ai_model_list'))

    modelfile = f'FROM {base_model}\n'
    if system_prompt:
        escaped = system_prompt.replace('"""', '\\"\\"\\"')
        modelfile += f'\nSYSTEM """{escaped}"""'

    # Ollama create is synchronous and can take a while
    ok, err = check_ollama_status()
    if not ok:
        flash(f'AI 服务不可用：{err}', 'danger')
        return redirect(url_for('admin.ai_model_list'))

    base_url = current_app.config['OLLAMA_BASE_URL']
    try:
        resp = requests.post(
            f'{base_url}/api/create',
            json={'name': new_name, 'modelfile': modelfile},
            timeout=300,
            proxies={'http': '', 'https': ''},
        )
        resp.raise_for_status()
        flash(f'模型 {new_name} 创建成功（基于 {base_model}）', 'success')

        # Save Modelfile to scripts/ for reference
        scripts_dir = os.path.join(current_app.root_path, '..', 'scripts')
        os.makedirs(scripts_dir, exist_ok=True)
        save_path = os.path.join(scripts_dir, f'Modelfile.{new_name}')
        with open(save_path, 'w', encoding='utf-8') as f:
            f.write(modelfile)

    except requests.RequestException as e:
        flash(f'模型创建失败：{e}', 'danger')

    return redirect(url_for('admin.ai_model_list'))


@admin_bp.route('/ai-models/set-active', methods=['POST'])
@admin_required
def ai_model_set_active():
    """Update config.local.yml to use selected model."""
    model_name = request.form.get('model_name', '').strip()
    if not model_name:
        flash('请选择模型', 'danger')
        return redirect(url_for('admin.ai_model_list'))

    local_path = os.path.join(current_app.root_path, '..', 'config.local.yml')
    local_cfg = {}
    if os.path.exists(local_path):
        with open(local_path, encoding='utf-8') as f:
            local_cfg = yaml.safe_load(f) or {}

    local_cfg.setdefault('ollama', {})['model'] = model_name
    with open(local_path, 'w', encoding='utf-8') as f:
        yaml.dump(local_cfg, f, allow_unicode=True, default_flow_style=False)

    # Update runtime config
    current_app.config['OLLAMA_MODEL'] = model_name
    flash(f'当前使用模型已切换为 {model_name}（已写入 config.local.yml）', 'success')
    return redirect(url_for('admin.ai_model_list'))


@admin_bp.route('/ai-models/delete', methods=['POST'])
@admin_required
def ai_model_delete():
    model_name = request.form.get('model_name', '').strip()
    if not model_name:
        flash('请选择模型', 'danger')
        return redirect(url_for('admin.ai_model_list'))

    if model_name == current_app.config['OLLAMA_MODEL']:
        flash('不能删除当前正在使用的模型', 'danger')
        return redirect(url_for('admin.ai_model_list'))

    data, err = _ollama_request('delete', '/api/delete', json={'name': model_name})
    if err:
        flash(f'删除失败：{err}', 'danger')
    else:
        flash(f'模型 {model_name} 已删除', 'success')
    return redirect(url_for('admin.ai_model_list'))


@admin_bp.route('/ai-models/set-provider', methods=['POST'])
@admin_required
def ai_set_provider():
    """Switch AI provider (ollama/openai)."""
    provider = request.form.get('provider', 'ollama')
    local_path = os.path.join(current_app.root_path, '..', 'config.local.yml')
    local_cfg = {}
    if os.path.exists(local_path):
        with open(local_path, encoding='utf-8') as f:
            local_cfg = yaml.safe_load(f) or {}
    local_cfg.setdefault('ai', {})['provider'] = provider
    with open(local_path, 'w', encoding='utf-8') as f:
        yaml.dump(local_cfg, f, allow_unicode=True, default_flow_style=False)
    current_app.config['AI_PROVIDER'] = provider
    flash(f'AI 服务已切换为 {"OpenAI API" if provider == "openai" else "Ollama"}', 'success')
    return redirect(url_for('admin.ai_model_list'))


@admin_bp.route('/ai-models/set-openai', methods=['POST'])
@admin_required
def ai_set_openai():
    """Save OpenAI API configuration."""
    base_url = request.form.get('base_url', '').strip()
    api_key = request.form.get('api_key', '').strip()
    model = request.form.get('model', '').strip()
    local_path = os.path.join(current_app.root_path, '..', 'config.local.yml')
    local_cfg = {}
    if os.path.exists(local_path):
        with open(local_path, encoding='utf-8') as f:
            local_cfg = yaml.safe_load(f) or {}
    local_cfg['openai'] = {'base_url': base_url, 'api_key': api_key, 'model': model}
    with open(local_path, 'w', encoding='utf-8') as f:
        yaml.dump(local_cfg, f, allow_unicode=True, default_flow_style=False)
    current_app.config['OPENAI_BASE_URL'] = base_url
    current_app.config['OPENAI_API_KEY'] = api_key
    current_app.config['OPENAI_MODEL'] = model
    flash('OpenAI API 配置已保存', 'success')
    return redirect(url_for('admin.ai_model_list'))


@admin_bp.route('/ai-models/save-prompts', methods=['POST'])
@admin_required
def ai_model_save_prompts():
    """Save AI prompt overrides to prompts.yml."""
    prompts = {}
    for key in PROMPT_DEFAULTS:
        val = request.form.get(f'prompt_{key}', '').strip()
        if val:
            prompts[key] = val
    save_all_prompts(prompts)
    flash('AI 提示词已保存', 'success')
    return redirect(url_for('admin.ai_model_list'))
