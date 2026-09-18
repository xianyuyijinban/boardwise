/**
  ******************************************************************************
  * @file    app_tasks.h
  * @brief   FreeRTOS任务定义
  ******************************************************************************
  */
#ifndef __APP_TASKS_H
#define __APP_TASKS_H

#include "main.h"
#include "cmsis_os.h"

/* 任务优先级 */
#define SENSOR_TASK_PRIORITY        osPriorityNormal
#define MQTT_TASK_PRIORITY          osPriorityAboveNormal
#define DISPLAY_TASK_PRIORITY       osPriorityBelowNormal
#define LED_TASK_PRIORITY           osPriorityLow
#define BUZZER_TASK_PRIORITY        osPriorityLow

/* 任务堆栈大小 */
#define SENSOR_TASK_STACK_SIZE      256
#define MQTT_TASK_STACK_SIZE        512
#define DISPLAY_TASK_STACK_SIZE     256
#define LED_TASK_STACK_SIZE         128
#define BUZZER_TASK_STACK_SIZE      256

/* 任务句柄 (可选，用于外部控制) */
extern osThreadId_t sensorTaskHandle;
extern osThreadId_t mqttTaskHandle;
extern osThreadId_t displayTaskHandle;
extern osThreadId_t buzzerTaskHandle;

/* 任务函数声明 */
void SensorTask(void *argument);
void MQTTTask(void *argument);
void DisplayTask(void *argument);
void LEDTask(void *argument);
void BuzzerTask(void *argument);

/* 应用初始化 */
void App_Init(void);
void App_StartTasks(void);

/* 网络配置 (根据实际情况修改) */
#define WIFI_SSID           "Galaxy Note 7 Ultra"
#define WIFI_PASSWORD       "12345678y"
#define MQTT_BROKER_IP      "192.168.1.100"
#define MQTT_BROKER_PORT    1883
#define MQTT_CLIENT_ID      "medicine_box_001"
#define MQTT_USERNAME       ""
#define MQTT_PASSWORD       ""

/* MQTT主题 */
#define MQTT_TOPIC_DATA     "medicine/box001/sensors"
#define MQTT_TOPIC_STATUS   "medicine/box001/status"
#define MQTT_TOPIC_CONTROL  "medicine/box001/control"
#define MQTT_TOPIC_ALERT    "medicine/box001/alert"
#define MQTT_TOPIC_CONTROL_RESPONSE "medicine/box001/control/response"

/* 采样间隔 */
#define SENSOR_SAMPLE_INTERVAL_MS   100     // 传感器采样间隔 100ms
#define MQTT_PUBLISH_INTERVAL_MS    5000    // MQTT发布间隔 5s

#define BUZZER_BEEP_COUNT           3
#define BUZZER_BEEP_ON_MS           200
#define BUZZER_BEEP_INTERVAL_MS     1000

/* 跌落检测与报警配置 */
#define DROP_ACCEL_THRESHOLD_G      6.0f
#define DROP_ACCEL_THRESHOLD_SQ     (DROP_ACCEL_THRESHOLD_G * DROP_ACCEL_THRESHOLD_G)
#define DROP_ACCEL_DURATION_MS      20U
#define DROP_ALARM_ON_MS            5000U
#define DROP_ALARM_GAP_MS           3000U
#define DROP_ALARM_REPEAT_COUNT     3U
#define KEY2_DEBOUNCE_MS            50U
#define BUZZER_POLL_INTERVAL_MS     20U

#endif /* __APP_TASKS_H */
