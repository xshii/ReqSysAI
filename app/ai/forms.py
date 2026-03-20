from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import TextAreaField, SelectField, StringField, FloatField, SubmitField
from wtforms.validators import DataRequired, Optional, Length


class ParseTextForm(FlaskForm):
    content = TextAreaField('聊天记录或需求文本', validators=[DataRequired(message='请输入内容')])
    submit = SubmitField('AI 解析')


class ParseDocxForm(FlaskForm):
    file = FileField('Word 文档', validators=[
        DataRequired(message='请选择文件'),
        FileAllowed(['docx'], '只支持 .docx 文件'),
    ])
    submit = SubmitField('上传并解析')


class ConfirmForm(FlaskForm):
    """Confirm AI-parsed result, allow editing before saving."""
    title = StringField('需求标题', validators=[DataRequired(), Length(max=300)])
    description = TextAreaField('需求描述', validators=[Optional()])
    project_id = SelectField('所属项目', coerce=int, validators=[DataRequired()])
    priority = SelectField('优先级', choices=[
        ('high', '高'), ('medium', '中'), ('low', '低'),
    ])
    estimate_days = FloatField('预估工期（人天）', validators=[Optional()])
    subtasks = TextAreaField('子任务（每行一个）', validators=[Optional()])
    submit = SubmitField('确认保存')
