#!/usr/bin/env python3

import time
import json
import signal
import sys
import configparser
import platform
import logging
from gpiozero import Button, OutputDevice
import paho.mqtt.client as mqtt

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("gpio2mqtt")

mqtt_client = None
running = True

mqtt_qos = 0
mqtt_retain = True

# Globale variabelen voor reconnect
last_check = 0
reconnect_interval = 10  # seconden

# Flag voor eerste connect
first_connect = True

# Config variabelen
gpio_pin = 18
meterfile = "meterstand.txt"
domoticz_idx = 0
MQTT_TOPIC_DOMOTICZ_IN = "domoticz/in"

# Globale variabelen
script_name = "gpio2mqtt"  # default fallback
lights = {}

def on_connect(client, userdata, flags, rc, properties=None):
    logger.info(f"Connected to MQTT Broker with result code {rc} ({mqtt.error_string(rc)})")

    config = userdata
    global first_connect
    if first_connect:
        publish_discovery(config)
        first_connect = False
    subscribe_to_lights()

def on_disconnect(client, userdata, rc):
    logger.info(f"Disconnected from MQTT Broker with result code {rc}")

def read_meter_value():
    try:
        with open(meterfile, "r") as f:
            val = f.read().strip()
            return int(val)
    except Exception as e:
        logger.error(f"Fout bij lezen van meterstand uit {meterfile}: {e}")
        return 0

def write_meter_value(value):
    try:
        with open(meterfile, "w") as f:
            f.write(str(value))
    except Exception as e:
        logger.error(f"Fout bij schrijven van meterstand naar {meterfile}: {e}")

def pulse_detected():
    global mqtt_client, domoticz_idx

    current_value = read_meter_value()
    new_value = current_value + 1
    logger.info(f"Pulse detected! Meterstand verhoogd van {current_value} naar {new_value}")

    write_meter_value(new_value)

    payload = json.dumps({
        "command": "udevice",
        "idx": domoticz_idx,
        "nvalue": new_value,
        "svalue": str(new_value)
    })

    mqtt_client.publish(MQTT_TOPIC_DOMOTICZ_IN, payload, qos=mqtt_qos, retain=mqtt_retain)
    logger.info(f"Verzonden naar Domoticz topic [{MQTT_TOPIC_DOMOTICZ_IN}]: {payload} (qos={mqtt_qos}, retain={mqtt_retain})")

def setup_lights(config):
    global lights
    lights = {}

    lampen_str = config.get("main", "lampen", fallback="").strip()
    if not lampen_str:
        logger.warning("Geen lampen gedefinieerd in config.ini onder [main] lampen=...")
        return

    lampen = [l.strip() for l in lampen_str.split(",") if l.strip()]
    logger.info(f"Geconfigureerde lampen: {lampen}")

    for name in lampen:
        pin_key = f"gpio_{name}"
        active_high_key = f"active_high_{name}"

        pin = config.getint("main", pin_key, fallback=None)
        if pin is None:
            logger.warning(f"GPIO-pin niet opgegeven voor lamp '{name}', lamp wordt overgeslagen.")
            continue

        active_high = config.getboolean("main", active_high_key, fallback=True)

        device = OutputDevice(pin, active_high=active_high, initial_value=False)
        lights[name] = device

        logger.info(f"Lamp '{name}': GPIO pin={pin}, active_high={active_high}")

def publish_discovery(config):
    hatopic = config.get("mqtt", "hatopic", fallback="homeassistant")

    device_info = {
        "identifiers": [platform.node()],
        "name": script_name,
        "model": platform.platform(),
        "manufacturer": "Raspberry Pi",
        "sw_version": platform.python_version()
    }

    for name, led in lights.items():
        discovery_topic = f"{hatopic}/light/{script_name}/{name}/config"
        set_topic = f"{script_name}/light/{name}/set"
        state_topic = f"{script_name}/light/{name}/state"

        unique_id = f"{script_name}_{name}_light"

        payload = {
            "name": name,
            "unique_id": unique_id,
            "state_topic": state_topic,
            "command_topic": set_topic,
            "payload_on": "ON",
            "payload_off": "OFF",
            "device": device_info,
            "platform": "mqtt"
        }

        mqtt_client.publish(discovery_topic, json.dumps(payload), qos=mqtt_qos, retain=True)
        logger.info(f"Discovery bericht gepubliceerd naar: {discovery_topic}")

def subscribe_to_lights():
    for name in lights.keys():
        set_topic = f"{script_name}/light/{name}/set"
        mqtt_client.subscribe(set_topic)
        logger.info(f"Subscribed to topic {set_topic}")

def handle_mqtt_message(client, userdata, msg):
    topic = msg.topic
    payload = msg.payload.decode().lower()

    for name, led in lights.items():
        pin = led.pin.number if hasattr(led, 'pin') else 'onbekend'
        set_topic = f"{script_name}/light/{name}/set"
        state_topic = f"{script_name}/light/{name}/state"

        if topic == set_topic:
            logger.info(f"[MQTT] Ontvangen commando '{payload}' voor lamp '{name}' op GPIO {pin}")
            logger.info(f"[GPIO] Status vóór schakelen: {'aan' if led.value else 'uit'}")

            if payload == "on":
                led.on()
                mqtt_client.publish(state_topic, "ON", retain=True)
                logger.info(f"[ACTIE] Lamp '{name}' aangezet")
            elif payload == "off":
                led.off()
                mqtt_client.publish(state_topic, "OFF", retain=True)
                logger.info(f"[ACTIE] Lamp '{name}' uitgezet")
            else:
                logger.warning(f"Onbekend payload: '{payload}' voor lamp '{name}'")
                return

            logger.info(f"[GPIO] Status ná schakelen: {'aan' if led.value else 'uit'}")

def run():
    global mqtt_client, gpio_pin, meterfile, domoticz_idx, mqtt_qos, mqtt_retain, MQTT_TOPIC_DOMOTICZ_IN, script_name

    config = configparser.ConfigParser()
    config.read("config.ini")

    # Lees MQTT config
    mqtt_broker = config.get("mqtt", "broker", fallback="localhost")
    mqtt_port = config.getint("mqtt", "port", fallback=1883)
    mqtt_user = config.get("mqtt", "username", fallback=None)
    mqtt_pass = config.get("mqtt", "password", fallback=None)
    mqtt_qos = config.getint("mqtt", "qos", fallback=0)
    mqtt_retain = config.getboolean("mqtt", "retain", fallback=True)

    # Ha-topic voor autodiscovery
    hatopic = config.get("mqtt", "hatopic", fallback="homeassistant")

    # Domoticz config
    gpio_pin = config.getint("domoticz", "gpio_pin", fallback=18)
    meterfile = config.get("domoticz", "meterfile", fallback="meterstand.txt")
    domoticz_idx = config.getint("domoticz", "idx", fallback=0)
    MQTT_TOPIC_DOMOTICZ_IN = config.get("mqtt", "domoticzin", fallback="domoticz/in")

    # Script naam (voor topics)
    script_name = config.get("main", "script_name", fallback="gpio2mqtt")

    # Setup lampen (voor MQTT)
    setup_lights(config)

    logger.info(f"Start watermeter puls op GPIO {gpio_pin}")
    logger.info(f"Meterbestand: {meterfile}")
    logger.info(f"Domoticz IDX: {domoticz_idx}")
    logger.info(f"MQTT broker: {mqtt_broker}:{mqtt_port}")
    logger.info(f"Home Assistant discovery topic: {hatopic}")
    logger.info(f"Script naam: {script_name}")

    # MQTT setup
    mqtt_client = mqtt.Client()
    if mqtt_user and mqtt_pass:
        mqtt_client.username_pw_set(mqtt_user, mqtt_pass)

    mqtt_client.user_data_set(config)
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = handle_mqtt_message
    mqtt_client.on_disconnect = on_disconnect

    mqtt_client.connect(mqtt_broker, mqtt_port, 60)
    mqtt_client.loop_start()

    # Initialiseer reconnect check
    global last_check
    last_check = time.time()

    # Setup watermeter puls input
    button = Button(gpio_pin, pull_up=True, bounce_time=0.05)
    button.when_pressed = pulse_detected

    logger.info("Running, press CTRL+C to exit")

    while running:
        if time.time() - last_check > reconnect_interval:
            if not mqtt_client.is_connected():
                logger.info("MQTT connection lost, attempting to reconnect...")
                try:
                    mqtt_client.reconnect()
                except Exception as e:
                    logger.error(f"Failed to reconnect to MQTT broker: {e}")
            last_check = time.time()
        time.sleep(1)

def signal_handler(sig, frame):
    global running
    logger.info('Exiting gracefully')
    running = False
    if mqtt_client:
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    run()

