# GPIO2MQTT Docker

This project is a Python application that uses GPIO pins on a Raspberry Pi to detect pulses from a water meter and send this data via MQTT to Domoticz and Home Assistant. It also supports switching lamps via MQTT commands.

## Features

- **Water meter monitoring**: Detects pulses on a GPIO pin and sends meter readings to Domoticz.
- **Lamp control**: Switches GPIO-controlled lamps on/off via MQTT messages from Home Assistant.
- **MQTT reconnect**: Periodically checks the MQTT connection and attempts automatic reconnection on loss.
- **Home Assistant discovery**: Automatically publishes discovery messages for lamps.
- **Docker support**: Can be run in a Docker container for easy deployment.

## Requirements

- Raspberry Pi with GPIO pins (e.g., Raspberry Pi 4).
- Docker installed.
- MQTT broker (e.g., Mosquitto).
- Domoticz (for water meter integration).
- Home Assistant (for lamp control, optional).

## Installation

### Docker Installation

1. Build the Docker image:
   ```
   docker build -t gpio2mqtt .
   ```

2. Run the container (replace `/path/to/config` with your config directory):
   ```
   docker run -d --privileged --device /dev/gpiomem -v /path/to/config:/app gpio2mqtt
   ```

   - `--privileged` and `--device /dev/gpiomem` are required for GPIO access in Docker.

#### Using Docker Compose

Create a `docker-compose.yml` file in the project root with the following content:

```yaml
version: '3.8'
services:
  gpio2mqtt:
    build:
      context: ./gpio2mqtt
    container_name: gpio2mqtt
    volumes:
      - ./gpio2mqtt:/app        # Your script, config & meter file available
      - /sys:/sys               # Required for GPIO access
      - /dev:/dev
    devices:
      - /dev/gpiomem
    restart: unless-stopped
    environment:
      - PYTHONUNBUFFERED=1
    privileged: true
```

Then run:
```
docker-compose up -d
```

## Configuration

Edit `config.ini` (based on `config.ini.example`) with the following sections:

- **[mqtt]**: Broker details, authentication, QoS, retain.
- **[domoticz]**: GPIO pin for water meter, Domoticz IDX, meter file.
- **[main]**: Script name, list of lamps, GPIO pins and active_high settings per lamp.

Example:
```
[mqtt]
broker = 192.168.1.100
port = 1883
username = my_user
password = my_password

[domoticz]
gpio_pin = 18
idx = 123

[main]
lampen = Lamp1,Lamp2
gpio_Lamp1 = 14
active_high_Lamp1 = False
```

## Usage

- The script starts automatically upon execution.
- Water meter pulses are detected and sent to Domoticz.
- Lamps can be switched via MQTT topics like `gpio2mqtt/light/Lamp1/set` with payload "ON" or "OFF".
- Logs are displayed in the console.

