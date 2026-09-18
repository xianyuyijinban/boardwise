/**
  ******************************************************************************
  * @file    mpu6050.c
  * @brief   MPU6050 6轴姿态传感器驱动实现
  *          使用I2C2接口 (PA8-SDA, PA9-SCL)
  ******************************************************************************
  */
#include "mpu6050.h"
#include <math.h>

extern I2C_HandleTypeDef hi2c2;

/* 加速度灵敏度系数 (LSB/g) */
static const float ACCEL_SENSITIVITY[4] = {16384.0f, 8192.0f, 4096.0f, 2048.0f};
/* 陀螺仪灵敏度系数 (LSB/(°/s)) */
static const float GYRO_SENSITIVITY[4] = {131.0f, 65.5f, 32.8f, 16.4f};
/* 当前配置量程，用于原始值到物理量换算 */
static MPU6050_AccelRange_t current_accel_range = MPU6050_ACCEL_RANGE_2G;
static MPU6050_GyroRange_t current_gyro_range = MPU6050_GYRO_RANGE_250DPS;

/**
  * @brief  向MPU6050寄存器写入数据
  * @param  reg: 寄存器地址
  * @param  data: 要写入的数据
  * @retval HAL状态
  */
static HAL_StatusTypeDef MPU6050_WriteReg(uint8_t reg, uint8_t data)
{
    uint8_t buf[2] = {reg, data};
    return HAL_I2C_Master_Transmit(&hi2c2, MPU6050_ADDR_WRITE, buf, 2, 100);
}

/**
  * @brief  从MPU6050寄存器读取数据
  * @param  reg: 寄存器地址
  * @param  buf: 数据缓冲区
  * @param  len: 读取长度
  * @retval HAL状态
  */
static HAL_StatusTypeDef MPU6050_ReadReg(uint8_t reg, uint8_t *buf, uint16_t len)
{
    HAL_StatusTypeDef status;
    
    status = HAL_I2C_Master_Transmit(&hi2c2, MPU6050_ADDR_WRITE, &reg, 1, 100);
    if (status != HAL_OK) return status;
    
    return HAL_I2C_Master_Receive(&hi2c2, MPU6050_ADDR_READ, buf, len, 100);
}

/**
  * @brief  初始化MPU6050
  * @retval 0:成功 1:失败
  */
uint8_t MPU6050_Init(void)
{
    uint8_t id;
    
    /* 检查设备ID */
    id = MPU6050_ReadID();
    if (id != MPU6050_ID) {
        return 1;
    }
    
    /* 唤醒MPU6050 */
    MPU6050_WriteReg(MPU6050_REG_PWR_MGMT_1, 0x00);
    HAL_Delay(10);
    
    /* 设置时钟源为PLL with X axis gyroscope reference */
    MPU6050_WriteReg(MPU6050_REG_PWR_MGMT_1, 0x01);
    HAL_Delay(10);
    
    /* 设置采样率分频 1kHz/(1+99) = 100Hz */
    MPU6050_WriteReg(MPU6050_REG_SMPLRT_DIV, 99);
    
    /* 设置低通滤波器 DLPF_CFG = 3 (41Hz带宽) */
    MPU6050_WriteReg(MPU6050_REG_CONFIG, 0x03);
    
    /* 设置加速度计量程为 ±16g */
    MPU6050_SetAccelRange(MPU6050_ACCEL_RANGE_16G);
    
    /* 设置陀螺仪量程为 ±250°/s */
    MPU6050_SetGyroRange(MPU6050_GYRO_RANGE_250DPS);
    
    /* 使能传感器 */
    MPU6050_WriteReg(MPU6050_REG_PWR_MGMT_2, 0x00);
    
    HAL_Delay(100);
    return 0;
}

/**
  * @brief  读取MPU6050设备ID
  * @retval 设备ID
  */
uint8_t MPU6050_ReadID(void)
{
    uint8_t id;
    if (MPU6050_ReadReg(MPU6050_REG_WHO_AM_I, &id, 1) != HAL_OK) {
        return 0;
    }
    return id;
}

/**
  * @brief  设置加速度计量程
  * @param  range: 量程选择
  */
void MPU6050_SetAccelRange(MPU6050_AccelRange_t range)
{
    MPU6050_WriteReg(MPU6050_REG_ACCEL_CONFIG, range << 3);
    current_accel_range = range;
}

/**
  * @brief  设置陀螺仪量程
  * @param  range: 量程选择
  */
void MPU6050_SetGyroRange(MPU6050_GyroRange_t range)
{
    MPU6050_WriteReg(MPU6050_REG_GYRO_CONFIG, range << 3);
    current_gyro_range = range;
}

/**
  * @brief  读取MPU6050传感器数据
  * @param  data: 数据结构指针
  * @retval 0:成功 1:失败
  */
uint8_t MPU6050_ReadData(MPU6050_Data_t *data)
{
    uint8_t buf[14];
    
    if (MPU6050_ReadReg(MPU6050_REG_ACCEL_XOUT_H, buf, 14) != HAL_OK) {
        return 1;
    }
    
    /* 合成数据 (大端模式) */
    data->accel_x = (int16_t)((buf[0] << 8) | buf[1]);
    data->accel_y = (int16_t)((buf[2] << 8) | buf[3]);
    data->accel_z = (int16_t)((buf[4] << 8) | buf[5]);
    data->temp    = (int16_t)((buf[6] << 8) | buf[7]);
    data->gyro_x  = (int16_t)((buf[8] << 8) | buf[9]);
    data->gyro_y  = (int16_t)((buf[10] << 8) | buf[11]);
    data->gyro_z  = (int16_t)((buf[12] << 8) | buf[13]);
    
    /* 转换为物理量 */
    data->accel_range = current_accel_range;
    data->gyro_range = current_gyro_range;
    data->accel_x_g = data->accel_x / ACCEL_SENSITIVITY[data->accel_range];
    data->accel_y_g = data->accel_y / ACCEL_SENSITIVITY[data->accel_range];
    data->accel_z_g = data->accel_z / ACCEL_SENSITIVITY[data->accel_range];
    
    data->gyro_x_dps = data->gyro_x / GYRO_SENSITIVITY[data->gyro_range];
    data->gyro_y_dps = data->gyro_y / GYRO_SENSITIVITY[data->gyro_range];
    data->gyro_z_dps = data->gyro_z / GYRO_SENSITIVITY[data->gyro_range];
    
    /* 温度转换: Temp = (Raw / 340.0) + 36.53 */
    data->temp_c = (data->temp / 340.0f) + 36.53f;
    
    return 0;
}

/**
  * @brief  计算俯仰角和横滚角
  * @param  data: 数据结构指针
  * @note   使用加速度计计算姿态角
  */
void MPU6050_CalculateAngles(MPU6050_Data_t *data)
{
    /* 俯仰角 (Pitch) - 绕X轴旋转 */
    data->pitch = atan2f(data->accel_y_g, 
                         sqrtf(data->accel_x_g * data->accel_x_g + 
                               data->accel_z_g * data->accel_z_g)) * 180.0f / M_PI;
    
    /* 横滚角 (Roll) - 绕Y轴旋转 */
    data->roll = atan2f(-data->accel_x_g, 
                        data->accel_z_g) * 180.0f / M_PI;
}
