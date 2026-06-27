# ========================================
# SMART AGRICULTURE MONITORING SYSTEM
# Raspberry Pi Zero 2W - OPTIMIZED VERSION
# Smooth Performance with Limited Resources
# ========================================

"""
INSTALLATION FOR RASPBERRY PI ZERO 2W:

# Basic system update
sudo apt-get update
sudo apt-get install -y python3-pip python3-opencv

# Lightweight dependencies
pip3 install flask opencv-python RPi.GPIO requests
pip3 install adafruit-circuitpython-ads1x15 pillow

# Optional (if you have space and want YOLO)
pip3 install ultralytics --no-deps
pip3 install torch torchvision --index-url https://download.pytorch.org/whl/cpu

# Enable Camera and I2C
sudo raspi-config
# Interface Options -> Enable Camera and I2C

# For LSC-6 controller
pip3 install pyserial
"""

import os
import cv2
import time
import threading
from datetime import datetime
from flask import Flask, render_template, Response, jsonify, request
import RPi.GPIO as GPIO
import json

# Optional imports
try:
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
except:
    YOLO_AVAILABLE = False
    print("YOLO not available - running in lightweight mode")

try:
    import board
    import busio
    import adafruit_ads1x15.ads1115 as ADS
    from adafruit_ads1x15.analog_in import AnalogIn
    SENSOR_AVAILABLE = True
except:
    SENSOR_AVAILABLE = False

try:
    import serial
    SERIAL_AVAILABLE = True
except:
    SERIAL_AVAILABLE = False

# ========================================
# OPTIMIZED CONFIGURATION FOR PI ZERO 2W
# ========================================

class Config:
    # GPIO Pins
    SERVO_PIN = 18
    FERTILIZER_RELAY = 23
    WATER_RELAY = 24
    UV_LIGHT_RELAY = 25
    BUZZER_PIN = 17
    PIR_SENSOR_PIN = 27
    RELAY_SWITCH_2 = 22
    MQ2_SENSOR_PIN = 4
    BOX_SERVO_PIN = 12
    
    # Camera - REDUCED RESOLUTION for Pi Zero 2W
    CAMERA_INDEX = 0
    CAMERA_WIDTH = 320  # Reduced from 640
    CAMERA_HEIGHT = 240  # Reduced from 480
    CAMERA_FPS = 10      # Lower FPS for smoother performance
    
    # Model
    MODEL_PATH = 'best.pt'
    
    # Timing - OPTIMIZED
    SOIL_CHECK_INTERVAL = 1800
    FERTILIZER_SPRAY_TIME = 30
    UV_LIGHT_TIME = 180
    FRAME_SKIP = 3  # Process every 3rd frame to reduce CPU load
    
    # LSC-6 Servo Controller
    LSC6_PORT = '/dev/ttyUSB0'
    LSC6_BAUDRATE = 9600
    
    # Performance
    DETECTION_CONFIDENCE = 0.6  # Higher threshold = faster
    MAX_LOGS = 50  # Reduced log storage

# ========================================
# LIGHTWEIGHT LSC-6 CONTROLLER
# ========================================

class LSC6Controller:
    def __init__(self, port=Config.LSC6_PORT, baudrate=Config.LSC6_BAUDRATE):
        self.ser = None
        self.connected = False
        self.servo_positions = [1500] * 6
        
        if SERIAL_AVAILABLE:
            try:
                self.ser = serial.Serial(port, baudrate, timeout=0.5)
                time.sleep(1)
                self.connected = True
                print(f"LSC-6: Connected")
            except:
                print("LSC-6: Not available")
    
    def move_servo(self, servo_id, position, speed=1000):
        if not self.connected or servo_id < 1 or servo_id > 6:
            return False
        
        position = max(500, min(2500, position))
        self.servo_positions[servo_id - 1] = position
        command = f"#{servo_id}P{position}T{speed}!\r\n"
        
        try:
            self.ser.write(command.encode())
            return True
        except:
            return False
    
    def reset_position(self):
        if not self.connected:
            return False
        command = ""
        for i in range(6):
            self.servo_positions[i] = 1500
            command += f"#{i+1}P1500"
        command += "T1000!\r\n"
        try:
            self.ser.write(command.encode())
            return True
        except:
            return False
    
    def close(self):
        if self.ser:
            self.ser.close()

# ========================================
# OPTIMIZED HARDWARE CONTROLLER
# ========================================

class HardwareController:
    def __init__(self):
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        
        # Setup Servos with reduced frequency
        GPIO.setup(Config.SERVO_PIN, GPIO.OUT)
        self.servo = GPIO.PWM(Config.SERVO_PIN, 50)
        self.servo.start(0)
        
        GPIO.setup(Config.BOX_SERVO_PIN, GPIO.OUT)
        self.box_servo = GPIO.PWM(Config.BOX_SERVO_PIN, 50)
        self.box_servo.start(0)
        
        # Setup Relays
        for pin in [Config.FERTILIZER_RELAY, Config.WATER_RELAY, 
                    Config.UV_LIGHT_RELAY, Config.RELAY_SWITCH_2]:
            GPIO.setup(pin, GPIO.OUT)
            GPIO.output(pin, GPIO.HIGH)
        
        # Setup Buzzer
        GPIO.setup(Config.BUZZER_PIN, GPIO.OUT)
        self.buzzer = GPIO.PWM(Config.BUZZER_PIN, 2000)
        
        # Setup Sensors
        GPIO.setup(Config.PIR_SENSOR_PIN, GPIO.IN)
        GPIO.setup(Config.MQ2_SENSOR_PIN, GPIO.IN)
        
        # Soil Sensor
        self.soil_sensor = None
        if SENSOR_AVAILABLE:
            try:
                i2c = busio.I2C(board.SCL, board.SDA)
                ads = ADS.ADS1115(i2c)
                self.soil_sensor = AnalogIn(ads, ADS.P0)
            except:
                pass
        
        # LSC-6
        self.lsc6 = LSC6Controller()
        
        self.servo_position = 0
        self.box_open = False
        
        # Quick startup beep
        self.beep(0.1)
    
    def beep(self, duration=0.2):
        try:
            self.buzzer.start(30)  # Reduced duty cycle
            time.sleep(duration)
            self.buzzer.stop()
        except:
            pass
    
    def play_alarm(self, duration=5):
        try:
            end_time = time.time() + duration
            while time.time() < end_time:
                self.buzzer.ChangeFrequency(2000)
                self.buzzer.start(30)
                time.sleep(0.3)
                self.buzzer.stop()
                time.sleep(0.2)
            self.buzzer.stop()
        except:
            pass
    
    def set_servo_angle(self, angle):
        try:
            duty = 2 + (angle / 18)
            self.servo.ChangeDutyCycle(duty)
            time.sleep(0.3)
            self.servo.ChangeDutyCycle(0)
            self.servo_position = angle
        except:
            pass
    
    def control_box(self, open_box):
        try:
            angle = 90 if open_box else 0
            duty = 2 + (angle / 18)
            self.box_servo.ChangeDutyCycle(duty)
            time.sleep(0.3)
            self.box_servo.ChangeDutyCycle(0)
            self.box_open = open_box
        except:
            pass
    
    def read_pir_sensor(self):
        try:
            return GPIO.input(Config.PIR_SENSOR_PIN) == GPIO.HIGH
        except:
            return False
    
    def read_mq2_sensor(self):
        try:
            return GPIO.input(Config.MQ2_SENSOR_PIN) == GPIO.HIGH
        except:
            return False
    
    def read_soil_moisture(self):
        if self.soil_sensor:
            try:
                voltage = self.soil_sensor.voltage
                moisture = max(0, min(100, (3.3 - voltage) / 1.8 * 100))
                return round(moisture, 2)
            except:
                pass
        return None
    
    def control_relay(self, relay_pin, state):
        try:
            GPIO.output(relay_pin, GPIO.LOW if state else GPIO.HIGH)
        except:
            pass
    
    def spray_fertilizer(self, duration=30):
        self.control_relay(Config.FERTILIZER_RELAY, True)
        time.sleep(duration)
        self.control_relay(Config.FERTILIZER_RELAY, False)
        self.beep(0.1)
    
    def spray_water(self, duration=30):
        self.control_relay(Config.WATER_RELAY, True)
        time.sleep(duration)
        self.control_relay(Config.WATER_RELAY, False)
        self.beep(0.1)
    
    def activate_uv_light(self, duration=180):
        self.control_relay(Config.UV_LIGHT_RELAY, True)
        time.sleep(duration)
        self.control_relay(Config.UV_LIGHT_RELAY, False)
        self.beep(0.1)
    
    def cleanup(self):
        try:
            self.servo.stop()
            self.box_servo.stop()
            self.buzzer.stop()
            self.lsc6.close()
            GPIO.cleanup()
        except:
            pass

# ========================================
# LIGHTWEIGHT DETECTION SYSTEM
# ========================================

class LightweightDetector:
    def __init__(self, model_path):
        self.model = None
        self.use_simple_detection = True
        
        if YOLO_AVAILABLE and os.path.exists(model_path):
            try:
                self.model = YOLO(model_path)
                self.use_simple_detection = False
                print("YOLO Model loaded")
            except:
                print("YOLO failed - using simple detection")
        else:
            print("Using simple color-based detection")
        
        self.last_detection = None
        self.detection_count = 0
    
    def simple_disease_detection(self, frame):
        """Lightweight color-based detection for diseased leaves"""
        detections = []
        
        try:
            # Convert to HSV for color detection
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            
            # Detect brown/yellow spots (common disease indicators)
            # Brown range
            lower_brown = (10, 50, 50)
            upper_brown = (25, 255, 200)
            mask_brown = cv2.inRange(hsv, lower_brown, upper_brown)
            
            # Yellow range (yellowing leaves)
            lower_yellow = (20, 100, 100)
            upper_yellow = (35, 255, 255)
            mask_yellow = cv2.inRange(hsv, lower_yellow, upper_yellow)
            
            # Combine masks
            combined = cv2.bitwise_or(mask_brown, mask_yellow)
            
            # Find contours
            contours, _ = cv2.findContours(combined, cv2.RETR_EXTERNAL, 
                                          cv2.CHAIN_APPROX_SIMPLE)
            
            annotated = frame.copy()
            
            for contour in contours:
                area = cv2.contourArea(contour)
                if area > 100:  # Minimum area threshold
                    x, y, w, h = cv2.boundingRect(contour)
                    cv2.rectangle(annotated, (x, y), (x+w, y+h), (0, 255, 0), 2)
                    cv2.putText(annotated, "Possible Disease", (x, y-5),
                               cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
                    
                    detections.append({
                        'class': 'Disease Spot',
                        'confidence': 0.7,
                        'bbox': [x, y, x+w, y+h]
                    })
            
            return detections, annotated
            
        except Exception as e:
            print(f"Simple detection error: {e}")
            return [], frame
    
    def detect_diseases(self, frame):
        """Detect diseases using available method"""
        if self.use_simple_detection or self.model is None:
            return self.simple_disease_detection(frame)
        
        try:
            # Use YOLO if available
            results = self.model(frame, conf=Config.DETECTION_CONFIDENCE, 
                               verbose=False)
            
            detections = []
            annotated = frame.copy()
            
            for result in results:
                boxes = result.boxes
                for box in boxes:
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    confidence = float(box.conf[0])
                    class_id = int(box.cls[0])
                    class_name = self.model.names[class_id]
                    
                    cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 1)
                    label = f"{class_name}: {confidence:.2f}"
                    cv2.putText(annotated, label, (x1, y1-5), 
                               cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
                    
                    detections.append({
                        'class': class_name,
                        'confidence': confidence,
                        'bbox': [x1, y1, x2, y2]
                    })
            
            self.detection_count = len(detections)
            return detections, annotated
            
        except Exception as e:
            print(f"YOLO detection error: {e}")
            return self.simple_disease_detection(frame)

# ========================================
# OPTIMIZED MONITORING SYSTEM
# ========================================

class MonitoringSystem:
    def __init__(self):
        self.hardware = HardwareController()
        self.detector = LightweightDetector(Config.MODEL_PATH)
        self.camera = None
        self.running = False
        self.current_frame = None
        self.annotated_frame = None
        self.frame_counter = 0
        
        self.status = {
            'soil_moisture': None,
            'last_soil_check': None,
            'last_detection': None,
            'detection_count': 0,
            'fertilizer_active': False,
            'water_active': False,
            'uv_light_active': False,
            'servo_position': 0,
            'box_open': False,
            'motion_detected': False,
            'smoke_detected': False,
            'relay_switch_2': True,
            'auto_mode': True,
            'lsc6_connected': self.hardware.lsc6.connected,
            'lsc6_positions': self.hardware.lsc6.servo_positions,
            'system_logs': []
        }
        
        self.daily_report = {
            'date': datetime.now().strftime("%Y-%m-%d"),
            'total_detections': 0,
            'diseases_found': [],
            'actions_taken': [],
            'motion_events': 0,
            'smoke_alerts': 0
        }
        
        # Start sensor monitoring
        threading.Thread(target=self.sensor_monitoring_loop, daemon=True).start()
    
    def add_log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {message}"
        self.status['system_logs'].insert(0, log_entry)
        if len(self.status['system_logs']) > Config.MAX_LOGS:
            self.status['system_logs'] = self.status['system_logs'][:Config.MAX_LOGS]
        print(log_entry)
    
    def sensor_monitoring_loop(self):
        """Lightweight sensor monitoring"""
        last_motion = False
        last_smoke = False
        
        while True:
            try:
                # Check PIR
                motion = self.hardware.read_pir_sensor()
                if motion != last_motion:
                    self.status['motion_detected'] = motion
                    if motion:
                        self.add_log("Motion detected")
                        self.hardware.control_relay(Config.RELAY_SWITCH_2, False)
                        self.status['relay_switch_2'] = False
                        self.hardware.beep(0.05)
                        self.daily_report['motion_events'] += 1
                    else:
                        self.hardware.control_relay(Config.RELAY_SWITCH_2, True)
                        self.status['relay_switch_2'] = True
                    last_motion = motion
                
                # Check MQ2
                smoke = self.hardware.read_mq2_sensor()
                if smoke != last_smoke:
                    self.status['smoke_detected'] = smoke
                    if smoke:
                        self.add_log("SMOKE DETECTED!")
                        self.daily_report['smoke_alerts'] += 1
                        threading.Thread(target=self.hardware.play_alarm, 
                                       args=(3,), daemon=True).start()
                    last_smoke = smoke
                
                time.sleep(1)  # Check every second
            except:
                time.sleep(1)
    
    def start_camera(self):
        """Start optimized camera"""
        try:
            self.camera = cv2.VideoCapture(Config.CAMERA_INDEX)
            self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, Config.CAMERA_WIDTH)
            self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, Config.CAMERA_HEIGHT)
            self.camera.set(cv2.CAP_PROP_FPS, Config.CAMERA_FPS)
            self.camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Reduce buffer
            self.running = True
            self.add_log("Camera started")
        except Exception as e:
            print(f"Camera error: {e}")
    
    def stop_camera(self):
        self.running = False
        if self.camera:
            self.camera.release()
    
    def get_frame(self):
        if self.camera and self.camera.isOpened():
            ret, frame = self.camera.read()
            if ret:
                self.current_frame = frame
                return frame
        return None
    
    def process_frame(self):
        """Process frames with frame skipping"""
        frame = self.get_frame()
        if frame is None:
            return None, None
        
        # Frame skipping for performance
        self.frame_counter += 1
        if self.frame_counter % Config.FRAME_SKIP != 0:
            return [], frame
        
        # Detect diseases
        detections, annotated = self.detector.detect_diseases(frame)
        self.annotated_frame = annotated
        
        self.status['detection_count'] = len(detections)
        
        if len(detections) > 0 and self.status['auto_mode']:
            self.handle_disease_detection(detections)
        
        return detections, annotated
    
    def handle_disease_detection(self, detections):
        if len(detections) > 0:
            self.add_log(f"Disease: {len(detections)} found")
            self.daily_report['total_detections'] += len(detections)
            
            for det in detections:
                if det['class'] not in self.daily_report['diseases_found']:
                    self.daily_report['diseases_found'].append(det['class'])
            
            threading.Thread(target=self.execute_treatment, daemon=True).start()
    
    def execute_treatment(self):
        self.add_log("Treatment started")
        self.hardware.beep(0.2)
        
        self.status['fertilizer_active'] = True
        self.hardware.spray_fertilizer(15)  # Shorter duration
        self.status['fertilizer_active'] = False
        
        self.status['uv_light_active'] = True
        self.hardware.activate_uv_light(60)  # Shorter duration
        self.status['uv_light_active'] = False
        
        self.add_log("Treatment complete")
    
    def check_soil_moisture(self):
        self.add_log("Checking soil...")
        
        self.hardware.set_servo_angle(90)
        time.sleep(1)
        
        moisture = self.hardware.read_soil_moisture()
        self.status['soil_moisture'] = moisture
        self.status['last_soil_check'] = datetime.now().strftime("%H:%M:%S")
        
        self.hardware.set_servo_angle(0)
        
        if moisture:
            self.add_log(f"Soil: {moisture}%")
            if moisture < 30 and self.status['auto_mode']:
                self.status['water_active'] = True
                self.hardware.spray_water(20)  # Shorter
                self.status['water_active'] = False
    
    def soil_monitoring_loop(self):
        while self.running:
            self.check_soil_moisture()
            time.sleep(Config.SOIL_CHECK_INTERVAL)
    
    def cleanup(self):
        self.stop_camera()
        self.hardware.cleanup()

# ========================================
# LIGHTWEIGHT WEB APPLICATION
# ========================================

app = Flask(__name__)
monitoring_system = MonitoringSystem()

def generate_frames():
    """Optimized frame generation"""
    while True:
        try:
            detections, frame = monitoring_system.process_frame()
            if frame is not None:
                # Compress JPEG more for bandwidth
                ret, buffer = cv2.imencode('.jpg', frame, 
                                          [cv2.IMWRITE_JPEG_QUALITY, 70])
                if ret:
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + 
                           buffer.tobytes() + b'\r\n')
            time.sleep(0.1)
        except:
            time.sleep(0.5)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(),
                   mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/status')
def get_status():
    monitoring_system.status['box_open'] = monitoring_system.hardware.box_open
    monitoring_system.status['lsc6_positions'] = monitoring_system.hardware.lsc6.servo_positions
    return jsonify(monitoring_system.status)

@app.route('/api/control', methods=['POST'])
def control():
    data = request.json
    action = data.get('action')
    
    try:
        if action == 'fertilizer':
            duration = min(data.get('duration', 30), 60)
            threading.Thread(target=monitoring_system.hardware.spray_fertilizer, 
                           args=(duration,), daemon=True).start()
        
        elif action == 'water':
            duration = min(data.get('duration', 30), 60)
            threading.Thread(target=monitoring_system.hardware.spray_water,
                           args=(duration,), daemon=True).start()
        
        elif action == 'uv_light':
            duration = min(data.get('duration', 180), 300)
            threading.Thread(target=monitoring_system.hardware.activate_uv_light,
                           args=(duration,), daemon=True).start()
        
        elif action == 'servo':
            angle = data.get('angle', 0)
            monitoring_system.hardware.set_servo_angle(angle)
            monitoring_system.status['servo_position'] = angle
        
        elif action == 'box':
            open_box = data.get('open', False)
            monitoring_system.hardware.control_box(open_box)
        
        elif action == 'beep':
            monitoring_system.hardware.beep(0.1)
        
        elif action == 'alarm':
            threading.Thread(target=monitoring_system.hardware.play_alarm,
                           args=(3,), daemon=True).start()
        
        elif action == 'soil_check':
            threading.Thread(target=monitoring_system.check_soil_moisture,
                           daemon=True).start()
        
        elif action == 'toggle_auto':
            monitoring_system.status['auto_mode'] = not monitoring_system.status['auto_mode']
        
        elif action == 'lsc6_servo':
            servo_id = data.get('servo_id', 1)
            position = data.get('position', 1500)
            speed = data.get('speed', 1000)
            success = monitoring_system.hardware.lsc6.move_servo(servo_id, position, speed)
            return jsonify({'success': success})
        
        elif action == 'lsc6_reset':
            monitoring_system.hardware.lsc6.reset_position()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/daily_report')
def daily_report():
    return jsonify(monitoring_system.daily_report)

@app.route('/api/download_report')
def download_report():
    report_json = json.dumps(monitoring_system.daily_report, indent=2)
    return Response(
        report_json,
        mimetype='application/json',
        headers={'Content-Disposition': 'attachment;filename=report.json'}
    )

# ========================================
# MAIN EXECUTION
# ========================================

if __name__ == '__main__':
    try:
        print("="*50)
        print("SMART AGRICULTURE - PI ZERO 2W OPTIMIZED")
        print("="*50)
        
        monitoring_system.start_camera()
        
        soil_thread = threading.Thread(target=monitoring_system.soil_monitoring_loop,
                                       daemon=True)
        soil_thread.start()
        
        print("\n✅ System Ready!")
        print("🌐 http://raspberrypi.local:5000")
        print("📹 Camera: 320x240 @10fps")
        print("🔔 Sensors: Active")
        print("🦾 LSC-6:", "Connected" if monitoring_system.hardware.lsc6.connected else "Not Connected")
        print("\nPress Ctrl+C to stop\n")
        
        # Run with minimal threads
        app.run(host='0.0.0.0', port=5000, threaded=True, debug=False)
        
    except KeyboardInterrupt:
        print("\n\nShutting down...")
    finally:
        monitoring_system.cleanup()
        print("System stopped")
