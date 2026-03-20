from flask import render_template, redirect, url_for, flash, request, session
from flask_login import current_user

from app.ai import ai_bp
from app.ai.forms import ParseTextForm, ParseDocxForm, ConfirmForm
from flask_login import login_required
from app.extensions import db
from app.models.project import Project
from app.models.requirement import Requirement, RequirementTask, Activity
from app.models.ai_log import AIParseLog
from app.services.ai import parse_requirement, refine_requirement, extract_text_from_docx

# Session keys in one place
_SK_PARSED = 'ai_parsed'
_SK_LOG_ID = 'ai_log_id'
_SK_ORIGINAL = 'ai_original_text'


def _save_parse_result(input_type, raw_input, result, raw_output):
    """Common logic after AI parse: log, save to session, redirect."""
    log = AIParseLog(input_type=input_type, raw_input=raw_input[:5000],
                     ai_output=raw_output, created_by=current_user.id)
    db.session.add(log)
    db.session.commit()

    if not result:
        flash('AI 解析失败，请检查 Ollama 服务是否正常或重试', 'danger')
        return redirect(url_for('ai.parse_page'))

    session[_SK_PARSED] = result
    session[_SK_LOG_ID] = log.id
    session[_SK_ORIGINAL] = raw_input[:5000]
    return redirect(url_for('ai.confirm'))


def _clear_session():
    for key in (_SK_PARSED, _SK_LOG_ID, _SK_ORIGINAL):
        session.pop(key, None)


@ai_bp.route('/', methods=['GET', 'POST'])
@login_required
def parse_page():
    text_form = ParseTextForm(prefix='text')
    docx_form = ParseDocxForm(prefix='docx')
    return render_template('ai/parse.html', text_form=text_form, docx_form=docx_form)


@ai_bp.route('/parse-text', methods=['POST'])
@login_required
def parse_text():
    form = ParseTextForm(prefix='text')
    if not form.validate_on_submit():
        flash('请输入需要解析的内容', 'danger')
        return redirect(url_for('ai.parse_page'))
    result, raw_output = parse_requirement(form.content.data)
    return _save_parse_result('chat_text', form.content.data, result, raw_output)


@ai_bp.route('/parse-docx', methods=['POST'])
@login_required
def parse_docx():
    form = ParseDocxForm(prefix='docx')
    if not form.validate_on_submit():
        flash('请选择 .docx 文件', 'danger')
        return redirect(url_for('ai.parse_page'))
    raw_text = extract_text_from_docx(form.file.data)
    if not raw_text.strip():
        flash('文档内容为空', 'danger')
        return redirect(url_for('ai.parse_page'))
    result, raw_output = parse_requirement(raw_text)
    return _save_parse_result('docx', raw_text, result, raw_output)


@ai_bp.route('/confirm', methods=['GET', 'POST'])
@login_required
def confirm():
    parsed = session.get(_SK_PARSED)
    if not parsed:
        flash('没有待确认的解析结果', 'warning')
        return redirect(url_for('ai.parse_page'))

    form = ConfirmForm()
    form.project_id.choices = [(p.id, p.name) for p in Project.query.filter_by(status='active').all()]

    if request.method == 'GET':
        form.title.data = parsed.get('title', '')
        form.description.data = parsed.get('description', '')
        form.priority.data = parsed.get('priority', 'medium')
        form.estimate_days.data = parsed.get('estimate_days')
        subtasks = parsed.get('subtasks', [])
        form.subtasks.data = '\n'.join(subtasks) if subtasks else ''

    if form.validate_on_submit():
        log = db.session.get(AIParseLog, session.get(_SK_LOG_ID))
        source = 'ai_docx' if (log and log.input_type == 'docx') else 'ai_chat'

        req = Requirement(
            number=Requirement.generate_number(),
            title=form.title.data,
            description=form.description.data,
            project_id=form.project_id.data,
            priority=form.priority.data,
            estimate_days=form.estimate_days.data,
            source=source,
            created_by=current_user.id,
        )
        db.session.add(req)
        db.session.flush()

        for line in (form.subtasks.data or '').strip().splitlines():
            line = line.strip()
            if line:
                db.session.add(RequirementTask(requirement_id=req.id, title=line))

        db.session.add(Activity(
            requirement_id=req.id, user_id=current_user.id,
            action='created', detail=f'通过 AI 解析创建需求「{req.title}」',
        ))
        db.session.commit()
        _clear_session()
        flash(f'需求 {req.number} 已保存', 'success')
        return redirect(url_for('requirement.requirement_detail', req_id=req.id))

    return render_template('ai/confirm.html', form=form, parsed=parsed,
                           has_original=bool(session.get(_SK_ORIGINAL)))


@ai_bp.route('/refine', methods=['POST'])
@login_required
def refine():
    feedback = request.form.get('feedback', '').strip()
    parsed = session.get(_SK_PARSED)
    original_text = session.get(_SK_ORIGINAL)

    if not feedback or not parsed or not original_text:
        flash('缺少反馈内容或原始数据', 'danger')
        return redirect(url_for('ai.confirm'))

    result, raw_output = refine_requirement(original_text, parsed, feedback)
    return _save_parse_result('refine', feedback, result, raw_output)


@ai_bp.route('/discard', methods=['POST'])
@login_required
def discard():
    _clear_session()
    flash('已丢弃本次解析结果', 'info')
    return redirect(url_for('ai.parse_page'))
