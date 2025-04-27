from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO
import serial
import time
import threading
import re

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
                
                # Default to OK, unless overwritten
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

    # Send CSV over Serial to Arduino
    serial_connection.write(csv_string.encode())

    return jsonify({"message": "Thresholds sent"}), 200

def start_serial_thread():
    thread = threading.Thread(target=read_from_arduino)
    thread.daemon = True
    thread.start()

if __name__ == '__main__':
    start_serial_thread()
    socketio.run(app, host='0.0.0.0', port=5001)
