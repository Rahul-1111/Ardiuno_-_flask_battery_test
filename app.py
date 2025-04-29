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
SERIAL_PORT = "COM3"
BAUD_RATE = 115200
serial_connection = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)

# Database
DB_NAME = "battery_data.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # Voltage + Status columns per cell
    fields = ", ".join([f"{chr(c)}_voltage REAL, {chr(c)}_status TEXT" for c in range(ord('A'), ord('P') + 1)])
    c.execute(f'''
        CREATE TABLE IF NOT EXISTS battery_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            shift TEXT,
            qr_code TEXT,
            {fields}
        )
    ''')
    conn.commit()
    conn.close()

def get_current_shift():
    now = datetime.now().time()
    if now >= datetime.strptime('06:00:00', '%H:%M:%S').time() and now < datetime.strptime('14:00:00', '%H:%M:%S').time():
        return 'Shift 1'
    elif now >= datetime.strptime('14:00:00', '%H:%M:%S').time() and now < datetime.strptime('22:00:00', '%H:%M:%S').time():
        return 'Shift 2'
    else:
        return 'Shift 3'

def save_full_cell_data(shift, qr_code, cell_data):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    columns = ', '.join([f"{cell}_voltage, {cell}_status" for cell in cell_data])
    placeholders = ', '.join(['?'] * (len(cell_data) * 2))
    values = []
    for cell in cell_data:
        values.append(cell_data[cell]['voltage'])
        values.append(cell_data[cell]['status'])

    query = f'''
        INSERT INTO battery_log (timestamp, shift, qr_code, {columns})
        VALUES (?, ?, ?, {placeholders})
    '''
    c.execute(query, [timestamp, shift, qr_code] + values)
    conn.commit()
    conn.close()
    print("📥 Saved full data to DB.")

def read_from_arduino():
    voltage_pattern = re.compile(r'([A-P]) CELL Voltage: ([\-0-9.]+) V')
    status_pattern = re.compile(r'([A-P]) CELL (Undervoltage|Overvoltage)')
    final_summary_pattern = re.compile(r'📊 Final Summary:')
    cycle_end_pattern = re.compile(r'Cycle End')

    cell_data = {}
    collecting_data = False
    qr_code = "XYZ123"  # 🔧 Replace with actual scanned input when integrated

    expected_cells = [chr(c) for c in range(ord('A'), ord('P') + 1)]

    while True:
        if serial_connection.in_waiting > 0:
            line = serial_connection.readline().decode('utf-8', errors='ignore').strip()
            print("Received:", line)

            # Detect start of summary
            if final_summary_pattern.search(line):
                collecting_data = True
                print("📊 Summary started. Ready to collect final data.")

            # Collect voltage
            v_match = voltage_pattern.search(line)
            if v_match:
                cell = v_match.group(1)
                voltage = float(v_match.group(2))
                socketio.emit('cell_voltage', {'cell': cell, 'voltage': voltage})
                cell_data[cell] = cell_data.get(cell, {})
                cell_data[cell]['voltage'] = voltage
                if 'status' not in cell_data[cell]:
                    cell_data[cell]['status'] = 'OK'

            # Collect status
            s_match = status_pattern.search(line)
            if s_match:
                cell = s_match.group(1)
                status = s_match.group(2).upper().replace("VOLTAGE", "")
                socketio.emit('cell_status', {'cell': cell, 'status': status})
                cell_data[cell] = cell_data.get(cell, {})
                cell_data[cell]['status'] = status

            # Once cycle ends, store full data
            if collecting_data and cycle_end_pattern.search(line):
                if all(cell in cell_data and 'voltage' in cell_data[cell] and 'status' in cell_data[cell] for cell in expected_cells):
                    shift = get_current_shift()
                    save_full_cell_data(shift, qr_code, cell_data)
                    print("✅ Final cycle data saved.")
                else:
                    print("⚠️ Incomplete data. Skipping save.")
                cell_data.clear()
                collecting_data = False

        time.sleep(0.01)


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/set_thresholds', methods=['POST'])
def set_thresholds():
    data = request.get_json()

    ordered_cells = [f"{chr(c)}_CELL" for c in range(ord('A'), ord('P') + 1)]
    csv_parts = []
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS thresholds (
            cell TEXT PRIMARY KEY,
            min_voltage REAL,
            max_voltage REAL
        )
    ''')

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

@app.route('/view-data')
def view_data():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM battery_log ORDER BY timestamp DESC LIMIT 100")
    records = c.fetchall()
    conn.close()

    cells = [chr(c) for c in range(ord('A'), ord('P') + 1)]
    return render_template('data_view.html', records=records, cells=cells)

def start_serial_thread():
    thread = threading.Thread(target=read_from_arduino)
    thread.daemon = True
    thread.start()

if __name__ == '__main__':
    init_db()
    start_serial_thread()
    socketio.run(app, host='0.0.0.0', port=5001)
