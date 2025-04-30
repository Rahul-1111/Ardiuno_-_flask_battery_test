from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO
import sqlite3
import serial
import time
import threading
import re
from datetime import datetime

app = Flask(__name__)
socketio = SocketIO(app)

SERIAL_PORT = "COM3"
BAUD_RATE = 115200
serial_connection = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)

DB_FILE = "battery_data.db"

# --- Database Setup ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS battery_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            cell TEXT,
            voltage REAL,
            status TEXT
        )
    ''')
    conn.commit()
    conn.close()

# --- Serial Reading Thread ---
def read_from_arduino():
    voltage_pattern = re.compile(r'([A-P] CELL) Voltage: ([\-0-9.]+) V')
    status_pattern = re.compile(r'([A-P] CELL) (Undervoltage|Overvoltage)')

    cell_statuses = {}

    while True:
        try:
            if serial_connection.in_waiting > 0:
                line = serial_connection.readline().decode('utf-8', errors='ignore').strip()
                print("Received:", line)

                voltage_match = voltage_pattern.search(line)
                status_match = status_pattern.search(line)

                if voltage_match:
                    cell = voltage_match.group(1)
                    voltage = float(voltage_match.group(2))
                    timestamp = datetime.now().isoformat()

                    # Emit to frontend
                    socketio.emit('cell_voltage', {'cell': cell, 'voltage': voltage})

                    # Save to DB
                    save_to_db(cell, voltage, cell_statuses.get(cell, "OK"), timestamp)

                    # Emit default OK status if no warning
                    if cell_statuses.get(cell) != "OK":
                        socketio.emit('cell_status', {'cell': cell, 'status': 'OK'})
                        cell_statuses[cell] = "OK"

                if status_match:
                    cell = status_match.group(1)
                    status = status_match.group(2)
                    timestamp = datetime.now().isoformat()

                    # Emit status
                    socketio.emit('cell_status', {'cell': cell, 'status': status})
                    cell_statuses[cell] = status

                    # Save latest status to DB (even without voltage update)
                    save_to_db(cell, None, status, timestamp)
        except Exception as e:
            print("Error in serial thread:", e)

        time.sleep(0.01)

def save_to_db(cell, voltage, status, timestamp):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        INSERT INTO battery_logs (timestamp, cell, voltage, status)
        VALUES (?, ?, ?, ?)
    ''', (timestamp, cell, voltage, status))
    conn.commit()
    conn.close()

# --- Routes ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/set_thresholds', methods=['POST'])
def set_thresholds():
    data = request.get_json()

    ordered_cells = [
        "A_CELL", "B_CELL", "C_CELL", "D_CELL",
        "E_CELL", "F_CELL", "G_CELL", "H_CELL",
        "I_CELL", "J_CELL", "K_CELL", "L_CELL",
        "M_CELL", "N_CELL", "O_CELL", "P_CELL"
    ]

    csv_parts = []
    for cell in ordered_cells:
        min_v = data.get(f"{cell}_min", "0.000")
        max_v = data.get(f"{cell}_max", "0.000")
        csv_parts.append(str(min_v))
        csv_parts.append(str(max_v))

    csv_string = ",".join(csv_parts) + "\n"
    serial_connection.write(csv_string.encode())
    return jsonify({"message": "Thresholds sent"}), 200

# --- Thread Start ---
def start_serial_thread():
    thread = threading.Thread(target=read_from_arduino)
    thread.daemon = True
    thread.start()

# --- Main ---
if __name__ == '__main__':
    init_db()
    start_serial_thread()
    socketio.run(app, host='0.0.0.0', port=5001)
