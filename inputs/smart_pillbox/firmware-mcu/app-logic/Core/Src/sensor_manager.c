/**
  ******************************************************************************
  * @file    sensor_manager.c
  * @brief   传感器数据管理器实现
  ******************************************************************************
  */
#include "sensor_manager.h"
#include <stdio.h>
#include <string.h>
#include <math.h>

/* 传感器数据实例 */
static MPU6050_Data_t mpu_data;
static AHT20_Data_t aht_data;
static BMP280_Data_t bmp_data;

/* 药箱综合数据 */
static MedicineBoxData_t box_data;

/* 振动检测阈值 */
#define VIBRATION_THRESHOLD     0.5f    // g
#define TILT_THRESHOLD          30.0f   // 度

#define ENV_ABNORMAL_RATIO      0.30f
#define ENV_RATED_TEMP_MIN      1.0f
#define ENV_RATED_TEMP_MAX      60.0f
#define ENV_RATED_HUM_MIN       1.0f
#define ENV_RATED_HUM_MAX       100.0f

static float rated_temperature = ENV_RATED_DEFAULT_TEMP_C;
static float rated_humidity = ENV_RATED_DEFAULT_HUMIDITY_PERCENT;
static EnvironmentAlertStatus_t env_alert_status;

static void UpdateEnvAlertStatus(void)
{
    env_alert_status.rated_temperature = rated_temperature;
    env_alert_status.rated_humidity = rated_humidity;
    env_alert_status.temp_low_limit = rated_temperature * (1.0f - ENV_ABNORMAL_RATIO);
    env_alert_status.temp_high_limit = rated_temperature * (1.0f + ENV_ABNORMAL_RATIO);
    env_alert_status.humidity_low_limit = rated_humidity * (1.0f - ENV_ABNORMAL_RATIO);
    env_alert_status.humidity_high_limit = rated_humidity * (1.0f + ENV_ABNORMAL_RATIO);

    if (box_data.is_valid == 0U) {
        env_alert_status.temperature_abnormal = 0U;
        env_alert_status.humidity_abnormal = 0U;
        env_alert_status.is_abnormal = 0U;
        return;
    }

    env_alert_status.temperature_abnormal =
        ((box_data.env.temperature < env_alert_status.temp_low_limit) ||
         (box_data.env.temperature > env_alert_status.temp_high_limit)) ? 1U : 0U;
    env_alert_status.humidity_abnormal =
        ((box_data.env.humidity < env_alert_status.humidity_low_limit) ||
         (box_data.env.humidity > env_alert_status.humidity_high_limit)) ? 1U : 0U;
    env_alert_status.is_abnormal =
        (uint8_t)(env_alert_status.temperature_abnormal || env_alert_status.humidity_abnormal);
}

/**
  * @brief  初始化传感器管理器
  */
void SensorManager_Init(void)
{
    uint8_t retry;
    
    /* 初始化MPU6050 */
    retry = 3;
    while (retry--) {
        if (MPU6050_Init() == 0) {
            break;
        }
        HAL_Delay(100);
    }
    
    /* 初始化AHT20 */
    retry = 3;
    while (retry--) {
        if (AHT20_Init() == 0) {
            break;
        }
        HAL_Delay(100);
    }
    
    /* 初始化BMP280 */
    retry = 3;
    while (retry--) {
        if (BMP280_Init() == 0) {
            break;
        }
        HAL_Delay(100);
    }
    
    /* 初始化数据结构 */
    memset(&box_data, 0, sizeof(box_data));
    box_data.state = BOX_STATE_CLOSED;
    box_data.is_valid = 0U;
    rated_temperature = ENV_RATED_DEFAULT_TEMP_C;
    rated_humidity = ENV_RATED_DEFAULT_HUMIDITY_PERCENT;
    memset(&env_alert_status, 0, sizeof(env_alert_status));
    UpdateEnvAlertStatus();
}

/**
  * @brief  读取所有传感器数据
  * @retval 0:成功 1:失败
  */
uint8_t SensorManager_ReadAll(void)
{
    uint8_t result = 0;
    
    /* 读取MPU6050 */
    if (MPU6050_ReadData(&mpu_data) == 0) {
        MPU6050_CalculateAngles(&mpu_data);
        
        box_data.motion.accel_x = mpu_data.accel_x_g;
        box_data.motion.accel_y = mpu_data.accel_y_g;
        box_data.motion.accel_z = mpu_data.accel_z_g;
        box_data.motion.gyro_x = mpu_data.gyro_x_dps;
        box_data.motion.gyro_y = mpu_data.gyro_y_dps;
        box_data.motion.gyro_z = mpu_data.gyro_z_dps;
        box_data.motion.pitch = mpu_data.pitch;
        box_data.motion.roll = mpu_data.roll;
        
        /* 计算振动强度 (合成加速度变化) */
        box_data.motion.vibration = sqrtf(
            mpu_data.accel_x_g * mpu_data.accel_x_g +
            mpu_data.accel_y_g * mpu_data.accel_y_g +
            mpu_data.accel_z_g * mpu_data.accel_z_g
        ) - 1.0f;  // 减去重力
        if (box_data.motion.vibration < 0) {
            box_data.motion.vibration = 0;
        }
    } else {
        result |= 0x01;
    }
    
    /* 读取AHT20 */
    if (AHT20_ReadDataBlocking(&aht_data, 200) == 0) {
        box_data.env.humidity = aht_data.humidity;
        /* 温度暂存，后续与BMP280取平均 */
    } else {
        result |= 0x02;
    }
    
    /* 读取BMP280 */
    if (BMP280_ReadData(&bmp_data) == 0) {
        box_data.env.pressure = bmp_data.pressure;
        box_data.env.altitude = bmp_data.altitude;
        
        /* 温度取AHT20和BMP280的平均值 */
        if ((result & 0x02) == 0) {
            box_data.env.temperature = (aht_data.temperature + bmp_data.temperature) / 2.0f;
        } else {
            box_data.env.temperature = bmp_data.temperature;
        }
    } else {
        result |= 0x04;
        /* 如果BMP280失败，使用AHT20的温度 */
        if ((result & 0x02) == 0) {
            box_data.env.temperature = aht_data.temperature;
        }
    }
    
    /* 检测药箱状态 */
    box_data.state = SensorManager_DetectState();
    box_data.timestamp = HAL_GetTick();
    box_data.is_valid = (result == 0) ? 1 : 0;
    UpdateEnvAlertStatus();
    
    return result;
}

/**
  * @brief  获取药箱数据
  * @param  data: 数据指针
  */
void SensorManager_GetData(MedicineBoxData_t *data)
{
    if (data != NULL) {
        memcpy(data, &box_data, sizeof(MedicineBoxData_t));
    }
}

uint8_t SensorManager_SetRatedEnvironment(float temperature, float humidity)
{
    if ((temperature < ENV_RATED_TEMP_MIN) || (temperature > ENV_RATED_TEMP_MAX)) {
        return 1U;
    }

    if ((humidity < ENV_RATED_HUM_MIN) || (humidity > ENV_RATED_HUM_MAX)) {
        return 1U;
    }

    rated_temperature = temperature;
    rated_humidity = humidity;
    UpdateEnvAlertStatus();
    return 0U;
}

void SensorManager_GetRatedEnvironment(float *temperature, float *humidity)
{
    if (temperature != NULL) {
        *temperature = rated_temperature;
    }
    if (humidity != NULL) {
        *humidity = rated_humidity;
    }
}

void SensorManager_GetEnvAlertStatus(EnvironmentAlertStatus_t *status)
{
    if (status != NULL) {
        memcpy(status, &env_alert_status, sizeof(EnvironmentAlertStatus_t));
    }
}

/**
  * @brief  检测药箱状态
  * @retval 状态枚举
  */
BoxState_t SensorManager_DetectState(void)
{
    /* 检测移动/振动 */
    if (box_data.motion.vibration > VIBRATION_THRESHOLD) {
        return BOX_STATE_MOVING;
    }
    
    /* 检测倾斜 */
    if (fabsf(box_data.motion.pitch) > TILT_THRESHOLD || 
        fabsf(box_data.motion.roll) > TILT_THRESHOLD) {
        return BOX_STATE_TILTED;
    }
    
    /* 检测开合 (通过Z轴加速度判断) */
    /* 正常放置时Z轴约1g，打开时可能变化 */
    /* 这里简化处理，实际可能需要霍尔传感器辅助 */
    if (box_data.motion.accel_z < 0.7f) {
        return BOX_STATE_OPENED;
    }
    
    return BOX_STATE_CLOSED;
}

/**
  * @brief  获取状态字符串
  * @param  state: 状态枚举
  * @retval 状态描述
  */
const char* SensorManager_GetStateString(BoxState_t state)
{
    switch (state) {
        case BOX_STATE_CLOSED:   return "closed";
        case BOX_STATE_OPENED:   return "opened";
        case BOX_STATE_MOVING:   return "moving";
        case BOX_STATE_TILTED:   return "tilted";
        default:                 return "unknown";
    }
}

/**
  * @brief  生成JSON格式的传感器数据
  * @param  json_buf: JSON缓冲区
  * @param  buf_size: 缓冲区大小
  */
void SensorManager_CreateJSON(char *json_buf, uint16_t buf_size)
{
    snprintf(json_buf, buf_size,
        "{"
        "\"timestamp\":%lu,"
        "\"device_id\":\"medicine_box_001\","
        "\"state\":\"%s\","
        "\"environment\":{"
            "\"temperature\":%.2f,"
            "\"humidity\":%.2f,"
            "\"pressure\":%.2f,"
            "\"altitude\":%.2f"
        "},"
        "\"environment_limits\":{"
            "\"temperature_rated\":%.2f,"
            "\"temperature_low\":%.2f,"
            "\"temperature_high\":%.2f,"
            "\"humidity_rated\":%.2f,"
            "\"humidity_low\":%.2f,"
            "\"humidity_high\":%.2f"
        "},"
        "\"motion\":{"
            "\"accel_x\":%.3f,"
            "\"accel_y\":%.3f,"
            "\"accel_z\":%.3f,"
            "\"gyro_x\":%.2f,"
            "\"gyro_y\":%.2f,"
            "\"gyro_z\":%.2f,"
            "\"pitch\":%.2f,"
            "\"roll\":%.2f,"
            "\"vibration\":%.3f"
        "},"
        "\"alerts\":{"
            "\"env_abnormal\":%d,"
            "\"temperature_abnormal\":%d,"
            "\"humidity_abnormal\":%d"
        "},"
        "\"valid\":%d"
        "}",
        box_data.timestamp,
        SensorManager_GetStateString(box_data.state),
        box_data.env.temperature,
        box_data.env.humidity,
        box_data.env.pressure,
        box_data.env.altitude,
        env_alert_status.rated_temperature,
        env_alert_status.temp_low_limit,
        env_alert_status.temp_high_limit,
        env_alert_status.rated_humidity,
        env_alert_status.humidity_low_limit,
        env_alert_status.humidity_high_limit,
        box_data.motion.accel_x,
        box_data.motion.accel_y,
        box_data.motion.accel_z,
        box_data.motion.gyro_x,
        box_data.motion.gyro_y,
        box_data.motion.gyro_z,
        box_data.motion.pitch,
        box_data.motion.roll,
        box_data.motion.vibration,
        env_alert_status.is_abnormal,
        env_alert_status.temperature_abnormal,
        env_alert_status.humidity_abnormal,
        box_data.is_valid
    );
}
