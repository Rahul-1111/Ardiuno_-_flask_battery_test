from flask import Flask, render_template, request
from flask_socketio import SocketIO
import serial
import time
import threading
import re
import json

app = Flask(__name__)
socketio = SocketIO(app)

SERIAL_PORT = "COM3"  # Adjust if needed
BAUD_RATE = 115200
serial_connection = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)

def read_from_arduino():
    voltage_pattern = re.compile(r'([A-P] CELL) Voltage: ([\-0-9.]+) V')
    status_pattern = re.compile(r'([A-P] CELL) (Undervoltage|Overvoltage)')

    cell_statuses = {}

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
                
                # Default to OK, unless overwritten in following lines
                last_status = cell_statuses.get(cell)
                if last_status != "OK":
                    socketio.emit('cell_status', {'cell': cell, 'status': 'OK'})
                    cell_statuses[cell] = "OK"

            if status_match:
                cell = status_match.group(1)
                status = status_match.group(2)
                socketio.emit('cell_status', {'cell': cell, 'status': status})
                cell_statuses[cell] = status

        time.sleep(0.01)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/set_thresholds', methods=['POST'])
def set_thresholds():
    thresholds = request.json
    print("Received thresholds:", thresholds)

    ordered_keys = [
        "A_CELL_min", "A_CELL_max", "B_CELL_min", "B_CELL_max",
        "C_CELL_min", "C_CELL_max", "D_CELL_min", "D_CELL_max",
        "E_CELL_min", "E_CELL_max", "F_CELL_min", "F_CELL_max",
        "G_CELL_min", "G_CELL_max", "H_CELL_min", "H_CELL_max",
        "I_CELL_min", "I_CELL_max", "J_CELL_min", "J_CELL_max",
        "K_CELL_min", "K_CELL_max", "L_CELL_min", "L_CELL_max",
        "M_CELL_min", "M_CELL_max", "N_CELL_min", "N_CELL_max",
        "O_CELL_min", "O_CELL_max", "P_CELL_min", "P_CELL_max"
    ]

    values = [thresholds[key] for key in ordered_keys]

    # Join into a single comma-separated string
    threshold_str = ",".join(values)
    serial_connection.write(f"<THRESHOLDS>{threshold_str}</THRESHOLDS>\n".encode())
    return {'status': 'sent'}


def start_serial_thread():
    thread = threading.Thread(target=read_from_arduino)
    thread.daemon = True
    thread.start()

if __name__ == '__main__':
    start_serial_thread()
    socketio.run(app, host='0.0.0.0', port=5001)
