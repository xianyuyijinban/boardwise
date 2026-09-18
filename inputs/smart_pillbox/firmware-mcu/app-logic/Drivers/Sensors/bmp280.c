/**
  ******************************************************************************
  * @file    bmp280.c
  * @brief   BMP280 气压温度传感器驱动实现
  *          使用I2C3接口 (PC8-SCL, PC9-SDA)
  ******************************************************************************
  */
#include "bmp280.h"
#include <math.h>

extern I2C_HandleTypeDef hi2c3;

/* 校准数据 */
static BMP280_CalibData_t calib_data;

/**
  * @brief  向BMP280寄存器写入数据
  * @param  reg: 寄存器地址
  * @param  data: 数据
  * @retval HAL状态
  */
static HAL_StatusTypeDef BMP280_WriteReg(uint8_t reg, uint8_t data)
{
    uint8_t buf[2] = {reg, data};
    return HAL_I2C_Master_Transmit(&hi2c3, BMP280_ADDR_WRITE, buf, 2, 100);
}

/**
  * @brief  从BMP280寄存器读取数据
  * @param  reg: 寄存器地址
  * @param  buf: 缓冲区
  * @param  len: 长度
  * @retval HAL状态
  */
static HAL_StatusTypeDef BMP280_ReadReg(uint8_t reg, uint8_t *buf, uint16_t len)
{
    HAL_StatusTypeDef status;
    
    status = HAL_I2C_Master_Transmit(&hi2c3, BMP280_ADDR_WRITE, &reg, 1, 100);
    if (status != HAL_OK) return status;
    
    return HAL_I2C_Master_Receive(&hi2c3, BMP280_ADDR_READ, buf, len, 100);
}

/**
  * @brief  初始化BMP280
  * @retval 0:成功 1:失败
  */
uint8_t BMP280_Init(void)
{
    uint8_t id;
    
    /* 读取芯片ID */
    id = BMP280_ReadID();
    if (id != BMP280_CHIP_ID) {
        return 1;
    }
    
    /* 读取校准数据 */
    if (BMP280_ReadCalibrationData() != 0) {
        return 1;
    }
    
    /* 设置配置: 温度x2, 气压x16, 正常模式 */
    BMP280_SetConfig(BMP280_OVERSAMPLING_X2, 
                     BMP280_OVERSAMPLING_X16, 
                     BMP280_MODE_NORMAL);
    
    /* 设置IIR滤波器 */
    BMP280_SetFilter(BMP280_FILTER_X4);
    
    HAL_Delay(100);
    return 0;
}

/**
  * @brief  读取芯片ID
  * @retval 芯片ID
  */
uint8_t BMP280_ReadID(void)
{
    uint8_t id;
    if (BMP280_ReadReg(BMP280_REG_CHIPID, &id, 1) != HAL_OK) {
        return 0;
    }
    return id;
}

/**
  * @brief  软件复位
  */
void BMP280_Reset(void)
{
    BMP280_WriteReg(BMP280_REG_SOFTRESET, 0xB6);
}

/**
  * @brief  读取校准数据
  * @retval 0:成功 1:失败
  */
uint8_t BMP280_ReadCalibrationData(void)
{
    uint8_t buf[24];
    
    if (BMP280_ReadReg(BMP280_REG_DIG_T1, buf, 24) != HAL_OK) {
        return 1;
    }
    
    calib_data.dig_T1 = (uint16_t)(buf[1] << 8) | buf[0];
    calib_data.dig_T2 = (int16_t)(buf[3] << 8) | buf[2];
    calib_data.dig_T3 = (int16_t)(buf[5] << 8) | buf[4];
    calib_data.dig_P1 = (uint16_t)(buf[7] << 8) | buf[6];
    calib_data.dig_P2 = (int16_t)(buf[9] << 8) | buf[8];
    calib_data.dig_P3 = (int16_t)(buf[11] << 8) | buf[10];
    calib_data.dig_P4 = (int16_t)(buf[13] << 8) | buf[12];
    calib_data.dig_P5 = (int16_t)(buf[15] << 8) | buf[14];
    calib_data.dig_P6 = (int16_t)(buf[17] << 8) | buf[16];
    calib_data.dig_P7 = (int16_t)(buf[19] << 8) | buf[18];
    calib_data.dig_P8 = (int16_t)(buf[21] << 8) | buf[20];
    calib_data.dig_P9 = (int16_t)(buf[23] << 8) | buf[22];
    
    return 0;
}

/**
  * @brief  设置测量配置
  * @param  temp_os: 温度过采样
  * @param  press_os: 气压过采样
  * @param  mode: 工作模式
  */
void BMP280_SetConfig(BMP280_Oversampling_t temp_os, 
                      BMP280_Oversampling_t press_os,
                      BMP280_Mode_t mode)
{
    uint8_t ctrl_meas = (temp_os << 5) | (press_os << 2) | mode;
    BMP280_WriteReg(BMP280_REG_CONTROL, ctrl_meas);
}

/**
  * @brief  设置滤波器
  * @param  filter: 滤波器系数
  */
void BMP280_SetFilter(BMP280_Filter_t filter)
{
    uint8_t config = (filter << 2);
    BMP280_WriteReg(BMP280_REG_CONFIG, config);
}

/**
  * @brief  补偿温度
  * @param  adc_T: 原始温度值
  * @param  t_fine: 输出校准参数
  * @retval 补偿后的温度 (0.01°C)
  */
static int32_t BMP280_Compensate_T(int32_t adc_T, int32_t *t_fine)
{
    int32_t var1, var2, T;
    
    var1 = ((((adc_T >> 3) - ((int32_t)calib_data.dig_T1 << 1))) * 
            ((int32_t)calib_data.dig_T2)) >> 11;
    var2 = (((((adc_T >> 4) - ((int32_t)calib_data.dig_T1)) * 
              ((adc_T >> 4) - ((int32_t)calib_data.dig_T1))) >> 12) * 
            ((int32_t)calib_data.dig_T3)) >> 14;
    
    *t_fine = var1 + var2;
    T = (*t_fine * 5 + 128) >> 8;
    
    return T;
}

/**
  * @brief  补偿气压
  * @param  adc_P: 原始气压值
  * @param  t_fine: 校准参数
  * @retval 补偿后的气压 (Pa)
  */
static uint32_t BMP280_Compensate_P(int32_t adc_P, int32_t t_fine)
{
    int64_t var1, var2, p;
    
    var1 = ((int64_t)t_fine) - 128000;
    var2 = var1 * var1 * (int64_t)calib_data.dig_P6;
    var2 = var2 + ((var1 * (int64_t)calib_data.dig_P5) << 17);
    var2 = var2 + (((int64_t)calib_data.dig_P4) << 35);
    var1 = ((var1 * var1 * (int64_t)calib_data.dig_P3) >> 8) + 
           ((var1 * (int64_t)calib_data.dig_P2) << 12);
    var1 = (((((int64_t)1) << 47) + var1)) * ((int64_t)calib_data.dig_P1) >> 33;
    
    if (var1 == 0) {
        return 0;
    }
    
    p = 1048576 - adc_P;
    p = (((p << 31) - var2) * 3125) / var1;
    var1 = (((int64_t)calib_data.dig_P9) * (p >> 13) * (p >> 13)) >> 25;
    var2 = (((int64_t)calib_data.dig_P8) * p) >> 19;
    p = ((p + var1 + var2) >> 8) + (((int64_t)calib_data.dig_P7) << 4);
    
    return (uint32_t)p;
}

/**
  * @brief  读取传感器数据
  * @param  data: 数据结构指针
  * @retval 0:成功 1:失败
  */
uint8_t BMP280_ReadData(BMP280_Data_t *data)
{
    uint8_t buf[6];
    int32_t adc_T, adc_P;
    int32_t t_fine;
    
    /* 读取原始数据 */
    if (BMP280_ReadReg(BMP280_REG_PRESS_MSB, buf, 6) != HAL_OK) {
        return 1;
    }
    
    /* 合成原始值 (20bit) */
    adc_P = ((int32_t)buf[0] << 12) | ((int32_t)buf[1] << 4) | ((int32_t)buf[2] >> 4);
    adc_T = ((int32_t)buf[3] << 12) | ((int32_t)buf[4] << 4) | ((int32_t)buf[5] >> 4);
    
    data->press_raw = adc_P;
    data->temp_raw = adc_T;
    
    /* 补偿计算 */
    data->temperature = BMP280_Compensate_T(adc_T, &t_fine) / 100.0f;
    data->pressure = BMP280_Compensate_P(adc_P, t_fine) / 256.0f;
    data->t_fine = t_fine;
    
    /* 计算海拔高度 */
    data->altitude = BMP280_CalculateAltitude(data->pressure, 101325.0f);
    
    return 0;
}

/**
  * @brief  计算海拔高度
  * @param  pressure_pa: 当前气压 (Pa)
  * @param  sea_level_pa: 海平面气压 (Pa), 标准值101325
  * @retval 海拔高度 (m)
  */
float BMP280_CalculateAltitude(float pressure_pa, float sea_level_pa)
{
    /* 国际标准大气公式 */
    return 44330.0f * (1.0f - powf(pressure_pa / sea_level_pa, 0.1903f));
}
