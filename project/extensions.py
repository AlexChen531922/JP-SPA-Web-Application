from flask_mysqldb import MySQL
from flask_wtf.csrf import CSRFProtect
from flask_bootstrap import Bootstrap5
from flask_mail import Mail

database = MySQL()
mail = Mail()
csrf = CSRFProtect()  # Prevent unauthorized malicious requests
bootstrap = Bootstrap5()
