import RPi.GPIO as GPIO
import time
import requests
import json
import board
import busio
from adafruit_ssd1306 import SSD1306_I2C
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime

# --- [1] 설정 및 초기화 ---
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

# 핀 번호 설정
SERVO_PIN_DOOR = 16
SERVO_PIN_BASKET = 6
TRIG_PIN = 17
ECHO_PIN = 27

# GPIO 설정
GPIO.setup(TRIG_PIN, GPIO.OUT)
GPIO.setup(ECHO_PIN, GPIO.IN)
GPIO.setup(SERVO_PIN_DOOR, GPIO.OUT)
GPIO.setup(SERVO_PIN_BASKET, GPIO.OUT)

# 서보모터 초기화
pwm_door = GPIO.PWM(SERVO_PIN_DOOR, 50)
pwm_basket = GPIO.PWM(SERVO_PIN_BASKET, 50)
pwm_door.start(0)
pwm_basket.start(0)

SERVO_MIN_DUTY = 3
SERVO_MAX_DUTY = 12

# OLED 설정
i2c = busio.I2C(board.SCL, board.SDA)
try:
    oled = SSD1306_I2C(128, 64, i2c, addr=0x3c)
    font = ImageFont.load_default()
except Exception as e:
    print(f"OLED 초기화 실패: {e}")

API_KEY = "API_KEY"

# --- [2] 함수 정의 ---
def set_servo_degree(pwm, degree):
    if degree > 180: degree = 180
    if degree < 0: degree = 0
    duty = SERVO_MIN_DUTY + (degree * (SERVO_MAX_DUTY - SERVO_MIN_DUTY) / 180.0)
    pwm.ChangeDutyCycle(duty)
    time.sleep(0.5)
    pwm.ChangeDutyCycle(0)

def get_current_location():
    try:
        url = "http://ip-api.com/json"
        response = requests.get(url)
        
        if response.status_code == 200:
            data = response.json()
            # status가 success면 성공
            if data['status'] == 'success':
                lat = data['lat']
                lon = data['lon']
                city = data['city']
                print(f"{city} (위도: {lat}, 경도: {lon})")
                return lat, lon
            else:
                print("위치 정보를 가져오는데 실패")
                return None, None
        else:
            print("IP API 요청 실패")
            return None, None
            
    except Exception as e:
        print(f"위치 감지 중 에러 발생: {e}")
        return None, None



def get_distance():
    GPIO.output(TRIG_PIN, True)
    time.sleep(0.00001)
    GPIO.output(TRIG_PIN, False)
    
    timeout = time.time()
    while GPIO.input(ECHO_PIN) == 0:
        if time.time() - timeout > 0.1: return 1000
        start_time = time.time()

    timeout = time.time()
    while GPIO.input(ECHO_PIN) == 1:
        if time.time() - timeout > 0.1: return 1000
        stop_time = time.time()

    duration = stop_time - start_time
    distance = duration * 34300 / 2
    return distance

def get_combined_weather_info(lat, lon):
    result = {
        "temp": 0,
        "main": "Unknown",
        "id": 800,
        "max_pop": 0
    }

    try:
        # --- 1. 현재 날씨 조회 (/weather) ---
        url_curr = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={API_KEY}&units=metric"
        res_curr = requests.get(url_curr, timeout=5)
        data_curr = json.loads(res_curr.text)

        if data_curr.get("cod") == 200:
            result['temp'] = data_curr['main']['temp']
            result['main'] = data_curr['weather'][0]['main'] # Rain, Clear etc
            result['id'] = data_curr['weather'][0]['id']
        else:
            print("현재 날씨 조회 실패")
            return None

        # --- 2. 예보 조회 (/forecast) ---
        url_fore = f"https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&appid={API_KEY}&units=metric"
        res_fore = requests.get(url_fore, timeout=5)
        data_fore = json.loads(res_fore.text)

        if data_fore.get("cod") == "200":
            # 오늘 날짜 (YYYY-MM-DD)
            today_str = datetime.now().strftime("%Y-%m-%d")
            max_pop = 0.0

            # 3시간 간격 예보 리스트 순회
            for item in data_fore['list']:
                # 예보의 날짜가 오늘 날짜와 일치하는 경우만 계산
                if today_str in item['dt_txt']:
                    pop = float(item.get('pop', 0)) * 100
                    if pop > max_pop:
                        max_pop = pop
            
            result['max_pop'] = int(max_pop)
        else:
            print("예보 조회 실패")
            
        return result

    except Exception as e:
        print(f"API 요청 중 에러: {e}")
        return None

def display_info(w_data):
    try:
        oled.fill(0)
        canvas = Image.new("1", (oled.width, oled.height))
        draw = ImageDraw.Draw(canvas)
        
        # 1. 아이콘 처리
        icon_name = "cloud.png"
        w_id = w_data['id']
        if 200 <= w_id < 600: icon_name = "rain.png"
        elif 600 <= w_id < 700: icon_name = "snow.png"
        elif w_id == 800: icon_name = "sun.png"

        try:
            icon = Image.open(icon_name).convert("1").resize((35,35))
            canvas.paste(icon, (5, 0))
        except:
            draw.text((5, 10), "IMG X", font=font, fill=255)

        # 2. 현재 날씨 출력 (Current Weather API 결과)
        draw.text((50, 5), "NOW", font=font, fill=255)
        draw.text((50, 18), f"{w_data['temp']:.1f}C", font=font, fill=255)
        draw.text((90, 18), f"{w_data['main']}", font=font, fill=255)

        # 구분선
        draw.line((0, 40, 128, 40), fill=255)

        # 3. 오늘 강수 확률 출력 (Forecast API 결과)
        draw.text((10, 48), f" Today Rain: {w_data['max_pop']}%", font=font, fill=255)
        
        oled.image(canvas)
        oled.show()
    except Exception as e:
        print(f"디스플레이 에러: {e}")

# --- [3] 메인 루프 ---

MY_LAT, MY_LON = get_current_location()

print(f"시스템 시작 (좌표: {MY_LAT}, {MY_LON})")
set_servo_degree(pwm_door, 0)
set_servo_degree(pwm_basket, 0)

try:
    while True:
        dist = get_distance()
        # 10cm 이내 사람 감지
        if dist < 10:
            print(f"감지됨! (거리: {dist:.1f}cm)")            
            # 통합 날씨 데이터 가져오기 (Current + Forecast)
            weather_info = get_combined_weather_info(MY_LAT, MY_LON)
            
            if weather_info:
                print(f"-> 현재: {weather_info['temp']}도 / {weather_info['main']}")
                print(f"-> 오늘 최대 강수확률: {weather_info['max_pop']}%")
                
                display_info(weather_info)
                # 강수확률 0% 초과하면 우산 제공
                if weather_info['max_pop'] > 0:
                    print("비 올 확률 높음 -> 우산 배출")
                    set_servo_degree(pwm_door, 90)
                    time.sleep(0.5)
                    set_servo_degree(pwm_basket, 60)
                    time.sleep(3) # 우산 가져갈 시간
                    set_servo_degree(pwm_basket, 0)
                    time.sleep(0.5)
                    set_servo_degree(pwm_door, 0)
                else:
                    print("비 올 확률 낮음 -> 대기")
                    time.sleep(3)
                oled.fill(0)
                oled.show()
            else:
                print("API 통신 실패")
            time.sleep(2) # 중복 감지 방지
        time.sleep(0.5)

except KeyboardInterrupt:
    print("종료")
    pwm_door.stop()
    pwm_basket.stop()
    GPIO.cleanup()