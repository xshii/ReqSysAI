from flask_wtf import FlaskForm
from wtforms import DateField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional


class ProjectForm(FlaskForm):
    name = StringField('项目名称', validators=[DataRequired(), Length(max=200)])
    parent_id = SelectField('父项目', coerce=int, validators=[Optional()])
    description = TextAreaField('项目目标', validators=[Optional()])
    submit = SubmitField('保存')


class MilestoneForm(FlaskForm):
    name = StringField('里程碑名称', validators=[DataRequired(), Length(max=200)])
    due_date = DateField('截止日期', validators=[Optional()])
    submit = SubmitField('保存')
