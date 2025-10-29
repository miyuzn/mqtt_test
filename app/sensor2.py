# Sensor v2
# Comparable with board GCU v3.0 above

import struct
import csv
import numpy as np
import pandas as pd
import os

coordinate_x_35_insole = [
    -40.6, -21.2, -6.5, 7.2, 17.3,
    -39.6, -24.3, -8.2, 4.3, 15.2,
    -35.3, -23, -8.9, 4.5, 16.2,
    -17, -8.5, 0, 8.5, 17,
    -19.5, -11, -2.5, 6, 14.5,
    -29, -19, -9, 1, 11,
    -30, -20.5, -11, -1.5, 8
]

coordinate_y_35_insole = [
    -100.5, -104, -100.7, -88, -73,
    -70.8, -68.9, -65, -59.8, -54,
    -39, -36, -32, -28.5, -25.2,
    0, 0, 0, 0, 0,
    40, 40, 40, 40, 40,
    70, 70, 70, 70, 70,
    90, 90, 90, 90, 90,
]

# 传感器读数（每帧）
class SensorData:
    def __init__(self, dn, sn, timestamp, pressure_sensors, magnetometer, gyroscope, accelerometer):
        self.timestamp = timestamp
        self.dn = dn
        self.sn = sn
        self.pressure_sensors = pressure_sensors  # 这里仍然用pressure_sensors来表示电阻值
        self.magnetometer = magnetometer
        self.gyroscope = gyroscope
        self.accelerometer = accelerometer
    
    def sensor_v_to_r(self):
        v_ref = 0.312
        R1 = 5000
        for i in range(len(self.pressure_sensors)):
            current_v = self.pressure_sensors[i] / 1000
            if current_v > v_ref:
                self.pressure_sensors[i] = R1 * v_ref / (current_v - v_ref)
            else:
                self.pressure_sensors[i] = float('inf')

    def sensor_r_to_f(self, params):
        for i in range(len(self.pressure_sensors)):
            sensor_id = i + 1
            if sensor_id in params:
                k, alpha = params[sensor_id]
                R = self.pressure_sensors[i]
                if R != float('inf'):
                    res = (R / k) ** (1 / alpha)
                    if res < 1e-2:
                        self.pressure_sensors[i] = 0  # 处理压力值过小的情况
                    elif res > 50:
                        self.pressure_sensors[i] = 50 # 处理异常值或超过量程的情况
                    else:
                        self.pressure_sensors[i] = res
                else:
                    self.pressure_sensors[i] = 0  # 处理电阻无限大的情况


# 传感器数据
class SensorDataList:
    def __init__(self, sensor_data_list):
        self.sensor_data_list = sensor_data_list
    
    # 提取加速度函数
    def get_acc(self):
        acc_x = [data.accelerometer[0] for data in self.sensor_data_list]
        acc_y = [data.accelerometer[1] for data in self.sensor_data_list]
        acc_z = [data.accelerometer[2] for data in self.sensor_data_list]
        return [acc_x, acc_y, acc_z]
    
    # 提取角速度函数
    def get_gyro(self):
        gyro_x = [data.gyroscope[0] for data in self.sensor_data_list]
        gyro_y = [data.gyroscope[1] for data in self.sensor_data_list]
        gyro_z = [data.gyroscope[2] for data in self.sensor_data_list]
        return [gyro_x, gyro_y, gyro_z]

    # 提取磁力计函数
    def get_mag(self):
        mag_x = [data.magnetometer[0] for data in self.sensor_data_list]
        mag_y = [data.magnetometer[1] for data in self.sensor_data_list]
        mag_z = [data.magnetometer[2] for data in self.sensor_data_list]
        return [mag_x, mag_y, mag_z]

    # 提取时间戳函数
    def get_timestamp(self):
        timestamp = [data.timestamp for data in self.sensor_data_list]
        return timestamp

    # 提取压力矩阵函数
    def get_pressure(self):
        pressure = [data.pressure_sensors for data in self.sensor_data_list]
        return pressure
    
    # 提取压力和函数
    def get_pressure_sum(self):
        pressure_sum = []
        for i in self.sensor_data_list:
            pressure_sum.append(np.sum(i.pressure_sensors))
        return pressure_sum

    # 提取COP函数
    def get_pressure_cop(self):
        pressure_x_cop = []
        pressure_y_cop = []
        for i in self.sensor_data_list:
            for j in range(len(i.pressure_sensors)):
                weight_coordinate_x = []
                weight_coordinate_x.append(coordinate_x_35_insole[j] * i.pressure_sensors[j])
                weight_coordinate_y = []
                weight_coordinate_y.append(coordinate_y_35_insole[j] * i.pressure_sensors[j])

            pressure_y_cop.append(np.sum(weight_coordinate_y) / np.sum(i.pressure_sensors))
            pressure_x_cop.append(np.sum(weight_coordinate_x) / np.sum(i.pressure_sensors))

        return pressure_x_cop, pressure_y_cop
                


# 收集数据函数（逐个）
# ESP32的二进制数据 -> SensorData对象
# 解析传入的二进制数据，返回SensorData对象
def parse_sensor_data(data):
    # 首先检查起始和结束标志是否正确
    if data[:2] == b'\x5a\x5a' and data[-2:] == b'\xa5\xa5':
        # 解析DN和SN字段
        dn = struct.unpack('BBBBBB', data[2:8])
        sn = struct.unpack('B', data[8:9])[0]
        # 解析时间戳（4字节整数）
        timestamp = struct.unpack('<I', data[9:13])[0]
        # 解析时间戳毫秒（2字节整数）
        timems = struct.unpack('<H', data[13:15])[0]
        # 设置压力传感器数据的起始位置
        pressure_start_position = 15
        # 解析每个压力传感器的整数值
        pressure_sensors = [struct.unpack('<i', data[pressure_start_position + i * 4:pressure_start_position + (i + 1) * 4])[0]
                            for i in range(sn)]
        # 设置和解析磁力计、陀螺仪、加速度计数据的起始和结束位置
        magnetometer_start = pressure_start_position + sn * 4
        magnetometer = struct.unpack('<3f', data[magnetometer_start:magnetometer_start + 12])
        gyroscope_start = magnetometer_start + 12
        gyroscope = struct.unpack('<3f', data[gyroscope_start:gyroscope_start + 12])
        accelerometer_start = gyroscope_start + 12
        accelerometer = struct.unpack('<3f', data[accelerometer_start:accelerometer_start + 12])
        
        return SensorData(dn,sn,timestamp + timems/1000, pressure_sensors, magnetometer, gyroscope, accelerometer)
    # 忽略标志错误的数据包
    else:
        return None

# 收集数据函数
# SensorData对象列表 -> CSV
def save_sensor_data_to_csv(sensor_data_list, filename):
    """
    将同一批 SensorData 按 dn 分组分别写入多个 CSV 文件。
    输出文件名 = <输入文件名去掉扩展名>_dn_<DNHEX>.csv
      例如: sensor_data.csv -> sensor_data_dn_E00AD6773866.csv
    说明:
      - 同一 dn 的 sn 恒定，使用该组第一条记录的 sn 来确定压力列数
      - 头部第一行写入: // DN: <dn十六进制>, SN: <sn>
    """
    if not sensor_data_list:
        # 没有数据，直接返回
        return

    # 将 filename 拆分为目录、主名、扩展名
    base_dir, base_name = os.path.split(filename)
    stem, ext = os.path.splitext(base_name)
    if ext == "":
        ext = ".csv"  # 没有扩展名则默认 .csv

    # 分组：dn -> list[SensorData]
    groups = {}
    for sd in sensor_data_list:
        # 将 dn（可能是 bytes/tuple/list）统一转成 hashable 的 bytes，再到大写 HEX 字符串用于文件名和头
        if isinstance(sd.dn, (bytes, bytearray)):
            dn_bytes = bytes(sd.dn)
        elif isinstance(sd.dn, (tuple, list)):
            dn_bytes = bytes(sd.dn)
        else:
            # 若用户在别处把 dn 设成了 int/str，这里也做个兜底
            if isinstance(sd.dn, int):
                # 将 int 当作 6 字节（大端）截断/填充
                dn_bytes = sd.dn.to_bytes(6, byteorder="big", signed=False)
            elif isinstance(sd.dn, str):
                # 允许形如 "E0 0A D6 77 38 66" 或 "E00AD6773866"
                hex_str = sd.dn.replace(" ", "").replace("-", "")
                dn_bytes = bytes.fromhex(hex_str[-12:].rjust(12, "0"))
            else:
                raise TypeError(f"Unsupported dn type: {type(sd.dn)}")

        dn_hex = dn_bytes.hex().upper()
        groups.setdefault(dn_hex, []).append(sd)

    # 逐组写文件
    for dn_hex, items in groups.items():
        # 取该设备的 sn（同一设备恒定）
        sn = int(items[0].sn)

        out_name = f"{stem}_dn_{dn_hex}{ext}"
        out_path = os.path.join(base_dir, out_name)

        with open(out_path, "w", newline="") as csvfile:
            header_writer = csv.writer(csvfile)
            # 头注释：DN 用连续 HEX，SN 用十进制
            header_writer.writerow([f"// DN: {dn_hex}, SN: {sn}"])

            # 列标题依据 sn 构建
            fieldnames = (
                ["Timestamp"]
                + [f"P{i + 1}" for i in range(sn)]
                + ["Mag_x", "Mag_y", "Mag_z",
                   "Gyro_x", "Gyro_y", "Gyro_z",
                   "Acc_x", "Acc_y", "Acc_z"]
            )
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for sd in items:
                # 压力长度以 sn 为准；若长度不一致，仅截断/补零以避免异常
                pressures = list(sd.pressure_sensors[:sn])
                if len(pressures) < sn:
                    pressures.extend([0] * (sn - len(pressures)))

                row = {"Timestamp": sd.timestamp}
                row.update({f"P{i + 1}": pressures[i] for i in range(sn)})
                row.update({
                    "Mag_x": sd.magnetometer[0], "Mag_y": sd.magnetometer[1], "Mag_z": sd.magnetometer[2],
                    "Gyro_x": sd.gyroscope[0],   "Gyro_y": sd.gyroscope[1],   "Gyro_z": sd.gyroscope[2],
                    "Acc_x": sd.accelerometer[0], "Acc_y": sd.accelerometer[1], "Acc_z": sd.accelerometer[2],
                })
                writer.writerow(row)
# 读取数据函数
# CSV -> 数据列表
def read_sensor_data_from_csv(filepath, p_num=35):
    # Read the CSV file into a pandas DataFrame
    with open(filepath, 'r') as file:
        first_line = file.readline()
        
    if first_line.startswith('"//'):
        df = pd.read_csv(filepath, skiprows=1, low_memory=False)
    else:
        df = pd.read_csv(filepath, low_memory=False)
    
    
    # Check if the Timestamp column exists
    if 'Timestamp' not in df.columns:
        raise ValueError("The CSV file must contain a 'Timestamp' column.")
    
    # Convert timestamp to float
    df['Timestamp'] = df['Timestamp'].astype(float)
    
    # Extract sensor data
    pressure_sensors = df[[f'P{i}' for i in range(1, p_num + 1)]].astype(int).values.tolist()
    magnetometer = df[['Mag_x', 'Mag_y', 'Mag_z']].astype(float).values.tolist()
    gyroscope = df[['Gyro_x', 'Gyro_y', 'Gyro_z']].astype(float).values.tolist()
    accelerometer = df[['Acc_x', 'Acc_y', 'Acc_z']].astype(float).values.tolist()
    
    # Create a list of SensorData instances
    sensor_data_list = [
        SensorData(
            timestamp=row['Timestamp'],
            pressure_sensors=pressure_sensors[idx],
            magnetometer=magnetometer[idx],
            gyroscope=gyroscope[idx],
            accelerometer=accelerometer[idx]
        )
        for idx, row in df.iterrows()
    ]

    return sensor_data_list

# 测试函数
def test_save():
    data_example = b'ZZ\xe0\n\xd6w8f\xb7\x017\x01\x00\x008\x01\x00\x008\x01\x00\x008\x01\x00\x007\x01\x00\x009\x01\x00\x00:\x01\x00\x00:\x01\x00\x00:\x01\x00\x00;\x01\x00\x00\x00\x00\x80@\x00\x00`A\x00\x00\x1cB\xff\xffy=\xff\xff\xf9\xbd\x00\x00\x00\x00\x00\x00U=\x00\x00\xd3\xbc\x00\xe0~?\xa5\xa5'
    sensor_data = parse_sensor_data(data_example)

    if sensor_data:
        # 将数据保存到CSV文件
        save_sensor_data_to_csv([sensor_data], 'sensor_data.csv')

def test_read():
    return read_sensor_data_from_csv("./sensor_data.csv", 10)

if __name__ == "__main__":
    # 示例数据
    test_save()
    a = test_read()
    print(a)