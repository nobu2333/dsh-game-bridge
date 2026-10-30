"""一次性实验：新开一个虚拟手柄，看它落在哪个 XInput 槽位，退出后是否释放。"""
import ctypes
import time

import vgamepad as vg


class XINPUT_STATE(ctypes.Structure):
    _fields_ = [("dwPacketNumber", ctypes.c_ulong), ("Gamepad", ctypes.c_byte * 16)]


def probe(tag):
    xinput = ctypes.windll.xinput1_4
    slots = []
    for slot in range(4):
        state = XINPUT_STATE()
        if xinput.XInputGetState(slot, ctypes.byref(state)) == 0:
            slots.append(slot)
    print(f"{tag}: connected slots = {slots}", flush=True)


probe("before-create")
pad = vg.VX360Gamepad()
time.sleep(1.0)
probe("after-create")
pad.press_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_A)
pad.update()
time.sleep(0.5)
probe("while-A-held")
pad.reset()
pad.update()
time.sleep(0.5)
print("exiting process (device should disappear)", flush=True)
