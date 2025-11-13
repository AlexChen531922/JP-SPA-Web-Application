from decimal import Decimal
from flask_wtf import FlaskForm
from wtforms import SelectMultipleField, widgets
from wtforms.validators import DataRequired, Length, Optional, NumberRange, InputRequired, Email
from flask_wtf.file import FileField, FileRequired, FileAllowed
from wtforms.validators import InputRequired, DataRequired, Length, Regexp,Email, Optional, NumberRange
from wtforms.fields import SubmitField, StringField, PasswordField, SelectField, TextAreaField, DecimalField, BooleanField

def _stripper(v): return v.strip() if isinstance(v, str) else v

ALLOWED = ['jpg', 'jpeg', 'png', 'webp', 'gif']

resolutions = [
    ('6000x4000', '6000x4000'),
    ('4096x2731', '4096x2731'),
    ('4000x2667', '4000x2667'),
    ('3840x2160', '3840x2160'),
    ('2048x2048', '2048x2048'),
]

class MultiCheckboxField(SelectMultipleField):
    widget = widgets.ListWidget(prefix_label=False)
    option_widget = widgets.CheckboxInput()

class AddItemForm(FlaskForm):
    title = StringField("Title", validators=[InputRequired()])
    description = TextAreaField(
        "Description", validators=[InputRequired()])
    resolution = SelectField('Resolution', choices=[
        ('6000x4000', '6000x4000'), ('4096x2731',
                                     '4096x2731'), ('4000x2667', '4000x2667'),
        ('3840x2160', '3840x2160'), ('2048x2048', '2048x2048')], validators=[DataRequired()])
    format = SelectField('Format', choices=[
        ('jpg', 'JPG'), ('png', 'PNG'), ('webp', 'WEBP')], validators=[DataRequired()])
    price = DecimalField('Price', places=2, default=Decimal("5.99"), validators=[
                         InputRequired(), NumberRange(min=0)])
    image = FileField('Image', validators=[
        FileRequired(message="Image file is required."),
        FileAllowed(['jpg', 'jpeg', 'png'], 'Only image files are allowed!')
    ])
    event_id = SelectField("Event", coerce=int, validators=[DataRequired()])
    category_ids = MultiCheckboxField(
        'Categories',
        coerce=int,
        validators=[Length(min=1, message='Please select at least one category.')]
    )
    license_id = SelectField('License', coerce=int, validators=[InputRequired()])
    resolution = SelectField(
        'Resolution', choices=resolutions, validators=[InputRequired()])
    format = SelectField('Format', choices=[
        ('jpg', 'JPG'), ('png', 'PNG'), ('webp', 'WEBP')], validators=[InputRequired()])
    price = DecimalField('Price', places=2, default=Decimal('0.00'), validators=[
                            InputRequired(), NumberRange(min=0)])
    submit = SubmitField("Submit")

class LoginForm(FlaskForm):
    """Form for user login."""
    username = StringField("Username", validators=[InputRequired()])
    password = PasswordField("Password", validators=[InputRequired()])
    submit = SubmitField("Login")


class RegisterForm(FlaskForm):
    """Form for user registry."""
    username = StringField("Username", validators=[InputRequired()])
    password = PasswordField("Password", validators=[InputRequired()])
    email = StringField("Email", validators=[InputRequired(), Email()])
    firstname = StringField("Your first name", validators=[InputRequired()])
    surname = StringField("Your surname", validators=[InputRequired()])
    role = SelectField("Role", choices=[
                       ('customer', 'Customer'), ('vendor', 'Vendor')], validators=[InputRequired()])
    submit = SubmitField("Make Account")


class VendorUploadFormDB(FlaskForm):
    title = StringField(
        'Title',
        filters=[_stripper],
        validators=[DataRequired(
            message="Title is required."), Length(max=255)]
    )
    description = TextAreaField('Description', filters=[
                                _stripper], validators=[Optional()])
    event_id = SelectField('Event', coerce=int, validators=[InputRequired(), NumberRange(min=1)])
    category_ids = MultiCheckboxField(
        'Categories',
        coerce=int,
        validators=[Length(min=1, message='Please select at least one category.')]
    )
    license_id = SelectField('License', coerce=int, validators=[InputRequired()])
    resolution = SelectField(
        'Resolution', choices=resolutions, validators=[InputRequired()])
    format = SelectField('Format', choices=[
        ('jpg', 'JPG'), ('png', 'PNG'), ('webp', 'WEBP')], validators=[InputRequired()])
    price = DecimalField('Price', places=2, default=Decimal('0.00'), validators=[
                         InputRequired(), NumberRange(min=0)])
    image = FileField(
        'Image',
        validators=[
            FileRequired(message="Image file is required."),
            FileAllowed(
                ALLOWED, "Only images are allowed (jpg, jpeg, png, webp, gif).")
        ]
    )
    submit = SubmitField('Upload Image')


class VendorEditFormDB(FlaskForm):
    title = StringField('Title', filters=[_stripper], validators=[
                        InputRequired(), Length(max=255)])
    description = TextAreaField('Description', validators=[Optional()])
    event_id = SelectField('Event', coerce=int, validators=[Optional()])
    category_ids = MultiCheckboxField(
        'Categories',
        coerce=int,
        validators=[Length(min=1, message='Please select at least one category.')]
    )
    license_id = SelectField('License', coerce=int, validators=[Optional()])
    resolution = SelectField(
        'Resolution', choices=resolutions, validators=[Optional()])
    format = SelectField('Format', choices=[
        ('jpg', 'JPG'), ('png', 'PNG'), ('webp', 'WEBP')], validators=[Optional()])
    price = DecimalField('Price', places=2, validators=[
                         Optional(), NumberRange(min=0)])
    image = FileField('Image', validators=[
                      Optional(), FileAllowed(ALLOWED, 'Images only!')])
    submit = SubmitField('Save changes')

class CheckoutForm(FlaskForm):
    """Form for user checkout."""
    username = StringField("Name (ex: emilychung)", validators = [DataRequired(message="Please enter your full name"),
            Length(min=1, max=50)])
    email = StringField("Email (ex:emily1234@gmail.com)", validators = [DataRequired(message="Please enter your email"),
            Email(message="Invalid email format")])

    accountname = StringField("Account name (same as credit card)", validators = [DataRequired(message="Please enter your account name"),Length(min=2, max=50)])
    cardnumber = StringField("Card number (ex: xxxxxxxxxxxxxxxx, 16 digits)", validators = [DataRequired(message="Invalid card number"),Length(min=16,max=16)])
    expiry = StringField("Expiry (ex: MM/YY, YY >=25)", validators = [DataRequired(), Regexp(r"^(0[1-9]|1[0-2])\/(2[5-9]|3[0-9])$", message="Invalid expiry date")])
    cvc = StringField("CVC (ex:123)", validators = [DataRequired(), Length(min=3,max=3, message="Invalid CVC")])
    agreeterm = BooleanField("Agree terms and License" , validators = [DataRequired(message="You must agree before proceeding")])
    submit = SubmitField("Complete payment")