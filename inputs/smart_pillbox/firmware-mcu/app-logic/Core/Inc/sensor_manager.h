/**
  ******************************************************************************
  * @file    sensor_manager.h
  * @brief   传感器数据管理器
  *          整合MPU6050、AHT20、BMP280数据
  ******************************************************************************
  */
#ifndef __SENSOR_MANAGER_H
#define __SENSOR_MANAGER_H

#include "main.h"
#include "mpu6050.h"
#include "aht20.h"
#include "bmp280.h"

/* 药箱状态 */
typedef enum {
    BOX_STATE_CLOSED = 0,   // 关闭状态
    BOX_STATE_OPENED,       // 打开状态
    BOX_STATE_MOVING,       // 移动中
    BOX_STATE_TILTED        // 倾斜状态
} BoxState_t;

/* 环境数据结构 */
typedef struct {
    float temperature;      // 温度 (°C) - 综合AHT20和BMP280
    float humidity;         // 湿度 (%RH) - AHT20
    float pressure;         // 气压 (Pa) - BMP280
    float altitude;         // 海拔 (m) - BMP280
} EnvironmentData_t;

/* 姿态数据结构 */
typedef struct {
    float accel_x;          // X加速度 (g)
    float accel_y;          // Y加速度 (g)
    float accel_z;          // Z加速度 (g)
    float gyro_x;           // X角速度 (°/s)
    float gyro_y;           // Y角速度 (°/s)
    float gyro_z;           // Z角速度 (°/s)
    float pitch;            // 俯仰角 (°)
    float roll;             // 横滚角 (°)
    float vibration;        // 振动强度
} MotionData_t;

/* 药箱状态数据结构 */
typedef struct {
    BoxState_t state;           // 药箱状态
    EnvironmentData_t env;      // 环境数据
    MotionData_t motion;        // 运动数据
    uint32_t timestamp;         // 时间戳
    uint8_t is_valid;           // 数据有效标志
} MedicineBoxData_t;

#define ENV_RATED_DEFAULT_TEMP_C           15.0f
#define ENV_RATED_DEFAULT_HUMIDITY_PERCENT 50.0f

typedef struct {
    float rated_temperature;
    float rated_humidity;
    float temp_low_limit;
    float temp_high_limit;
    float humidity_low_limit;
    float humidity_high_limit;
    uint8_t temperature_abnormal;
    uint8_t humidity_abnormal;
    uint8_t is_abnormal;
} EnvironmentAlertStatus_t;

/* 函数声明 */
void SensorManager_Init(void);
uint8_t SensorManager_ReadAll(void);
void SensorManager_GetData(MedicineBoxData_t *data);
BoxState_t SensorManager_DetectState(void);
const char* SensorManager_GetStateString(BoxState_t state);
void SensorManager_CreateJSON(char *json_buf, uint16_t buf_size);
uint8_t SensorManager_SetRatedEnvironment(float temperature, float humidity);
void SensorManager_GetRatedEnvironment(float *temperature, float *humidity);
void SensorManager_GetEnvAlertStatus(EnvironmentAlertStatus_t *status);

#endif /* __SENSOR_MANAGER_H */
