from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SelectField, FloatField, SubmitField
from wtforms.validators import DataRequired, Length, Optional


class RequirementForm(FlaskForm):
    title = StringField('需求标题', validators=[DataRequired(), Length(max=300)])
    description = TextAreaField('需求描述', validators=[Optional()])
    project_id = SelectField('所属项目', coerce=int, validators=[DataRequired()])
    milestone_id = SelectField('里程碑', coerce=int, validators=[Optional()])
    priority = SelectField('优先级', choices=[
        ('high', '高'), ('medium', '中'), ('low', '低'),
    ], default='medium')
    assignee_id = SelectField('负责人', coerce=int, validators=[Optional()])
    estimate_days = FloatField('预估工期（人天）', validators=[Optional()])
    submit = SubmitField('保存')


class CommentForm(FlaskForm):
    content = TextAreaField('评论内容', validators=[DataRequired(message='请输入评论内容')])
    submit = SubmitField('发表评论')


class TaskForm(FlaskForm):
    title = StringField('子任务名称', validators=[DataRequired(), Length(max=300)])
    submit = SubmitField('添加')
