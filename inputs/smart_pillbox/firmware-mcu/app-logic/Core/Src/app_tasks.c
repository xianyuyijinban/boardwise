/**
  ******************************************************************************
  * @file    app_tasks.c
  * @brief   FreeRTOS任务实现
  ******************************************************************************
  */
#include "app_tasks.h"
#include "sensor_manager.h"
#include "esp8266.h"
#include "tim.h"
#include "usart.h"
#include "spi.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* 任务句柄 */
osThreadId_t sensorTaskHandle = NULL;
osThreadId_t mqttTaskHandle = NULL;
osThreadId_t displayTaskHandle = NULL;
osThreadId_t buzzerTaskHandle = NULL;

/* 信号量/队列 */
static osSemaphoreId_t mqttPublishSem;
static osSemaphoreId_t buzzerAlertSem;

/* 运行标志 */
static volatile uint8_t system_ready = 0;
static volatile uint8_t env_alert_latched = 0U;
static volatile uint8_t env_alert_pending = 0U;
static volatile uint8_t env_recover_pending = 0U;
static volatile uint8_t env_alert_reason_flags = 0U;
static volatile uint8_t app_bus_fault_flags = 0U;
static volatile uint8_t drop_alert_latched = 0U;
static volatile uint8_t drop_alert_pending = 0U;
static volatile uint8_t drop_alarm_request_pending = 0U;
static volatile uint8_t drop_alarm_cancel_pending = 0U;
static volatile uint32_t drop_alert_timestamp = 0U;
static volatile uint32_t drop_alarm_cancel_timestamp = 0U;
static volatile float drop_alert_accel_x = 0.0f;
static volatile float drop_alert_accel_y = 0.0f;
static volatile float drop_alert_accel_z = 0.0f;
static volatile float drop_alert_accel_magnitude = 0.0f;

typedef struct {
    uint8_t key_armed;
    uint8_t key_pressed_latched;
    uint32_t key_press_tick;
} KeyDebounceState_t;

#define APP_BUS_FAULT_SENSOR   0x01U
#define APP_BUS_FAULT_UART3    0x02U
#define APP_BUS_FAULT_SPI1     0x04U
#define LED2_FAULT_BLINK_MS    200U

static void App_SetBusFaultFlag(uint8_t mask, uint8_t active)
{
    if (active != 0U) {
        app_bus_fault_flags |= mask;
    } else {
        app_bus_fault_flags &= (uint8_t)(~mask);
    }
}

static uint8_t App_ExtractJsonString(const char *payload, const char *key, char *out, uint16_t out_size)
{
    char pattern[32];
    const char *cursor;
    const char *value_start;
    const char *value_end;
    size_t value_len;

    if ((payload == NULL) || (key == NULL) || (out == NULL) || (out_size < 2U)) {
        return 1U;
    }

    snprintf(pattern, sizeof(pattern), "\"%s\"", key);
    cursor = strstr(payload, pattern);
    if (cursor == NULL) {
        return 1U;
    }

    cursor = strchr(cursor + strlen(pattern), ':');
    if (cursor == NULL) {
        return 1U;
    }
    cursor++;

    while ((*cursor == ' ') || (*cursor == '\t')) {
        cursor++;
    }

    if (*cursor != '"') {
        return 1U;
    }
    value_start = cursor + 1;
    value_end = strchr(value_start, '"');
    if (value_end == NULL) {
        return 1U;
    }

    value_len = (size_t)(value_end - value_start);
    if (value_len >= out_size) {
        return 1U;
    }

    memcpy(out, value_start, value_len);
    out[value_len] = '\0';
    return 0U;
}

static uint8_t App_ExtractJsonFloat(const char *payload, const char *key, float *out_value)
{
    char pattern[32];
    const char *cursor;
    char *value_end = NULL;
    float parsed_value;

    if ((payload == NULL) || (key == NULL) || (out_value == NULL)) {
        return 1U;
    }

    snprintf(pattern, sizeof(pattern), "\"%s\"", key);
    cursor = strstr(payload, pattern);
    if (cursor == NULL) {
        return 1U;
    }

    cursor = strchr(cursor + strlen(pattern), ':');
    if (cursor == NULL) {
        return 1U;
    }
    cursor++;

    while ((*cursor == ' ') || (*cursor == '\t')) {
        cursor++;
    }

    parsed_value = strtof(cursor, &value_end);
    if ((value_end == cursor) || (value_end == NULL)) {
        return 1U;
    }

    *out_value = parsed_value;
    return 0U;
}

static uint8_t App_ParseRatedValues(const char *payload, float *temperature, float *humidity)
{
    uint8_t temp_found = 0U;
    uint8_t hum_found = 0U;

    if ((payload == NULL) || (temperature == NULL) || (humidity == NULL)) {
        return 1U;
    }

    if (App_ExtractJsonFloat(payload, "temperature", temperature) == 0U) {
        temp_found = 1U;
    } else if (App_ExtractJsonFloat(payload, "temp", temperature) == 0U) {
        temp_found = 1U;
    } else if (App_ExtractJsonFloat(payload, "rated_temperature", temperature) == 0U) {
        temp_found = 1U;
    } else if (App_ExtractJsonFloat(payload, "temperature_rated", temperature) == 0U) {
        temp_found = 1U;
    }

    if (App_ExtractJsonFloat(payload, "humidity", humidity) == 0U) {
        hum_found = 1U;
    } else if (App_ExtractJsonFloat(payload, "hum", humidity) == 0U) {
        hum_found = 1U;
    } else if (App_ExtractJsonFloat(payload, "rated_humidity", humidity) == 0U) {
        hum_found = 1U;
    } else if (App_ExtractJsonFloat(payload, "humidity_rated", humidity) == 0U) {
        hum_found = 1U;
    }

    return (uint8_t)((temp_found != 0U) && (hum_found != 0U) ? 0U : 1U);
}

static uint8_t App_PublishControlResponse(const char *payload)
{
    if (ESP8266_GetState() != ESP8266_STATE_MQTT_CONNECTED) {
        return 1U;
    }

    return ESP8266_MQTT_Publish(MQTT_TOPIC_CONTROL_RESPONSE, payload, 0, 0);
}

static void App_OnMqttMessage(const char *topic, const char *payload)
{
    char cmd[32];
    char response[192];
    float rated_temperature;
    float rated_humidity;
    float current_rated_temperature;
    float current_rated_humidity;
    uint8_t has_cmd;
    uint8_t is_set_command;

    if ((topic == NULL) || (payload == NULL)) {
        return;
    }

    if (strcmp(topic, MQTT_TOPIC_CONTROL) != 0) {
        return;
    }

    has_cmd = (uint8_t)(App_ExtractJsonString(payload, "cmd", cmd, sizeof(cmd)) == 0U);
    is_set_command = (uint8_t)(has_cmd &&
                               ((strcmp(cmd, "set_env_rated") == 0) ||
                                (strcmp(cmd, "set_rated_env") == 0) ||
                                (strcmp(cmd, "set_threshold") == 0)));

    if (has_cmd && (strcmp(cmd, "publish_now") == 0)) {
        (void)osSemaphoreRelease(mqttPublishSem);
        snprintf(response, sizeof(response),
                 "{\"cmd\":\"publish_now\",\"result\":\"ok\",\"timestamp\":%lu}",
                 HAL_GetTick());
        (void)App_PublishControlResponse(response);
        return;
    }

    if (is_set_command || (has_cmd == 0U)) {
        if (App_ParseRatedValues(payload, &rated_temperature, &rated_humidity) != 0U) {
            if (has_cmd != 0U) {
                snprintf(response, sizeof(response),
                         "{\"cmd\":\"%s\",\"result\":\"error\",\"error_msg\":\"invalid rated values\"}",
                         cmd);
                (void)App_PublishControlResponse(response);
            }
            return;
        }

        if (SensorManager_SetRatedEnvironment(rated_temperature, rated_humidity) != 0U) {
            snprintf(response, sizeof(response),
                     "{\"cmd\":\"set_env_rated\",\"result\":\"error\",\"error_msg\":\"value out of range\"}");
            (void)App_PublishControlResponse(response);
            return;
        }

        SensorManager_GetRatedEnvironment(&current_rated_temperature, &current_rated_humidity);
        snprintf(response, sizeof(response),
                 "{\"cmd\":\"set_env_rated\",\"result\":\"ok\",\"rated_temperature\":%.2f,\"rated_humidity\":%.2f,\"timestamp\":%lu}",
                 current_rated_temperature, current_rated_humidity, HAL_GetTick());
        (void)App_PublishControlResponse(response);
        return;
    }

    snprintf(response, sizeof(response),
             "{\"cmd\":\"%s\",\"result\":\"error\",\"error_msg\":\"unsupported command\"}",
             cmd);
    (void)App_PublishControlResponse(response);
}

static uint8_t App_PublishPendingAlerts(void)
{
    char payload[320];
    EnvironmentAlertStatus_t env_status;
    MedicineBoxData_t data;

    if (ESP8266_GetState() != ESP8266_STATE_MQTT_CONNECTED) {
        return 1U;
    }

    if (env_alert_pending != 0U) {
        SensorManager_GetEnvAlertStatus(&env_status);
        SensorManager_GetData(&data);

        snprintf(payload, sizeof(payload),
                 "{\"event\":\"env_abnormal\",\"timestamp\":%lu,\"temperature\":%.2f,\"humidity\":%.2f,"
                 "\"rated_temperature\":%.2f,\"rated_humidity\":%.2f,"
                 "\"temperature_abnormal\":%d,\"humidity_abnormal\":%d}",
                 data.timestamp,
                 data.env.temperature,
                 data.env.humidity,
                 env_status.rated_temperature,
                 env_status.rated_humidity,
                 (env_alert_reason_flags & 0x01U) ? 1 : 0,
                 (env_alert_reason_flags & 0x02U) ? 1 : 0);

        if (ESP8266_MQTT_Publish(MQTT_TOPIC_ALERT, payload, 0, 0) == 0U) {
            env_alert_pending = 0U;
        }
    }

    if (env_recover_pending != 0U) {
        SensorManager_GetEnvAlertStatus(&env_status);
        SensorManager_GetData(&data);

        snprintf(payload, sizeof(payload),
                 "{\"event\":\"env_recovered\",\"timestamp\":%lu,\"temperature\":%.2f,\"humidity\":%.2f,"
                 "\"rated_temperature\":%.2f,\"rated_humidity\":%.2f}",
                 data.timestamp,
                 data.env.temperature,
                 data.env.humidity,
                 env_status.rated_temperature,
                 env_status.rated_humidity);

        if (ESP8266_MQTT_Publish(MQTT_TOPIC_ALERT, payload, 0, 0) == 0U) {
            env_recover_pending = 0U;
        }
    }

    if (drop_alert_pending != 0U) {
        snprintf(payload, sizeof(payload),
                 "{\"event\":\"drop_detected\",\"timestamp\":%lu,"
                 "\"accel_x\":%.3f,\"accel_y\":%.3f,\"accel_z\":%.3f,"
                 "\"accel_magnitude\":%.3f,\"threshold_g\":%.1f,\"duration_ms\":%u}",
                 drop_alert_timestamp,
                 drop_alert_accel_x,
                 drop_alert_accel_y,
                 drop_alert_accel_z,
                 drop_alert_accel_magnitude,
                 DROP_ACCEL_THRESHOLD_G,
                 (unsigned int)DROP_ACCEL_DURATION_MS);

        if (ESP8266_MQTT_Publish(MQTT_TOPIC_ALERT, payload, 0, 0) == 0U) {
            drop_alert_pending = 0U;
        }
    }

    if (drop_alarm_cancel_pending != 0U) {
        snprintf(payload, sizeof(payload),
                 "{\"event\":\"drop_alarm_cancelled\",\"timestamp\":%lu,"
                 "\"source\":\"key2\",\"stop_push\":1}",
                 drop_alarm_cancel_timestamp);

        if (ESP8266_MQTT_Publish(MQTT_TOPIC_ALERT, payload, 0, 0) == 0U) {
            drop_alarm_cancel_pending = 0U;
        }
    }

    return 0U;
}

static void Buzzer_StartTone(void)
{
    uint32_t pulse = (htim1.Init.Period + 1U) / 2U;
    if (pulse == 0U) {
        pulse = 1U;
    }
    __HAL_TIM_SET_COMPARE(&htim1, TIM_CHANNEL_1, pulse);
    (void)HAL_TIM_PWM_Start(&htim1, TIM_CHANNEL_1);
}

static void Buzzer_StopTone(void)
{
    (void)HAL_TIM_PWM_Stop(&htim1, TIM_CHANNEL_1);
    __HAL_TIM_SET_COMPARE(&htim1, TIM_CHANNEL_1, 0U);
}

static uint8_t App_UpdateKey2Pressed(KeyDebounceState_t *state)
{
    uint32_t now;
    uint8_t key_high;

    if (state == NULL) {
        return 0U;
    }

    now = HAL_GetTick();
    key_high = (HAL_GPIO_ReadPin(KEY2_GPIO_Port, KEY2_Pin) == GPIO_PIN_SET) ? 1U : 0U;

    if (state->key_pressed_latched == 0U) {
        if (key_high != 0U) {
            if (state->key_armed == 0U) {
                state->key_armed = 1U;
                state->key_press_tick = now;
            } else if ((uint32_t)(now - state->key_press_tick) >= KEY2_DEBOUNCE_MS) {
                state->key_pressed_latched = 1U;
                state->key_armed = 0U;
                return 1U;
            }
        } else {
            state->key_armed = 0U;
        }
    } else if (key_high == 0U) {
        state->key_pressed_latched = 0U;
    }

    return 0U;
}

static uint8_t Buzzer_WaitWithCancel(uint32_t wait_ms, KeyDebounceState_t *key_state)
{
    uint32_t start_tick;

    if (key_state == NULL) {
        return 0U;
    }

    start_tick = HAL_GetTick();
    while ((uint32_t)(HAL_GetTick() - start_tick) < wait_ms) {
        uint32_t elapsed = (uint32_t)(HAL_GetTick() - start_tick);
        uint32_t remaining = (wait_ms > elapsed) ? (wait_ms - elapsed) : 0U;
        uint32_t delay_ms = (remaining > BUZZER_POLL_INTERVAL_MS) ? BUZZER_POLL_INTERVAL_MS : remaining;

        if (App_UpdateKey2Pressed(key_state) != 0U) {
            return 1U;
        }
        if (delay_ms > 0U) {
            osDelay(delay_ms);
        }
    }

    return 0U;
}

/**
  * @brief  应用初始化
  */
void App_Init(void)
{
    printf("[APP] System Initializing...\r\n");
    
    /* 初始化传感器 */
    SensorManager_Init();
    printf("[APP] Sensors Initialized\r\n");
    
    /* 初始化ESP8266 */
    ESP8266_Init();
    printf("[APP] ESP8266 Initialized\r\n");
    
    mqttPublishSem = osSemaphoreNew(1, 0, NULL);
    buzzerAlertSem = osSemaphoreNew(1, 0, NULL);
    ESP8266_RegisterMQTTMessageCallback(App_OnMqttMessage);
    Buzzer_StopTone();
    
    system_ready = 1;
    printf("[APP] System Ready\r\n");
}

/**
  * @brief  启动所有任务
  */
void App_StartTasks(void)
{
    const osThreadAttr_t sensorTask_attr = {
        .name = "SensorTask",
        .priority = SENSOR_TASK_PRIORITY,
        .stack_size = SENSOR_TASK_STACK_SIZE * 4,
    };
    
    const osThreadAttr_t mqttTask_attr = {
        .name = "MQTTTask",
        .priority = MQTT_TASK_PRIORITY,
        .stack_size = MQTT_TASK_STACK_SIZE * 4,
    };
    
    const osThreadAttr_t displayTask_attr = {
        .name = "DisplayTask",
        .priority = DISPLAY_TASK_PRIORITY,
        .stack_size = DISPLAY_TASK_STACK_SIZE * 4,
    };
    
    const osThreadAttr_t ledTask_attr = {
        .name = "LEDTask",
        .priority = LED_TASK_PRIORITY,
        .stack_size = LED_TASK_STACK_SIZE * 4,
    };

    const osThreadAttr_t buzzerTask_attr = {
        .name = "BuzzerTask",
        .priority = BUZZER_TASK_PRIORITY,
        .stack_size = BUZZER_TASK_STACK_SIZE * 4,
    };
    
    sensorTaskHandle = osThreadNew(SensorTask, NULL, &sensorTask_attr);
    mqttTaskHandle = osThreadNew(MQTTTask, NULL, &mqttTask_attr);
    displayTaskHandle = osThreadNew(DisplayTask, NULL, &displayTask_attr);
    buzzerTaskHandle = osThreadNew(BuzzerTask, NULL, &buzzerTask_attr);
    osThreadNew(LEDTask, NULL, &ledTask_attr);
}

/**
  * @brief  传感器采集任务
  * @param  argument: 任务参数
  */
void SensorTask(void *argument)
{
    EnvironmentAlertStatus_t env_status;
    MedicineBoxData_t sensor_data;
    uint8_t sensor_read_result;
    uint32_t last_mqtt_tick = 0;
    uint8_t drop_over_threshold = 0U;
    uint32_t drop_over_threshold_start_tick = 0U;
    
    printf("[SensorTask] Started\r\n");
    
    for (;;) {
        /* 读取所有传感器数据 */
        sensor_read_result = SensorManager_ReadAll();
        App_SetBusFaultFlag(APP_BUS_FAULT_SENSOR, (sensor_read_result != 0U) ? 1U : 0U);

        SensorManager_GetEnvAlertStatus(&env_status);
        SensorManager_GetData(&sensor_data);
        if (env_status.is_abnormal != 0U) {
            uint8_t reason_flags = 0U;
            if (env_status.temperature_abnormal != 0U) {
                reason_flags |= 0x01U;
            }
            if (env_status.humidity_abnormal != 0U) {
                reason_flags |= 0x02U;
            }
            env_alert_reason_flags = reason_flags;

            if (env_alert_latched == 0U) {
                env_alert_latched = 1U;
                env_alert_pending = 1U;
                (void)osSemaphoreRelease(buzzerAlertSem);
            }
        } else if (env_alert_latched != 0U) {
            env_alert_latched = 0U;
            env_alert_reason_flags = 0U;
            env_recover_pending = 1U;
        }

        if ((sensor_data.is_valid != 0U) && (drop_alert_latched == 0U)) {
            float accel_sq = (sensor_data.motion.accel_x * sensor_data.motion.accel_x) +
                             (sensor_data.motion.accel_y * sensor_data.motion.accel_y) +
                             (sensor_data.motion.accel_z * sensor_data.motion.accel_z);

            if (accel_sq >= DROP_ACCEL_THRESHOLD_SQ) {
                if (drop_over_threshold == 0U) {
                    drop_over_threshold = 1U;
                    drop_over_threshold_start_tick = sensor_data.timestamp;
                } else if ((uint32_t)(sensor_data.timestamp - drop_over_threshold_start_tick) >= DROP_ACCEL_DURATION_MS) {
                    drop_alert_latched = 1U;
                    drop_alert_pending = 1U;
                    drop_alarm_request_pending = 1U;
                    drop_alert_timestamp = sensor_data.timestamp;
                    drop_alert_accel_x = sensor_data.motion.accel_x;
                    drop_alert_accel_y = sensor_data.motion.accel_y;
                    drop_alert_accel_z = sensor_data.motion.accel_z;
                    drop_alert_accel_magnitude = sqrtf(accel_sq);
                    drop_over_threshold = 0U;
                    (void)osSemaphoreRelease(mqttPublishSem);
                    (void)osSemaphoreRelease(buzzerAlertSem);
                }
            } else {
                drop_over_threshold = 0U;
            }
        } else {
            drop_over_threshold = 0U;
        }
        
        /* 检查是否需要触发MQTT发布 (每5秒) */
        if ((HAL_GetTick() - last_mqtt_tick) >= MQTT_PUBLISH_INTERVAL_MS) {
            (void)osSemaphoreRelease(mqttPublishSem);
            last_mqtt_tick = HAL_GetTick();
        }
        
        /* 100ms采样间隔 */
        osDelay(SENSOR_SAMPLE_INTERVAL_MS);
    }
}

/**
  * @brief  MQTT通信任务
  * @param  argument: 任务参数
  */
void MQTTTask(void *argument)
{
    uint8_t wifi_connected = 0;
    uint8_t mqtt_connected = 0;
    uint8_t retry_count = 0;
    char json_buffer[512];
    
    printf("[MQTTTask] Started\r\n");
    
    /* 等待系统就绪 */
    osDelay(1000);
    
    for (;;) {
        /* 状态机处理 */
        switch (ESP8266_GetState()) {
            case ESP8266_STATE_RESET:
            case ESP8266_STATE_INIT:
                /* 初始化WiFi */
                printf("[MQTT] Initializing WiFi...\r\n");
                if (ESP8266_WiFi_Init() == 0) {
                    printf("[MQTT] WiFi AT OK\r\n");
                }
                osDelay(500);
                break;
                
            case ESP8266_STATE_WIFI_CONNECTING:
                /* 等待连接完成 */
                osDelay(500);
                break;
                
            case ESP8266_STATE_WIFI_CONNECTED:
                /* WiFi已连接，连接MQTT */
                if (!mqtt_connected) {
                    printf("[MQTT] Connecting to broker...\r\n");
                    
                    if (ESP8266_MQTT_Init(MQTT_BROKER_IP, MQTT_BROKER_PORT) == 0) {
                        if (ESP8266_MQTT_ConnectToBroker(MQTT_BROKER_IP, MQTT_BROKER_PORT) == 0) {
                            printf("[MQTT] Connected to %s:%d\r\n", MQTT_BROKER_IP, MQTT_BROKER_PORT);
                            
                            /* 订阅控制主题 */
                            ESP8266_MQTT_Subscribe(MQTT_TOPIC_CONTROL, 0);
                            
                            /* 发布上线消息 */
                            ESP8266_MQTT_Publish(MQTT_TOPIC_STATUS, "online", 0, 1);
                            
                            mqtt_connected = 1;
                            retry_count = 0;
                        }
                    }
                    
                    if (!mqtt_connected) {
                        retry_count++;
                        if (retry_count >= 5) {
                            printf("[MQTT] Connection failed, reset...\r\n");
                            ESP8266_Reset();
                            retry_count = 0;
                        }
                        osDelay(3000);
                    }
                }
                break;
                
            case ESP8266_STATE_MQTT_CONNECTED:
                ESP8266_ProcessRxData();
                (void)App_PublishPendingAlerts();

                /* MQTT已连接，等待发布信号 */
                if (osSemaphoreAcquire(mqttPublishSem, 100) == osOK) {
                    /* 生成JSON数据 */
                    SensorManager_CreateJSON(json_buffer, sizeof(json_buffer));
                    
                    /* 发布数据 */
                    if (ESP8266_MQTT_Publish(MQTT_TOPIC_DATA, json_buffer, 0, 0) == 0) {
                        printf("[MQTT] Published: %s\r\n", json_buffer);
                    } else {
                        printf("[MQTT] Publish failed\r\n");
                        mqtt_connected = 0;
                    }
                }
                break;
                
            case ESP8266_STATE_ERROR:
                printf("[MQTT] Error state, resetting...\r\n");
                ESP8266_Reset();
                wifi_connected = 0;
                mqtt_connected = 0;
                osDelay(2000);
                break;
                
            default:
                break;
        }
        
        /* WiFi连接管理 */
        if (!wifi_connected && ESP8266_GetState() < ESP8266_STATE_WIFI_CONNECTING) {
            printf("[MQTT] Connecting to WiFi: %s\r\n", WIFI_SSID);
            if (ESP8266_WiFi_Connect(WIFI_SSID, WIFI_PASSWORD) == 0) {
                printf("[MQTT] WiFi Connected\r\n");
                wifi_connected = 1;
            } else {
                printf("[MQTT] WiFi Connect failed, retry...\r\n");
                osDelay(3000);
            }
        }
        
        /* 如果WiFi断开，重置状态 */
        if (wifi_connected && ESP8266_WiFi_IsConnected() == 0) {
            if (ESP8266_GetState() == ESP8266_STATE_WIFI_CONNECTED ||
                ESP8266_GetState() == ESP8266_STATE_MQTT_CONNECTED) {
                printf("[MQTT] WiFi disconnected\r\n");
                wifi_connected = 0;
                mqtt_connected = 0;
            }
        }

        {
            ESP8266_State_t current_state = ESP8266_GetState();
            uint8_t uart_fault_active = (uint8_t)((current_state == ESP8266_STATE_ERROR) ||
                                                  (huart3.gState == HAL_UART_STATE_RESET));
            uint8_t spi_fault_active = (uint8_t)(hspi1.State == HAL_SPI_STATE_RESET);
            App_SetBusFaultFlag(APP_BUS_FAULT_UART3, uart_fault_active);
            App_SetBusFaultFlag(APP_BUS_FAULT_SPI1, spi_fault_active);
        }
        
        osDelay(100);
    }
}

void BuzzerTask(void *argument)
{
    uint8_t beep_index;
    uint8_t alarm_round;
    uint8_t cancelled;
    uint32_t off_delay_ms;
    KeyDebounceState_t key2_state = {0};

    printf("[BuzzerTask] Started\r\n");
    off_delay_ms = (BUZZER_BEEP_INTERVAL_MS > BUZZER_BEEP_ON_MS) ?
                   (BUZZER_BEEP_INTERVAL_MS - BUZZER_BEEP_ON_MS) : 0U;

    for (;;) {
        if (osSemaphoreAcquire(buzzerAlertSem, osWaitForever) == osOK) {
            if (drop_alarm_request_pending != 0U) {
                drop_alarm_request_pending = 0U;
                cancelled = 0U;

                for (alarm_round = 0U; alarm_round < DROP_ALARM_REPEAT_COUNT; alarm_round++) {
                    Buzzer_StartTone();
                    if (Buzzer_WaitWithCancel(DROP_ALARM_ON_MS, &key2_state) != 0U) {
                        cancelled = 1U;
                        Buzzer_StopTone();
                        break;
                    }
                    Buzzer_StopTone();

                    if ((alarm_round + 1U) < DROP_ALARM_REPEAT_COUNT) {
                        if (Buzzer_WaitWithCancel(DROP_ALARM_GAP_MS, &key2_state) != 0U) {
                            cancelled = 1U;
                            break;
                        }
                    }
                }

                Buzzer_StopTone();
                if (cancelled != 0U) {
                    drop_alarm_cancel_timestamp = HAL_GetTick();
                    drop_alarm_cancel_pending = 1U;
                    (void)osSemaphoreRelease(mqttPublishSem);
                }
                drop_alert_latched = 0U;
                continue;
            }

            for (beep_index = 0U; beep_index < BUZZER_BEEP_COUNT; beep_index++) {
                Buzzer_StartTone();
                osDelay(BUZZER_BEEP_ON_MS);
                Buzzer_StopTone();
                if ((beep_index + 1U) < BUZZER_BEEP_COUNT) {
                    osDelay(off_delay_ms);
                }
            }
        }
    }
}

/**
  * @brief  显示任务
  * @param  argument: 任务参数
  */
void DisplayTask(void *argument)
{
    MedicineBoxData_t data;
    
    printf("[DisplayTask] Started\r\n");
    
    for (;;) {
        /* 获取最新数据 */
        SensorManager_GetData(&data);
        
        /* 这里可以添加LCD/OLED显示代码 */
        /* 示例：打印到调试串口 */
        #if 0  // 设为1启用调试输出
        printf("[DISP] T:%.1fC H:%.1f%% P:%.0fhPa State:%s\r\n",
               data.env.temperature,
               data.env.humidity,
               data.env.pressure / 100.0f,
               SensorManager_GetStateString(data.state));
        #endif
        
        osDelay(500);
    }
}

/**
  * @brief  LED指示任务
  * @param  argument: 任务参数
  */
void LEDTask(void *argument)
{
    uint32_t now;
    uint32_t led1_last_toggle_tick = 0U;
    uint32_t led2_last_toggle_tick = 0U;
    uint32_t led1_toggle_interval = 500U;
    ESP8266_State_t led1_mode = ESP8266_STATE_RESET;
    uint8_t led1_output = 0U;
    uint8_t led2_output = 1U;

    printf("[LEDTask] Started\r\n");

    HAL_GPIO_WritePin(LED1_GPIO_Port, LED1_Pin, GPIO_PIN_RESET);
    HAL_GPIO_WritePin(LED2_GPIO_Port, LED2_Pin, GPIO_PIN_SET);

    for (;;) {
        ESP8266_State_t state = ESP8266_GetState();
        now = HAL_GetTick();

        if (state == ESP8266_STATE_MQTT_CONNECTED) {
            if (led1_mode != ESP8266_STATE_MQTT_CONNECTED) {
                led1_mode = ESP8266_STATE_MQTT_CONNECTED;
                led1_toggle_interval = 500U;
                led1_last_toggle_tick = now;
                led1_output = 1U;
            } else if ((uint32_t)(now - led1_last_toggle_tick) >= led1_toggle_interval) {
                led1_last_toggle_tick = now;
                led1_output = (uint8_t)((led1_output == 0U) ? 1U : 0U);
            }
        } else if (state == ESP8266_STATE_WIFI_CONNECTED) {
            if (led1_mode != ESP8266_STATE_WIFI_CONNECTED) {
                led1_mode = ESP8266_STATE_WIFI_CONNECTED;
                led1_toggle_interval = 100U;
                led1_last_toggle_tick = now;
                led1_output = 1U;
            } else if ((uint32_t)(now - led1_last_toggle_tick) >= led1_toggle_interval) {
                led1_last_toggle_tick = now;
                led1_output = (uint8_t)((led1_output == 0U) ? 1U : 0U);
            }
        } else if (state == ESP8266_STATE_ERROR) {
            led1_mode = ESP8266_STATE_ERROR;
            led1_output = 1U;
            led1_last_toggle_tick = now;
        } else {
            led1_mode = ESP8266_STATE_RESET;
            led1_output = 0U;
            led1_last_toggle_tick = now;
        }

        HAL_GPIO_WritePin(LED1_GPIO_Port, LED1_Pin, (led1_output != 0U) ? GPIO_PIN_SET : GPIO_PIN_RESET);

        if (app_bus_fault_flags != 0U) {
            if ((uint32_t)(now - led2_last_toggle_tick) >= LED2_FAULT_BLINK_MS) {
                led2_last_toggle_tick = now;
                led2_output = (uint8_t)((led2_output == 0U) ? 1U : 0U);
            }
        } else {
            led2_output = 1U;
            led2_last_toggle_tick = now;
        }

        HAL_GPIO_WritePin(LED2_GPIO_Port, LED2_Pin, (led2_output != 0U) ? GPIO_PIN_SET : GPIO_PIN_RESET);
        osDelay(20);
    }
}
