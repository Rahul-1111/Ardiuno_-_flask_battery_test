import sqlite3

# Connect (or create) the database
conn = sqlite3.connect('battery_monitor.db')
cursor = conn.cursor()

# Create table
cursor.execute('''
CREATE TABLE IF NOT EXISTS voltage_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    cell_name TEXT,
    voltage REAL,
    status TEXT
)
''')

conn.commit()
conn.close()

print("✅ Database and table created.")
