rmdir /s /q build dist
del app.spec
pyinstaller --onefile --add-data "templates;templates" --add-data "static;static" --add-data "battery_data.db;." app.py
