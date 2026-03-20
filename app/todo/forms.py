from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired, Length


class TodoForm(FlaskForm):
    title = StringField('任务名称', validators=[DataRequired(), Length(max=300)])
    submit = SubmitField('添加')
