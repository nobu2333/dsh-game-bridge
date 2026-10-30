"""读取 XInput 0..3 槽位状态，确认虚拟手柄是否存在/按键是否真的生效。"""
import ctypes

class XINPUT_STATE(ctypes.Structure):
    _fields_ = [("dwPacketNumber", ctypes.c_ulong), ("Gamepad", ctypes.c_byte * 16)]

xinput = ctypes.windll.xinput1_4
for slot in range(4):
    state = XINPUT_STATE()
    rc = xinput.XInputGetState(slot, ctypes.byref(state))
    if rc == 0:
        raw = bytes(state.Gamepad)
        # wButtons 是前 2 字节（小端）
        buttons = int.from_bytes(raw[0:2], "little")
        print(f"slot {slot}: CONNECTED buttons=0x{buttons:04x}")
    else:
        print(f"slot {slot}: none (rc={rc})")
