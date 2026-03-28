from flask_wtf import FlaskForm
from wtforms import DateField, FloatField, IntegerField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional

from app.models.requirement import Requirement


class RequirementForm(FlaskForm):
    title = StringField('需求标题', validators=[DataRequired(), Length(max=300)])
    description = TextAreaField('需求描述', validators=[Optional()])
    project_id = SelectField('所属项目', coerce=int, validators=[DataRequired()])
    priority = SelectField('优先级',
                           choices=list(Requirement.PRIORITY_LABELS.items()),
                           default='medium')
    source = SelectField('需求类型',
                         choices=list(Requirement.SOURCE_LABELS.items()),
                         default='coding', validators=[DataRequired(message='请选择需求类型')])
    category = StringField('需求分类', validators=[Optional(), Length(max=100)])
    assignee_id = SelectField('负责人', coerce=int, validators=[Optional()])
    start_date = DateField('启动时间', validators=[Optional()])
    due_date = DateField('预期完成时间', validators=[DataRequired(message='请选择预期完成时间')])
    estimate_days = FloatField('预估工期（人天）', validators=[Optional()])
    code_lines = IntegerField('代码量（行）', validators=[Optional()])
    test_cases = IntegerField('测试用例数', validators=[Optional()])
    ai_ratio = IntegerField('AI辅助占比(%)', validators=[Optional()])
    submit = SubmitField('保存')


class CommentForm(FlaskForm):
    content = TextAreaField('评论内容', validators=[DataRequired(message='请输入评论内容')])
    submit = SubmitField('发表评论')
