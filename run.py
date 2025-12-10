from flask import Flask
import os
from project import create_app

app = create_app()

if __name__ == "__main__":
    debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(debug=debug_mode, host="0.0.0.0",
            port=int(os.environ.get("PORT", 5000)))
