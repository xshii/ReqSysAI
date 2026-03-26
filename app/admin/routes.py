import csv
import io
import logging
import os

import requests
import yaml
from flask import Response, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user

logger = logging.getLogger(__name__)

from datetime import date, datetime, timezone

from app.admin import admin_bp
from app.admin.forms import UserCreateForm, UserEditForm
from app.decorators import admin_required
from app.extensions import db
from app.models.ip_request import IPChangeRequest
from app.models.user import Group, Role, User
from app.services.ai import check_ollama_status
from app.services.prompts import LABELS as PROMPT_LABELS
from app.services.prompts import get_all_prompts, save_all_prompts
from app.utils.pinyin import to_pinyin


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

    all_group_objs = Group.query.order_by(Group.name).all()
    all_groups = [g.name for g in all_group_objs]
    group_counts = {}
    for g in all_groups:
        group_counts[g] = User.query.filter_by(group=g, is_active=True).count()

    hidden = set(current_app.config.get('HIDDEN_ROLES', []) + ['Admin'])
    visible_roles = [r for r in Role.query.order_by(Role.id).all() if r.name not in hidden]

    ip_requests = IPChangeRequest.query.filter_by(status='pending')\
        .order_by(IPChangeRequest.created_at.desc()).all()

    DEFAULT_DOMAINS = ['芯片验证', '业务开发', '技术开发', '编译器', '算法', '芯片', '产品', '功能仿真', '性能仿真', '产品测试']
    db_domains = set(u.domain for u in User.query.filter(User.domain.isnot(None), User.domain != '').all())
    all_domains = sorted(db_domains | set(DEFAULT_DOMAINS))
    return render_template('admin/users.html', users=users, visible_roles=visible_roles,
                           all_groups=all_groups, all_group_objs=all_group_objs,
                           group_counts=group_counts, all_domains=all_domains,
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
        user.ip_address = form.ip_address.data or f'pending-{user.employee_id}'
        user.group = form.group.data or None
        user.manager = form.manager.data.strip() or None
        user.domain = form.domain.data or None
        user.roles = Role.query.filter(Role.id.in_(form.role_ids.data)).all()
        user.is_active = form.is_active.data
        db.session.commit()
        flash(f'用户 {user.name} 更新成功', 'success')
        return redirect(url_for('admin.user_list'))

    return render_template('admin/user_form.html', form=form, title=f'编辑用户 - {user.name}', user=user)


@admin_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@admin_required
def user_delete(user_id):
    user = db.get_or_404(User, user_id)
    if user.is_admin:
        flash('不能删除管理员', 'danger')
        return redirect(url_for('admin.user_list'))
    name = user.name
    from app.services.audit import log_audit
    log_audit('delete', 'user', user.id, name, f'删除用户 {name} ({user.employee_id})')
    db.session.delete(user)
    db.session.commit()
    flash(f'用户 {name} 已删除', 'success')
    return redirect(url_for('admin.user_list'))


@admin_bp.route('/ip-request/<int:req_id>/approve', methods=['POST'])
@admin_required
def ip_request_approve(req_id):
    r = db.get_or_404(IPChangeRequest, req_id)
    r.status = 'approved'
    r.reviewed_by = current_user.id
    r.reviewed_at = datetime.now(timezone.utc)
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
    r.reviewed_at = datetime.now(timezone.utc)
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
    created, updated, skipped = 0, 0, 0
    new_groups = set()
    errors = []

    for i, row in enumerate(reader, start=2):
        uid = (row.get('ID') or '').strip() if has_id else ''
        if uid == '0':
            continue  # Skip demo row
        name = (row.get('姓名') or '').strip()
        eid = (row.get('工号') or '').strip().lower()
        group = (row.get('小组') or '').strip() or None
        role_str = (row.get('角色') or '').strip()
        manager_raw = (row.get('主管') or '').strip()
        # Validate manager format: "姓名 工号" or empty
        import re as _re
        if manager_raw and not _re.match(r'^.+\s[a-z]\d?00\d{6}$', manager_raw):
            errors.append(f'第{i}行({eid})：主管格式错误「{manager_raw}」，应为「姓名 工号」，已忽略')
            manager_raw = None
        manager = manager_raw or None
        domain = (row.get('业务领域') or '').strip() or None

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
            if manager:
                user.manager = manager
            if domain:
                user.domain = domain
            if roles:
                user.roles = roles
            # If no roles in CSV, keep existing roles unchanged
            updated += 1
        else:
            user = User(
                employee_id=eid, name=name, pinyin=to_pinyin(name),
                ip_address=f'pending-{eid}', group=group, roles=roles,
                manager=manager, domain=domain,
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


@admin_bp.route('/users/<int:user_id>/domain', methods=['POST'])
@admin_required
def user_update_domain(user_id):
    """Inline domain change from user table."""
    user = db.get_or_404(User, user_id)
    user.domain = request.form.get('domain', '').strip() or None
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
    elif action == 'toggle_hidden':
        name = request.form.get('group_name', '').strip()
        g = Group.query.filter_by(name=name).first()
        if g:
            g.is_hidden = not g.is_hidden
            db.session.commit()
            flash(f'团队 {name} 已{"隐藏" if g.is_hidden else "显示"}', 'success')
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
    writer.writerow(['ID', '姓名', '工号', '小组', '角色', '主管', '业务领域'])
    writer.writerow([0, '张三', 'a00123456', '研发一组(选填)', 'DE;TE(选填)', '李四 b00234567(选填)', '支付(选填) 此行为格式示例，导入时自动跳过'])
    for u in users:
        role_names = ';'.join(r.name for r in u.roles if r.name not in hidden)
        writer.writerow([u.id, u.name, u.employee_id, u.group or '', role_names, u.manager or '', u.domain or ''])

    from urllib.parse import quote
    from app.constants import DEFAULT_SITE_NAME
    site = current_app.config.get('SITE_NAME', DEFAULT_SITE_NAME)
    fname = f"{site}_团队成员_{date.today().strftime('%Y%m%d')}.csv"
    return Response(
        buf.getvalue(),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f"attachment; filename*=UTF-8''{quote(fname)}"},
    )


# ---- Milestone templates ----


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
    ai_provider = current_app.config.get('AI_PROVIDER', 'ollama')
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
                'provider': 'ollama',
            })
    # Also fetch OpenAI models
    openai_url = current_app.config.get('OPENAI_BASE_URL', '').rstrip('/')
    openai_key = current_app.config.get('OPENAI_API_KEY', '')
    openai_models = []
    openai_err = None
    if openai_url:
        try:
            headers = {'Authorization': f'Bearer {openai_key}'} if openai_key else {}
            resp = requests.get(f'{openai_url}/models', headers=headers, timeout=10)
            resp.raise_for_status()
            for m in resp.json().get('data', []):
                openai_models.append({
                    'name': m.get('id', m.get('name', '?')),
                    'size': '-',
                    'modified': '',
                    'family': m.get('owned_by', ''),
                    'params': '',
                    'provider': 'openai',
                })
        except Exception as e:
            openai_err = str(e)[:100]
    current_model = current_app.config.get('OLLAMA_MODEL', '') if ai_provider == 'ollama' else current_app.config.get('OPENAI_MODEL', '')

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

    return render_template('admin/ai_models.html',
                           models=models, err=err, current_model=current_model,
                           openai_models=openai_models, openai_err=openai_err,
                           default_prompt=default_prompt,
                           prompts=prompts, prompt_labels=PROMPT_LABELS,
                           ai_provider=ai_provider,
                           ollama_base_url=current_app.config.get('OLLAMA_BASE_URL', ''),
                           ollama_ssh_enabled=current_app.config.get('OLLAMA_SSH_ENABLED', False),
                           ollama_ssh_host=current_app.config.get('OLLAMA_SSH_HOST', ''),
                           ollama_ssh_local_port=current_app.config.get('OLLAMA_SSH_LOCAL_PORT', 11434),
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
    """Switch AI provider (ollama/openai) and enable/disable."""
    provider = request.form.get('provider', 'ollama')
    ai_enabled = request.form.get('ai_enabled') == '1'
    local_path = os.path.join(current_app.root_path, '..', 'config.local.yml')
    local_cfg = {}
    if os.path.exists(local_path):
        with open(local_path, encoding='utf-8') as f:
            local_cfg = yaml.safe_load(f) or {}
    ai_cfg = local_cfg.setdefault('ai', {})
    ai_cfg['provider'] = provider
    ai_cfg['enabled'] = ai_enabled
    with open(local_path, 'w', encoding='utf-8') as f:
        yaml.dump(local_cfg, f, allow_unicode=True, default_flow_style=False)
    current_app.config['AI_PROVIDER'] = provider
    current_app.config['AI_ENABLED'] = ai_enabled
    if ai_enabled:
        flash(f'AI 服务已开启（{provider}）', 'success')
    else:
        flash('AI 服务已关闭', 'warning')
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


@admin_bp.route('/ai-prompts')
@admin_required
def ai_prompt_list():
    prompts = get_all_prompts()
    return render_template('admin/ai_prompts.html',
                           prompts=prompts, prompt_labels=PROMPT_LABELS,
                           prompt_defaults={})


@admin_bp.route('/ai-models/save-prompts', methods=['POST'])
@admin_required
def ai_model_save_prompts():
    """Save AI prompt overrides to prompts.yml."""
    prompts = {}
    for key in PROMPT_LABELS:
        val = request.form.get(f'prompt_{key}', '').strip()
        if val:
            prompts[key] = val
    save_all_prompts(prompts)
    flash('AI 提示词已保存', 'success')
    return redirect(url_for('admin.ai_prompt_list'))


@admin_bp.route('/ai-models/set-ollama', methods=['POST'])
@admin_required
def ai_set_ollama():
    """Save Ollama connection config (SSH tunnel settings)."""
    base_url = request.form.get('base_url', '').strip()
    ssh_enabled = request.form.get('ssh_enabled') == '1'
    ssh_host = request.form.get('ssh_host', '').strip()
    ssh_local_port = request.form.get('ssh_local_port', 11434, type=int)

    local_path = os.path.join(current_app.root_path, '..', 'config.local.yml')
    local_cfg = {}
    if os.path.exists(local_path):
        with open(local_path, encoding='utf-8') as f:
            local_cfg = yaml.safe_load(f) or {}
    ollama_cfg = local_cfg.setdefault('ollama', {})
    if base_url:
        ollama_cfg['base_url'] = base_url
    ollama_cfg['ssh_enabled'] = ssh_enabled
    ollama_cfg['ssh_host'] = ssh_host
    ollama_cfg['ssh_local_port'] = ssh_local_port
    with open(local_path, 'w', encoding='utf-8') as f:
        yaml.dump(local_cfg, f, allow_unicode=True, default_flow_style=False)

    current_app.config['OLLAMA_BASE_URL'] = base_url or current_app.config['OLLAMA_BASE_URL']
    current_app.config['OLLAMA_SSH_ENABLED'] = ssh_enabled
    current_app.config['OLLAMA_SSH_HOST'] = ssh_host
    current_app.config['OLLAMA_SSH_LOCAL_PORT'] = ssh_local_port
    flash('Ollama 连接配置已保存', 'success')
    return redirect(url_for('admin.ai_model_list'))


@admin_bp.route('/ai-models/set-system-prompt', methods=['POST'])
@admin_required
def ai_set_system_prompt():
    """Save global AI system prompt."""
    prompt = request.form.get('system_prompt', '').strip()
    local_path = os.path.join(current_app.root_path, '..', 'config.local.yml')
    local_cfg = {}
    if os.path.exists(local_path):
        with open(local_path, encoding='utf-8') as f:
            local_cfg = yaml.safe_load(f) or {}
    local_cfg.setdefault('ai', {})['system_prompt'] = prompt
    with open(local_path, 'w', encoding='utf-8') as f:
        yaml.dump(local_cfg, f, allow_unicode=True, default_flow_style=False)
    current_app.config['AI_SYSTEM_PROMPT'] = prompt
    flash('系统提示词已保存', 'success')
    return redirect(url_for('admin.ai_model_list'))


@admin_bp.route('/ai-models/test', methods=['POST'])
@admin_required
def ai_test():
    """One-click test for current AI provider."""
    from app.services.ai import call_ollama
    test_prompt = '请用一句话回答：1+1等于几？'
    try:
        result, raw = call_ollama(test_prompt)
        if raw:
            return jsonify(ok=True, response=raw[:200])
        else:
            return jsonify(ok=False, error='AI 返回为空')
    except Exception as e:
        return jsonify(ok=False, error=str(e)[:200])


@admin_bp.route('/ai-models/test-all', methods=['POST'])
@admin_required
def ai_test_all():
    """Fetch all available models from Ollama + OpenAI and test each."""
    import time
    results = []

    # 1. Ollama models
    ollama_url = current_app.config.get('OLLAMA_BASE_URL', '').rstrip('/')
    if ollama_url:
        try:
            resp = requests.get(f'{ollama_url}/api/tags', timeout=10,
                                proxies={'http': '', 'https': ''})
            resp.raise_for_status()
            for m in resp.json().get('models', []):
                name = m['name']
                size_gb = m.get('size', 0) / 1e9
                size_str = f'{size_gb:.1f}GB' if size_gb >= 1 else f'{m.get("size", 0) / 1e6:.0f}MB'
                # Quick test
                t0 = time.time()
                try:
                    r = requests.post(f'{ollama_url}/api/chat', timeout=30,
                                      proxies={'http': '', 'https': ''},
                                      json={'model': name, 'messages': [{'role': 'user', 'content': 'hi'}], 'stream': False})
                    r.raise_for_status()
                    reply = r.json().get('message', {}).get('content', '')[:50]
                    elapsed = round(time.time() - t0, 1)
                    results.append({'provider': 'Ollama', 'model': name, 'size': size_str,
                                    'status': 'ok', 'reply': reply, 'time': f'{elapsed}s'})
                except Exception as e:
                    results.append({'provider': 'Ollama', 'model': name, 'size': size_str,
                                    'status': 'fail', 'reply': str(e)[:80], 'time': '-'})
        except Exception as e:
            results.append({'provider': 'Ollama', 'model': '-', 'size': '-',
                            'status': 'fail', 'reply': f'连接失败: {e}', 'time': '-'})

    # 2. OpenAI compatible models
    openai_url = current_app.config.get('OPENAI_BASE_URL', '').rstrip('/')
    openai_key = current_app.config.get('OPENAI_API_KEY', '')
    if openai_url:
        try:
            headers = {'Authorization': f'Bearer {openai_key}'} if openai_key else {}
            resp = requests.get(f'{openai_url}/models', headers=headers, timeout=10)
            resp.raise_for_status()
            models = resp.json().get('data', [])
            for m in models:
                mid = m.get('id', m.get('name', '?'))
                t0 = time.time()
                try:
                    r = requests.post(f'{openai_url}/chat/completions', headers=headers, timeout=30,
                                      json={'model': mid, 'messages': [{'role': 'user', 'content': 'hi'}], 'temperature': 0.1})
                    r.raise_for_status()
                    reply = r.json()['choices'][0]['message']['content'][:50]
                    elapsed = round(time.time() - t0, 1)
                    results.append({'provider': 'OpenAI', 'model': mid, 'size': '-',
                                    'status': 'ok', 'reply': reply, 'time': f'{elapsed}s'})
                except Exception as e:
                    results.append({'provider': 'OpenAI', 'model': mid, 'size': '-',
                                    'status': 'fail', 'reply': str(e)[:80], 'time': '-'})
        except Exception as e:
            results.append({'provider': 'OpenAI', 'model': '-', 'size': '-',
                            'status': 'fail', 'reply': f'连接失败: {e}', 'time': '-'})

    return jsonify(ok=True, results=results)


@admin_bp.route('/ai-models/test-one', methods=['POST'])
@admin_required
def ai_test_one():
    """Test a single model by provider and name."""
    import time
    data = request.get_json(silent=True) or {}
    provider = data.get('provider', 'ollama')
    model_name = data.get('model', '')
    if not model_name:
        return jsonify(ok=False, error='缺少模型名')

    t0 = time.time()
    try:
        if provider == 'ollama':
            url = current_app.config.get('OLLAMA_BASE_URL', '').rstrip('/')
            if not url:
                return jsonify(ok=False, error='Ollama 未配置 API 地址')
            r = requests.post(f'{url}/api/chat', timeout=30,
                              proxies={'http': '', 'https': ''},
                              json={'model': model_name, 'messages': [{'role': 'user', 'content': 'hi'}], 'stream': False})
            r.raise_for_status()
            reply = r.json().get('message', {}).get('content', '')[:100]
        else:
            url = current_app.config.get('OPENAI_BASE_URL', '').rstrip('/')
            if not url:
                return jsonify(ok=False, error='OpenAI 未配置 API 地址')
            key = current_app.config.get('OPENAI_API_KEY', '')
            headers = {'Authorization': f'Bearer {key}'} if key else {}
            r = requests.post(f'{url}/chat/completions', headers=headers, timeout=30,
                              json={'model': model_name, 'messages': [{'role': 'user', 'content': 'hi'}], 'temperature': 0.1})
            r.raise_for_status()
            reply = r.json()['choices'][0]['message']['content'][:100]
        elapsed = round(time.time() - t0, 1)
        return jsonify(ok=True, reply=reply, time=f'{elapsed}s')
    except Exception as e:
        return jsonify(ok=False, error=str(e)[:200])


@admin_bp.route('/site-settings')
@admin_required
def site_settings():
    from app.constants import DEFAULT_SITE_NAME
    from app.models.site_setting import SiteSetting
    site_name = SiteSetting.get('site_name', current_app.config.get('SITE_NAME', DEFAULT_SITE_NAME))
    exc_cfg = current_app.config.get('EXCHANGE_CONFIG', {})
    return render_template('admin/site_settings.html',
                           current_site_name=site_name,
                           exchange_server=SiteSetting.get('exchange_server', exc_cfg.get('server', '')),
                           exchange_domain=SiteSetting.get('exchange_domain', exc_cfg.get('domain', '')),
                           mail_domain=SiteSetting.get('mail_domain', current_app.config.get('MAIL_DOMAIN', 'company.com')))


@admin_bp.route('/site-settings/save', methods=['POST'])
@admin_required
def site_settings_save():
    from app.models.site_setting import SiteSetting
    new_name = request.form.get('site_name', '').strip()
    if not new_name:
        flash('站点名称不能为空', 'danger')
        return redirect(url_for('admin.site_settings'))
    SiteSetting.set('site_name', new_name)
    current_app.config['SITE_NAME'] = new_name
    flash('站点名称已更新', 'success')
    return redirect(url_for('admin.site_settings'))


@admin_bp.route('/site-settings/exchange', methods=['POST'])
@admin_required
def exchange_settings_save():
    from app.models.site_setting import SiteSetting
    server = request.form.get('exchange_server', '').strip()
    domain = request.form.get('exchange_domain', '').strip()
    mail = request.form.get('mail_domain', '').strip()
    SiteSetting.set('exchange_server', server)
    SiteSetting.set('exchange_domain', domain)
    SiteSetting.set('mail_domain', mail or 'company.com')
    # Update runtime config
    current_app.config['EXCHANGE_CONFIG'] = {'server': server, 'domain': domain}
    current_app.config['MAIL_DOMAIN'] = mail or 'company.com'
    flash('Exchange 配置已保存' + ('（已启用）' if server else '（已禁用）'), 'success')
    return redirect(url_for('admin.site_settings'))


@admin_bp.route('/audit-logs')
@admin_required
def audit_logs():
    from app.models.audit import AuditLog
    page = request.args.get('page', 1, type=int)
    entity_type = request.args.get('type', '')
    action = request.args.get('action', '')
    q = AuditLog.query
    if entity_type:
        q = q.filter_by(entity_type=entity_type)
    if action:
        q = q.filter_by(action=action)
    pagination = q.order_by(AuditLog.created_at.desc()).paginate(page=page, per_page=50, error_out=False)
    return render_template('admin/audit_logs.html', pagination=pagination, logs=pagination.items,
                           cur_type=entity_type, cur_action=action)
