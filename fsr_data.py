# pip install pyserial matplotlib
import serial
import threading
import time
import queue
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from collections import deque

# ================= 配置参数 =================
COM_PORT = 'COM3'       # <--- 请在此处修改为你的实际串口号
BAUD_RATE = 115200      # 波特率 (根据协议)
MAX_POINTS = 500        # 屏幕上显示的最多数据点数 (控制曲线窗口大小)
# ============================================

# 用于在串口线程和绘图线程之间传递数据的线程安全队列
data_queue = queue.Queue()

# 标志位，用于安全退出线程
is_running = True

def serial_read_thread():
    """
    后台线程：负责持续读取串口数据，并根据协议解析数据包
    协议：[帧头1 0x40] [帧头2 0x5C] [压力高8位] [压力中8位] [压力低8位] [校验和]
    """
    global is_running
    try:
        # 打开串口 (8位数据位，1位停止位，无校验是默认设置)
        ser = serial.Serial(COM_PORT, BAUD_RATE, timeout=0.1)
        print(f"成功打开串口: {COM_PORT} @ {BAUD_RATE}")
        
        buffer = bytearray()
        
        while is_running:
            if ser.in_waiting > 0:
                # 读取当前缓冲区所有数据并加入我们的拼包缓存
                data = ser.read(ser.in_waiting)
                buffer.extend(data)
                
                # 当缓存长度大于等于一帧长度(6字节)时，开始寻找有效包
                while len(buffer) >= 6:
                    # 寻找帧头 0x40 0x5C
                    if buffer[0] == 0x40 and buffer[1] == 0x5C:
                        packet = buffer[:6]
                        
                        # 计算校验和 (前5字节相加，取低8位)
                        checksum = sum(packet[:5]) & 0xFF
                        
                        # 校验匹配
                        if checksum == packet[5]:
                            # 解析压力值 (高8位 << 16 | 中8位 << 8 | 低8位)
                            pressure = (packet[2] << 16) | (packet[3] << 8) | packet[4]
                            
                            # 将解析出的数值放入队列供主线程绘图
                            data_queue.put(pressure)
                            
                            # 从缓存中移除已处理的一帧数据
                            del buffer[:6]
                        else:
                            # 校验失败，可能是假帧头，丢弃第一个字节重新寻找
                            del buffer[0:1]
                    else:
                        # 第一个字节不是帧头，丢弃
                        del buffer[0:1]
            else:
                time.sleep(0.01) # 防止CPU占用过高
                
    except serial.SerialException as e:
        print(f"串口错误: {e}")
        is_running = False
    except Exception as e:
        print(f"发生未知错误: {e}")
        is_running = False
    finally:
        if 'ser' in locals() and ser.is_open:
            ser.close()
            print("串口已关闭。")

# ================= 主程序 (绘图部分) =================

# 设置数据容器，使用 deque 方便实现滑动窗口效果
x_data = deque(maxlen=MAX_POINTS)
y_data = deque(maxlen=MAX_POINTS)
counter = 0

# 初始化画布
fig, ax = plt.subplots()
ax.set_title("Real-Time Pressure Data (实时压力值)")
ax.set_xlabel("Samples (采样点)")
ax.set_ylabel("Pressure Value (压力值)")
ax.grid(True)
line, = ax.plot([], [], 'b-', label='Pressure')
ax.legend()

def update_plot(frame):
    """
    动画更新函数：定期从队列中取出新数据并更新图表
    """
    global counter
    
    # 将队列中的所有新数据全部读出
    has_new_data = False
    while not data_queue.empty():
        pressure = data_queue.get()
        x_data.append(counter)
        y_data.append(pressure)
        counter += 1
        has_new_data = True
        
    if has_new_data:
        # 更新线条数据
        line.set_data(x_data, y_data)
        
        # 动态调整坐标轴范围
        ax.set_xlim(max(0, counter - MAX_POINTS), counter)
        if y_data:
            min_y = min(y_data)
            max_y = max(y_data)
            padding = (max_y - min_y) * 0.1 if max_y != min_y else 10
            ax.set_ylim(min_y - padding, max_y + padding)
            
    return line,

# 拦截窗口关闭事件，以便干净地退出串口线程
def on_close(event):
    global is_running
    print("正在关闭程序...")
    is_running = False

fig.canvas.mpl_connect('close_event', on_close)

if __name__ == '__main__':
    # 1. 启动串口接收后台线程
    thread = threading.Thread(target=serial_read_thread, daemon=True)
    thread.start()
    
    # 2. 启动 matplotlib 动画 (主线程阻塞在此)
    # interval=50 表示每 50 毫秒刷新一次图像
    ani = animation.FuncAnimation(fig, update_plot, interval=50, cache_frame_data=False)
    
    # 显示窗口
    plt.show()
    
    # 窗口关闭后，等待线程结束
    is_running = False
    thread.join(timeout=1.0)
    print("程序已完全退出。")
