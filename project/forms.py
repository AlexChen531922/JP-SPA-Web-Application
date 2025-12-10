from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, SelectField, EmailField
from wtforms.validators import DataRequired, Email, Length, EqualTo, Optional


class LoginForm(FlaskForm):
    """Login form"""
    username = StringField('帳號', validators=[DataRequired(message='請輸入帳號')])
    password = PasswordField('密碼', validators=[DataRequired(message='請輸入密碼')])
    submit = SubmitField('登入')


class RegisterForm(FlaskForm):
    """Registration form"""
    username = StringField('帳號', validators=[
        DataRequired(message='請輸入帳號'),
        Length(min=3, max=50, message='帳號長度需介於 3-50 個字元')
    ])
    email = EmailField('Email', validators=[
        DataRequired(message='請輸入 Email'),
        Email(message='Email 格式不正確')
    ])
    password = PasswordField('密碼', validators=[
        DataRequired(message='請輸入密碼'),
        Length(min=6, message='密碼至少需要 6 個字元')
    ])
    firstname = StringField('名字', validators=[
        DataRequired(message='請輸入名字')
    ])
    surname = StringField('姓氏', validators=[
        DataRequired(message='請輸入姓氏')
    ])

    line_id = StringField('LINE ID', validators=[Optional()])

    role = SelectField('註冊身份', choices=[
        ('customer', '一般會員'),
        ('staff', '員工')
    ], default='customer', validators=[DataRequired()])
    submit = SubmitField('註冊')


class ForgotPasswordForm(FlaskForm):
    """Forgot password form"""
    email = EmailField('Email', validators=[
        DataRequired(message='請輸入 Email'),
        Email(message='Email 格式不正確')
    ])
    submit = SubmitField('送出')


class ResetPasswordForm(FlaskForm):
    """Reset password form"""
    password = PasswordField('新密碼', validators=[
        DataRequired(message='請輸入新密碼'),
        Length(min=6, message='密碼至少需要 6 個字元')
    ])
    confirm_password = PasswordField('確認密碼', validators=[
        DataRequired(message='請確認密碼'),
        EqualTo('password', message='密碼不一致')
    ])
    submit = SubmitField('重設密碼')
