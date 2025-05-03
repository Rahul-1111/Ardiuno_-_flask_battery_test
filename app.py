from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO
import sqlite3
import serial
import time
import threading
import re
from datetime import datetime
import os
import sys

app = Flask(__name__)
socketio = SocketIO(app, async_mode='threading')

# Serial port configuration
SERIAL_PORT = "COM3"
BAUD_RATE = 115200

# --- Resource path helper for PyInstaller ---
def resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller .exe"""
    if hasattr(sys, '_MEIPASS'):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# --- Database file ---
DB_FILE = resource_path("battery_data.db")

# --- List of expected cells ---
expected_cells = [f"{chr(c)} CELL" for c in range(ord('A'), ord('P') + 1)]

# --- Open serial connection ---
def open_serial_connection():
    attempts = 5
    while attempts > 0:
        try:
            serial_connection = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
            print(f"Serial port {SERIAL_PORT} opened successfully.")
            return serial_connection
        except serial.SerialException as e:
            print(f"Error opening serial port {SERIAL_PORT}: {e}")
            attempts -= 1
            time.sleep(1)
    print(f"Failed to open serial port after several attempts.")
    return None

serial_connection = open_serial_connection()

# --- Initialize database ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    fields = ", ".join([f"{cell.replace(' ', '_')}_voltage REAL, {cell.replace(' ', '_')}_status TEXT" for cell in expected_cells])
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

# --- Shift logic ---
def get_current_shift():
    now = datetime.now().time()
    if now >= datetime.strptime('06:00:00', '%H:%M:%S').time() and now < datetime.strptime('14:00:00', '%H:%M:%S').time():
        return 'Shift 1'
    elif now >= datetime.strptime('14:00:00', '%H:%M:%S').time() and now < datetime.strptime('22:00:00', '%H:%M:%S').time():
        return 'Shift 2'
    else:
        return 'Shift 3'

# --- Save full cell data ---
def save_full_cell_data(cell_data):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    shift = get_current_shift()
    qr_code = "XYZ123"  # Placeholder QR code

    columns = ', '.join([f"{cell.replace(' ', '_')}_voltage, {cell.replace(' ', '_')}_status" for cell in expected_cells])
    values = [timestamp, shift, qr_code]
    for cell in expected_cells:
        voltage = cell_data[cell]['voltage'] if cell_data[cell]['voltage'] is not None else None
        status = cell_data[cell]['status'] if cell_data[cell]['status'] is not None else 'OK'
        values.append(voltage)
        values.append(status)

    placeholders = ', '.join(['?'] * len(values))
    query = f'INSERT INTO battery_log (timestamp, shift, qr_code, {columns}) VALUES ({placeholders})'
    try:
        c.execute(query, values)
        conn.commit()
        print("Saved full data to database.")
    except Exception as e:
        print(f"Error saving data: {e}")
    finally:
        conn.close()

# --- Serial reader ---
def read_from_arduino():
    voltage_pattern = re.compile(r'([A-P] CELL) Voltage: ([-0-9.]+) V')
    status_pattern = re.compile(r'([A-P] CELL) (Undervoltage|Overvoltage)')
    final_summary_pattern = re.compile(r'📊 Final Summary:')
    cycle_end_pattern = re.compile(r'Cycle End')
    reset_data_pattern = re.compile(r'RESET DATA')

    cell_data = {cell: {'voltage': None, 'status': 'OK'} for cell in expected_cells}
    last_statuses = {cell: None for cell in expected_cells}
    collecting_data = False

    while True:
        try:
            if serial_connection and serial_connection.in_waiting > 0:
                line = serial_connection.readline().decode('utf-8', errors='ignore').strip()
                print("Received:", line)

                if final_summary_pattern.search(line):
                    collecting_data = True
                    print("Summary started. Collecting final data.")

                voltage_match = voltage_pattern.search(line)
                status_match = status_pattern.search(line)

                if voltage_match:
                    cell = voltage_match.group(1)
                    voltage = float(voltage_match.group(2))
                    cell_data[cell]['voltage'] = voltage
                    socketio.emit('cell_voltage', {'cell': cell, 'voltage': voltage})

                    if last_statuses[cell] != "OK":
                        socketio.emit('cell_status', {'cell': cell, 'status': 'OK'})
                        cell_data[cell]['status'] = "OK"
                        last_statuses[cell] = "OK"

                if status_match:
                    cell = status_match.group(1)
                    status = status_match.group(2)
                    cell_data[cell]['status'] = status
                    socketio.emit('cell_status', {'cell': cell, 'status': status})
                    last_statuses[cell] = status

                if collecting_data and cycle_end_pattern.search(line):
                    if all(cell_data[cell]['voltage'] is not None for cell in expected_cells):
                        save_full_cell_data(cell_data)
                        socketio.emit('cycle_completed', {'message': 'Cycle completed, data saved.'})
                        print("Cycle ended, data saved.")
                    else:
                        print("Incomplete voltage data, skipping save.")
                    cell_data = {cell: {'voltage': None, 'status': 'OK'} for cell in expected_cells}
                    last_statuses = {cell: None for cell in expected_cells}
                    collecting_data = False

                if reset_data_pattern.search(line):
                    print("Reset data detected, triggering frontend reset.")
                    socketio.emit('reset_data')

            time.sleep(0.01)
        except Exception as e:
            print("Error in serial thread:", e)
            time.sleep(0.1)

# --- Routes ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/set_thresholds', methods=['POST'])
def set_thresholds():
    data = request.get_json()
    ordered_cells = [f"{chr(c)}_CELL" for c in range(ord('A'), ord('P') + 1)]
    csv_parts = []
    for cell in ordered_cells:
        min_v = data.get(f"{cell}_min", "0.000")
        max_v = data.get(f"{cell}_max", "0.000")
        csv_parts.append(str(min_v))
        csv_parts.append(str(max_v))
    csv_string = ",".join(csv_parts) + "\n"
    if serial_connection:
        serial_connection.write(csv_string.encode())
        return jsonify({"message": "Thresholds sent"}), 200
    else:
        return jsonify({"error": "Serial connection not available"}), 500
    
@socketio.on('start_measurement')
def handle_start_measurement():
    if serial_connection:
        try:
            serial_connection.write(b'MEASUREMENT START\n')
            print("Sent MEASUREMENT START to Arduino from GUI.")
        except Exception as e:
            print(f"Failed to send MEASUREMENT START to Arduino: {e}")

@app.route('/view-data')
def view_data():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM battery_log ORDER BY timestamp DESC LIMIT 100")
    records = c.fetchall()
    conn.close()
    return render_template('data_view.html', records=records, cells=expected_cells)

# --- Start background thread ---
def start_serial_thread():
    thread = threading.Thread(target=read_from_arduino)
    thread.daemon = True
    thread.start()

# --- App entrypoint ---
if __name__ == '__main__':
    init_db()
    start_serial_thread()
    socketio.run(app, host='0.0.0.0', port=5001)
