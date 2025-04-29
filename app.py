from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO
import serial
import time
import threading
import re
import sqlite3
from datetime import datetime

app = Flask(__name__)
socketio = SocketIO(app)

# Serial Setup
SERIAL_PORT = "COM3"  # Change if needed
BAUD_RATE = 115200
serial_connection = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)

# Database
DB_NAME = "battery_data.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS battery_log (
            timestamp TEXT,
            shift TEXT,
            battery_qr TEXT,
            A_CELL REAL, B_CELL REAL, C_CELL REAL, D_CELL REAL,
            E_CELL REAL, F_CELL REAL, G_CELL REAL, H_CELL REAL,
            I_CELL REAL, J_CELL REAL, K_CELL REAL, L_CELL REAL,
            M_CELL REAL, N_CELL REAL, O_CELL REAL, P_CELL REAL
        )
    ''')
    conn.commit()
    conn.close()

# 📍 Shift logic
def get_current_shift():
    now = datetime.now().time()
    if now >= datetime.strptime('06:00:00', '%H:%M:%S').time() and now < datetime.strptime('14:00:00', '%H:%M:%S').time():
        return 'Shift 1'  # Morning Shift
    elif now >= datetime.strptime('14:00:00', '%H:%M:%S').time() and now < datetime.strptime('22:00:00', '%H:%M:%S').time():
        return 'Shift 2'  # Afternoon Shift
    else:
        return 'Shift 3'  # Night Shift

def save_full_cell_data(shift, battery_qr, voltages):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    c.execute('''
        INSERT INTO battery_log (
            timestamp, shift, battery_qr,
            A_CELL, B_CELL, C_CELL, D_CELL,
            E_CELL, F_CELL, G_CELL, H_CELL,
            I_CELL, J_CELL, K_CELL, L_CELL,
            M_CELL, N_CELL, O_CELL, P_CELL
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', [timestamp, shift, battery_qr] + voltages)
    conn.commit()
    conn.close()

# 🔄 Serial reader
def read_from_arduino():
    voltage_pattern = re.compile(r'([A-P] CELL) Voltage: ([\-0-9.]+) V')
    status_pattern = re.compile(r'([A-P] CELL) (Undervoltage|Overvoltage)')

    cell_statuses = {}
    cell_voltages = {}
    expected_cells = [f"{chr(c)} CELL" for c in range(ord('A'), ord('P') + 1)]

    while True:
        if serial_connection.in_waiting > 0:
            line = serial_connection.readline().decode('utf-8', errors='ignore').strip()
            print("Received:", line)

            voltage_match = voltage_pattern.search(line)
            status_match = status_pattern.search(line)

            if voltage_match:
                cell = voltage_match.group(1)
                voltage = float(voltage_match.group(2))
                socketio.emit('cell_voltage', {'cell': cell, 'voltage': voltage})
                cell_voltages[cell] = voltage

                last_status = cell_statuses.get(cell, 'OK')
                if last_status != "OK":
                    socketio.emit('cell_status', {'cell': cell, 'status': 'OK'})
                    cell_statuses[cell] = "OK"

            if status_match:
                cell = status_match.group(1)
                status = status_match.group(2)
                socketio.emit('cell_status', {'cell': cell, 'status': status})
                cell_statuses[cell] = status

            # If we have voltages for all cells, save to DB
            if len(cell_voltages) == 16:
                ordered_voltages = [cell_voltages[f"{chr(c)} CELL"] for c in range(ord('A'), ord('P') + 1)]
                shift = get_current_shift()
                battery_qr = "HARDCODED-QR-001"  # Replace later with actual QR if needed
                save_full_cell_data(shift, battery_qr, ordered_voltages)
                print("📥 Saved full data to DB.")
                cell_voltages.clear()

        time.sleep(0.01)

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
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    for cell in ordered_cells:
        min_v = float(data.get(f"{cell}_min", "0.000"))
        max_v = float(data.get(f"{cell}_max", "0.000"))
        csv_parts.append(str(min_v))
        csv_parts.append(str(max_v))

        c.execute('REPLACE INTO thresholds (cell, min_voltage, max_voltage) VALUES (?, ?, ?)',
                  (cell, min_v, max_v))

    conn.commit()
    conn.close()

    csv_string = ",".join(csv_parts) + "\n"
    serial_connection.write(csv_string.encode())

    return jsonify({"message": "Thresholds updated"}), 200

def start_serial_thread():
    thread = threading.Thread(target=read_from_arduino)
    thread.daemon = True
    thread.start()

if __name__ == '__main__':
    init_db()
    start_serial_thread()
    socketio.run(app, host='0.0.0.0', port=5001)
