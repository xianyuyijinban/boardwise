# 智能药箱系统

## 1. 项目概述

本项目基于 STM32G431RBT6、MPU6050、AHT20 和 ESP-01S，实现家用药箱的环境监测、姿态/跌落检测、箱盖行为识别、蜂鸣器本地告警，以及通过 MQTT 与 Android APP 联动。

当前协议已经完成一次收敛：
- APP 侧不再显示 `pressure` / `altitude`
- 设备上报新增 `behavior` 与 `risk` 对象
- 环境异常、跌落、箱盖异常事件统一走 `medicine/{device_id}/alert`
- APP 只保留 EMQX/通用 MQTT 接入流程

## 2. 已完成功能

### 2.1 环境监测与告警
- AHT20 采集温度、湿度。
- BMP280 视为可选外接器件；未接入时固件会自动禁用气压/海拔采集，不影响温湿度告警、姿态检测和 LCD 刷新。
- 额定值可由 APP 通过 MQTT 下发：`set_env_rated`。
- 用户未设置时默认额定值为 `15.0°C / 50.0%RH`。
- 异常阈值按额定值 `±30%` 计算。
- 当温湿度任一项超限时：
  - 立即发布 `env_abnormal`
  - 本地蜂鸣器以 `2.7kHz` 发出 `3` 次提示音
  - 每次提示间隔 `1s`
- 恢复正常后发布 `env_recovered`。

### 2.2 跌落检测与告警
- 基于 MPU6050 三轴加速度与姿态数据进行跌落筛选。
- 当加速度大于 `6G` 且持续超过 `20ms` 时，设备判定为跌落并立即上报 `drop_detected`。
- 跌落报警音策略：
  - 单次持续鸣叫 `5s`
  - 间隔 `3s`
  - 共循环 `3` 次后停止
- 报警期间若用户按下 `KEY2(PB15)`：
  - 立即停止本轮报警
  - 发布 `drop_alarm_cancelled`
  - 事件中带 `stop_push=1`，APP 收到后停止继续推送该异常

### 2.3 箱盖行为识别
- 固件输出 `behavior` 字段，当前包括：
  - `lid_state`
  - `open_duration_ms`
  - `open_abnormal`
  - `open_reason`
- 设备会在以下时机主动发布行为事件：
  - `lid_abnormal_opened`
  - `lid_open_timeout`
  - `lid_closed`

### 2.4 指示灯与本地交互
- `LED1(PA3)`：网络状态指示。
  - WiFi 已连但 MQTT 未连：快速闪烁
  - MQTT 已连：慢闪
  - 模块错误：常亮
  - 未连接：熄灭
- `LED2(PA4)`：控制板总线/外设健康指示。
  - 任一总线外设故障：闪烁
  - 正常运行：常亮
- `KEY1(PC6)`：LCD 页面切换。
- `KEY2(PB15)`：跌落报警消警。
- `KEY3(PB14)`：蜂鸣器总开关。

## 3. 硬件连接摘要

| 模块 | 引脚/接口 | 说明 |
|------|-----------|------|
| 无源蜂鸣器 | `PC0 / TIM1_CH1(PWM1)` | 告警提示音，当前驱动频率 `2.7kHz` |
| LED1 | `PA3` | WiFi/MQTT 状态 |
| LED2 | `PA4` | 总线/外设故障状态 |
| KEY1 | `PC6` | 显示翻页 |
| KEY2 | `PB15` | 跌落报警消警 |
| KEY3 | `PB14` | 蜂鸣器开关 |
| KEY4 | `PB13` | 预留 |
| MPU6050 | `I2C2 (PA8/PA9)` | 姿态与加速度 |
| AHT20 | `I2C3 (PC8/PC9)` | 温湿度 |
| BMP280 | `I2C3 (PC8/PC9)` | 仅保留驱动，可用于温度融合；当前不向 APP 上报气压/海拔 |
| ESP-01S | `USART3 (PB10/PB11)` | WiFi/MQTT 通信 |
| ESP EN | `PD2` | 模块使能 |
| ESP RST | `PC12` | 模块复位 |
| ESP IO0 | `PB3` | 模式控制 |

## 4. WiFi 与 MQTT

### 4.1 ESP8266 通信方式

ESP8266 当前走 AT 指令驱动，代码位于 `MDK-ARM/code/esp8266.c`。
USART3 接收链路采用“单字节中断优先 + 阻塞轮询兜底”的方式；当中断接收处于忙状态时，固件不会再强制刷新 UART FIFO，避免把 `AT` 响应误清掉。
常用指令包括：
- WiFi：`AT+CWMODE`、`AT+CWJAP`
- MQTT AT 模式：`AT+MQTTUSERCFG`、`AT+MQTTCONN`、`AT+MQTTPUB`、`AT+MQTTSUB`
- 当前云端默认优先走 MQTT AT 直连，不再优先激活 raw socket 路径。

### 4.2 是否自动连接 WiFi

会自动连接，但前提是固件里已经配置好 WiFi 参数。当前默认配置位于 `MDK-ARM/code/app_tasks.h`：

```c
#define WIFI_SSID           "Galaxy Note 7 Ultra"
#define WIFI_PASSWORD       "12345678y"
#define MQTT_BROKER_IP      "jaf12a6c.ala.cn-hangzhou.emqxsl.cn"
#define MQTT_BROKER_PORT    8883
#define MQTT_CLIENT_ID      "SmartBox"
#define MQTT_USERNAME       "yunmenglin"
#define MQTT_PASSWORD       "12345678y"
```

上电后 `MQTTTask` 会先连 WiFi，再连 Broker。

### 4.3 当前联调链路

当前板端默认直接接入云端 EMQX：
- 首选：`jaf12a6c.ala.cn-hangzhou.emqxsl.cn:8883`
- 次选：`jaf12a6c.ala.cn-hangzhou.emqxsl.cn:8084`，路径 `/mqtt`

固件会优先按 MQTT AT 云端候选顺序尝试：
- `8883/TLS`（scheme `2`）
- `8084/WSS`（scheme `7`，path `/mqtt`）

只有在非云端端口场景下，代码中才保留 raw socket 兼容逻辑；当前默认联调链路不走本地代理。

## 5. MQTT 主题

| 主题 | 方向 | 说明 |
|------|------|------|
| `medicine/box001/sensors` | 药箱 -> APP | 周期传感器上报 |
| `medicine/box001/status` | 药箱 -> APP | 在线/离线状态 |
| `medicine/box001/control` | APP -> 药箱 | 控制命令 |
| `medicine/box001/control/response` | 药箱 -> APP | 控制应答 |
| `medicine/box001/alert` | 药箱 -> APP | 环境/跌落/箱盖事件 |

协议详情见 [APP_INTERFACE.md](./APP_INTERFACE.md)。

## 6. 传感器上报字段

当前 `sensors` 主题上报结构示例：

```json
{
  "timestamp": 123456789,
  "device_id": "medicine_box_001",
  "state": "closed",
  "environment": {
    "temperature": 25.30,
    "humidity": 55.50
  },
  "environment_limits": {
    "temperature_rated": 15.00,
    "temperature_low": 10.50,
    "temperature_high": 19.50,
    "humidity_rated": 50.00,
    "humidity_low": 35.00,
    "humidity_high": 65.00
  },
  "motion": {
    "accel_x": 0.015,
    "accel_y": -0.008,
    "accel_z": 0.995,
    "gyro_x": 0.50,
    "gyro_y": -0.30,
    "gyro_z": 0.10,
    "pitch": 2.15,
    "roll": -1.02,
    "vibration": 0.005
  },
  "behavior": {
    "lid_state": "closed",
    "open_duration_ms": 0,
    "open_abnormal": 0,
    "open_reason": "normal"
  },
  "risk": {
    "env_level": "normal",
    "drop_state": "none"
  },
  "alerts": {
    "env_abnormal": 0,
    "temperature_abnormal": 0,
    "humidity_abnormal": 0
  },
  "valid": 1
}
```

说明：
- `pressure` 与 `altitude` 已从设备到 APP 的协议里移除。
- `state` 保留粗粒度箱体状态，`behavior` 用于更细的箱盖行为，`risk` 用于风险等级表达。

## 7. APP 适配状态

Android APP 已同步适配当前协议与交互：
- 主页改为浅蓝 + 白色家用风格
- 应用图标改为蓝白药箱风格
- 状态区分 `MQTT 已连接` 与 `设备已在线`
- 未收到设备状态前显示 `尚未连接`
- 左上角刷新按钮仅在 MQTT 已连接且当前不处于连接中/刷新中时可点击，未连接时不会再触发白屏卡死
- 控制区为一行三个模块：`立即上报`、`上报间隔`、`额定值`
- 蜂鸣器开关单独成块显示
- 已移除气压/海拔展示
- 支持环境异常、跌落、箱盖行为、消警事件通知
- APP 挂后台后 MQTT 不因 Activity 销毁主动断开

## 8. 验证结果

本次收尾后已重新验证：

### 8.1 固件
- Keil 构建：`MDK-ARM/Smartbox.uvprojx`
- 结果：`0 Error(s), 0 Warning(s)`
- host tests：
  - `test_safety_env_risk: PASS`
  - `test_lid_behavior: PASS`
  - `test_drop_filter: PASS`

### 8.2 APP
- 单元测试：`./gradlew.bat :app:testDebugUnitTest`
- APK 构建：`./gradlew.bat :app:assembleDebug`
- 结果：均通过

## 9. 目录说明

```text
SmartMedicineBox/
├── APP_INTERFACE.md                  # 顶层 APP 协议文档
├── README.md                         # 顶层项目说明
├── MDK-ARM/
│   ├── Smartbox.uvprojx              # Keil 工程
│   └── code/
│       ├── app_tasks.c/h             # FreeRTOS 任务与告警逻辑
│       ├── sensor_manager.c/h        # 传感器采集、融合、JSON 输出
│       ├── safety_logic.h            # 环境/箱盖/跌落纯逻辑
│       └── esp8266.c/h               # ESP8266 AT/MQTT 驱动
├── SmartMedicineBox/
│   ├── README.md                     # 镜像说明文档
│   └── App/APP_INTERFACE.md          # 镜像协议文档
└── tools/
    └── mqtt_tls_proxy.py             # 本地 MQTT TLS 代理
```
