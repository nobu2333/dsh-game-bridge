"""只读性能测量：attach / snapshot(OCR) / events 的耗时（dry-run，不注入任何输入）。"""
import time

from dsh_game_core.session import GameSession

s = GameSession(control_backend="dry-run")

t0 = time.perf_counter()
s.attach({"window": "Cuphead"})
print(f"attach: {(time.perf_counter() - t0) * 1000:.0f} ms")

for i in range(1, 4):
    t0 = time.perf_counter()
    shot = s.snapshot(ocr=True)
    ms = (time.perf_counter() - t0) * 1000
    print(f"snapshot#{i} (ocr): {ms:.0f} ms, ocr_lines={len(shot['ocr'])}, {shot['width']}x{shot['height']}")

t0 = time.perf_counter()
ev = s.events()
print(f"events: {(time.perf_counter() - t0) * 1000:.0f} ms -> {ev['event']}")

t0 = time.perf_counter()
s.snapshot(ocr=False)
print(f"snapshot (no ocr): {(time.perf_counter() - t0) * 1000:.0f} ms")

t0 = time.perf_counter()
s.windows()
print(f"windows: {(time.perf_counter() - t0) * 1000:.0f} ms")

t0 = time.perf_counter()
s.status()
print(f"status: {(time.perf_counter() - t0) * 1000:.0f} ms")

s.close()
