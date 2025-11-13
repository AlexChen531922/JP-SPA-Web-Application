from flask_mysqldb import MySQL
from flask_wtf.csrf import CSRFProtect
from flask_bootstrap import Bootstrap5

database = MySQL()
csrf = CSRFProtect()  # Prevent unauthorized malicious requests
bootstrap = Bootstrap5()
